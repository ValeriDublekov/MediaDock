using System.Security.Cryptography;
using System.Text;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;

namespace MediaDock.Infrastructure.OscarAwards;

public sealed record OscarImportSummary(
    int RowsRead,
    int RowsSkippedByYear,
    int RowsSkippedByCategory,
    int RowsSkippedWithoutFilm,
    int TitlesCreated,
    int OscarFilmsCreated,
    int NominationsCreated,
    int NominationsUpdated);

public sealed class OscarDatasetImporter(MediaDockDbContext dbContext)
{
    public async Task<OscarImportSummary> ImportAsync(
        string path,
        int yearAfter = 1980,
        CancellationToken cancellationToken = default)
    {
        var dataset = OscarCsvDatasetReader.Read(path, yearAfter, cancellationToken);
        if (dataset.Rows.Count == 0)
        {
            return CreateSummary(dataset, 0, 0, 0, 0);
        }

        var now = DateTimeOffset.UtcNow;
        var preparedRows = dataset.Rows
            .Select(row => new PreparedOscarRow(
                row,
                NormalizeTitle(row.FilmTitle),
                CreateFilmStableKey(row, NormalizeTitle(row.FilmTitle))))
            .Select(prepared => prepared with
            {
                ImportKey = CreateNominationImportKey(prepared.Row, prepared.FilmStableKey)
            })
            .ToArray();

        await using var transaction = await dbContext.Database.BeginTransactionAsync(cancellationToken);
        try
        {
            var filmKeys = preparedRows.Select(row => row.FilmStableKey).Distinct(StringComparer.Ordinal).ToArray();
            var nominationKeys = preparedRows.Select(row => row.ImportKey).Distinct(StringComparer.Ordinal).ToArray();
            var oscarFilms = await dbContext.OscarFilms
                .Include(film => film.Title)
                .Where(film => filmKeys.Contains(film.StableKey))
                .ToListAsync(cancellationToken);
            var filmsByStableKey = oscarFilms.ToDictionary(film => film.StableKey, StringComparer.Ordinal);
            var nominations = await dbContext.OscarNominations
                .Where(nomination => nominationKeys.Contains(nomination.ImportKey))
                .ToListAsync(cancellationToken);
            var nominationsByImportKey = nominations.ToDictionary(
                nomination => nomination.ImportKey,
                StringComparer.Ordinal);

            var titlesByImdbId = new Dictionary<string, Title>(StringComparer.OrdinalIgnoreCase);
            var titlesByIdentity = new Dictionary<string, Title>(StringComparer.Ordinal);
            foreach (var film in oscarFilms)
            {
                AddTitle(film.Title, titlesByImdbId, titlesByIdentity);
            }

            var imdbIds = preparedRows
                .Where(row => row.Row.ImdbId is not null)
                .Select(row => row.Row.ImdbId!)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToArray();
            var normalizedTitles = preparedRows
                .Select(row => row.NormalizedTitle)
                .Distinct(StringComparer.Ordinal)
                .ToArray();
            var filmYears = preparedRows.Select(row => row.Row.FilmYear).Distinct().ToArray();
            var existingTitles = await dbContext.Titles
                .Where(title => (title.ImdbId != null && imdbIds.Contains(title.ImdbId))
                    || (title.MediaType == "movie"
                        && title.Year.HasValue
                        && filmYears.Contains(title.Year.Value)
                        && normalizedTitles.Contains(title.NormalizedTitle)))
                .OrderBy(title => title.Id)
                .ToListAsync(cancellationToken);
            foreach (var title in existingTitles)
            {
                AddTitle(title, titlesByImdbId, titlesByIdentity);
            }

            var titlesCreated = 0;
            var oscarFilmsCreated = 0;
            var nominationsCreated = 0;
            var nominationsUpdated = 0;
            foreach (var prepared in preparedRows)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var row = prepared.Row;
                filmsByStableKey.TryGetValue(prepared.FilmStableKey, out var oscarFilm);
                var title = FindTitle(row, prepared.NormalizedTitle, titlesByImdbId, titlesByIdentity)
                    ?? oscarFilm?.Title;
                if (title is null)
                {
                    title = CreatePlaceholderTitle(row, prepared.NormalizedTitle, now);
                    dbContext.Titles.Add(title);
                    AddTitle(title, titlesByImdbId, titlesByIdentity);
                    titlesCreated++;
                }
                else
                {
                    FillMissingTitleFields(title, row, prepared.NormalizedTitle, now);
                }

                if (oscarFilm is null)
                {
                    oscarFilm = new OscarFilm
                    {
                        StableKey = prepared.FilmStableKey,
                        EnrichmentStatus = "pending",
                        ImportedAt = now,
                        UpdatedAt = now,
                        Title = title
                    };
                    dbContext.OscarFilms.Add(oscarFilm);
                    filmsByStableKey.Add(prepared.FilmStableKey, oscarFilm);
                    oscarFilmsCreated++;
                }

                ApplyFilmSourceData(oscarFilm, row, prepared.NormalizedTitle, title, now);
                if (!nominationsByImportKey.TryGetValue(prepared.ImportKey, out var nomination))
                {
                    nomination = new OscarNomination
                    {
                        ImportKey = prepared.ImportKey,
                        ImportedAt = now,
                        UpdatedAt = now
                    };
                    dbContext.OscarNominations.Add(nomination);
                    nominationsByImportKey.Add(prepared.ImportKey, nomination);
                    ApplyNominationSourceData(nomination, row, oscarFilm, now);
                    nominationsCreated++;
                }
                else if (ApplyNominationSourceData(nomination, row, oscarFilm, now))
                {
                    nominationsUpdated++;
                }
            }

            await dbContext.SaveChangesAsync(cancellationToken);
            await transaction.CommitAsync(cancellationToken);
            return CreateSummary(dataset, titlesCreated, oscarFilmsCreated, nominationsCreated, nominationsUpdated);
        }
        catch
        {
            await transaction.RollbackAsync(CancellationToken.None);
            dbContext.ChangeTracker.Clear();
            throw;
        }
    }

    private static OscarImportSummary CreateSummary(
        OscarCsvReadResult dataset,
        int titlesCreated,
        int oscarFilmsCreated,
        int nominationsCreated,
        int nominationsUpdated) =>
        new(
            dataset.RowsRead,
            dataset.RowsSkippedByYear,
            dataset.RowsSkippedByCategory,
            dataset.RowsSkippedWithoutFilm,
            titlesCreated,
            oscarFilmsCreated,
            nominationsCreated,
            nominationsUpdated);

    private static void AddTitle(
        Title title,
        IDictionary<string, Title> titlesByImdbId,
        IDictionary<string, Title> titlesByIdentity)
    {
        if (!string.IsNullOrWhiteSpace(title.ImdbId))
        {
            titlesByImdbId.TryAdd(title.ImdbId, title);
        }

        if (title.MediaType == "movie" && title.Year is { } year)
        {
            titlesByIdentity.TryAdd(CreateTitleIdentity(title.NormalizedTitle, year), title);
        }
    }

    private static Title? FindTitle(
        OscarDatasetRow row,
        string normalizedTitle,
        IReadOnlyDictionary<string, Title> titlesByImdbId,
        IReadOnlyDictionary<string, Title> titlesByIdentity)
    {
        if (row.ImdbId is not null && titlesByImdbId.TryGetValue(row.ImdbId, out var byImdbId))
        {
            return byImdbId;
        }

        return titlesByIdentity.GetValueOrDefault(CreateTitleIdentity(normalizedTitle, row.FilmYear));
    }

    private static Title CreatePlaceholderTitle(
        OscarDatasetRow row,
        string normalizedTitle,
        DateTimeOffset now) =>
        new()
        {
            TitleText = row.FilmTitle,
            NormalizedTitle = normalizedTitle,
            Year = row.FilmYear,
            MediaType = "movie",
            SourceType = "movie",
            ContentKind = "standard",
            ImdbId = row.ImdbId,
            FirstSeenAt = now,
            LastSeenAt = now,
            UpdatedAt = now
        };

    private static void FillMissingTitleFields(
        Title title,
        OscarDatasetRow row,
        string normalizedTitle,
        DateTimeOffset now)
    {
        var changed = false;
        if (string.IsNullOrWhiteSpace(title.TitleText))
        {
            title.TitleText = row.FilmTitle;
            changed = true;
        }

        if (string.IsNullOrWhiteSpace(title.NormalizedTitle))
        {
            title.NormalizedTitle = normalizedTitle;
            changed = true;
        }

        if (title.Year is null)
        {
            title.Year = row.FilmYear;
            changed = true;
        }

        if (string.IsNullOrWhiteSpace(title.MediaType))
        {
            title.MediaType = "movie";
            changed = true;
        }

        if (title.SourceType is null)
        {
            title.SourceType = "movie";
            changed = true;
        }

        if (title.ContentKind is null)
        {
            title.ContentKind = "standard";
            changed = true;
        }

        if (title.ImdbId is null && row.ImdbId is not null)
        {
            title.ImdbId = row.ImdbId;
            changed = true;
        }

        if (changed)
        {
            title.UpdatedAt = now;
        }
    }

    private static void ApplyFilmSourceData(
        OscarFilm film,
        OscarDatasetRow row,
        string normalizedTitle,
        Title title,
        DateTimeOffset now)
    {
        film.FilmTitle = row.FilmTitle;
        film.NormalizedTitle = normalizedTitle;
        film.FilmYear = row.FilmYear;
        film.ImdbId = row.ImdbId;
        film.Title = title;
        film.TitleId = title.Id;
        if (film.ImportedAt == default)
        {
            film.ImportedAt = now;
        }

        film.UpdatedAt = now;
    }

    private static bool ApplyNominationSourceData(
        OscarNomination nomination,
        OscarDatasetRow row,
        OscarFilm film,
        DateTimeOffset now)
    {
        var changed = false;
        changed |= SetIfDifferent(nomination.Ceremony, row.Ceremony, value => nomination.Ceremony = value);
        changed |= SetIfDifferent(nomination.Class, row.Class, value => nomination.Class = value);
        changed |= SetIfDifferent(nomination.CanonicalCategory, row.CanonicalCategory, value => nomination.CanonicalCategory = value);
        changed |= SetIfDifferent(nomination.Category, row.Category, value => nomination.Category = value);
        changed |= SetIfDifferent(nomination.Name, row.Name, value => nomination.Name = value);
        changed |= SetIfDifferent(nomination.Nominees, row.Nominees, value => nomination.Nominees = value);
        changed |= SetIfDifferent(nomination.NomineeIds, row.NomineeIds, value => nomination.NomineeIds = value);
        changed |= SetIfDifferent(nomination.Detail, row.Detail, value => nomination.Detail = value);
        changed |= SetIfDifferent(nomination.IsWinner, row.IsWinner, value => nomination.IsWinner = value);
        changed |= SetIfDifferent(nomination.OscarFilmId, film.Id, value => nomination.OscarFilmId = value);
        if (nomination.OscarFilm != film)
        {
            nomination.OscarFilm = film;
            changed = true;
        }

        if (nomination.ImportedAt == default)
        {
            nomination.ImportedAt = now;
        }

        if (nomination.UpdatedAt == default || changed)
        {
            nomination.UpdatedAt = now;
        }

        return changed;
    }

    private static bool SetIfDifferent<T>(T current, T value, Action<T> setter)
    {
        if (EqualityComparer<T>.Default.Equals(current, value))
        {
            return false;
        }

        setter(value);
        return true;
    }

    private static string CreateFilmStableKey(OscarDatasetRow row, string normalizedTitle) =>
        row.ImdbId is not null
            ? $"imdb:{row.ImdbId.ToLowerInvariant()}"
            : $"title:{CreateTitleIdentity(normalizedTitle, row.FilmYear)}";

    private static string CreateNominationImportKey(OscarDatasetRow row, string filmStableKey)
    {
        var nomineeIdentity = string.IsNullOrWhiteSpace(row.NomineeIds) ? row.Name : row.NomineeIds;
        var identity = string.Join('\u001f',
            row.Ceremony.ToString(System.Globalization.CultureInfo.InvariantCulture),
            row.CanonicalCategory.Trim().ToUpperInvariant(),
            filmStableKey,
            NormalizeIdentity(nomineeIdentity),
            NormalizeIdentity(row.Nominees),
            NormalizeIdentity(row.Detail));
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes($"v1:{identity}"))).ToLowerInvariant();
    }

    private static string CreateTitleIdentity(string normalizedTitle, int year) =>
        $"{normalizedTitle}|{year.ToString(System.Globalization.CultureInfo.InvariantCulture)}";

    private static string NormalizeTitle(string value) => NormalizeIdentity(value).ToLowerInvariant();

    private static string NormalizeIdentity(string value) =>
        string.Join(' ', value.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));

    private sealed record PreparedOscarRow(OscarDatasetRow Row, string NormalizedTitle, string FilmStableKey)
    {
        public string ImportKey { get; init; } = string.Empty;
    }
}