using System.Security.Cryptography;
using System.Text;
using MediaDock.Application.Metadata;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;
using Npgsql;

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
        try
        {
            return await ImportOnceAsync(path, yearAfter, cancellationToken);
        }
        catch (DbUpdateException exception) when (IsImdbIdentityUniqueViolation(exception))
        {
            dbContext.ChangeTracker.Clear();
            return await ImportOnceAsync(path, yearAfter, cancellationToken);
        }
    }

    private async Task<OscarImportSummary> ImportOnceAsync(
        string path,
        int yearAfter,
        CancellationToken cancellationToken)
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
            var filmKeys = preparedRows
                .SelectMany(row => new[]
                {
                    row.FilmStableKey,
                    CreateTitleFilmStableKey(row.NormalizedTitle, row.Row.FilmYear)
                })
                .Distinct(StringComparer.Ordinal)
                .ToArray();
            var nominationKeys = preparedRows
                .SelectMany(row => new[]
                {
                    row.ImportKey,
                    CreateNominationImportKey(
                        row.Row,
                        CreateTitleFilmStableKey(row.NormalizedTitle, row.Row.FilmYear))
                })
                .Distinct(StringComparer.Ordinal)
                .ToArray();
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
            var titlesByIdentity = new Dictionary<string, List<Title>>(StringComparer.Ordinal);
            foreach (var film in oscarFilms)
            {
                film.ImdbId = ImdbIdNormalizer.Normalize(film.ImdbId);
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
                if (oscarFilm is null)
                {
                    var titleStableKey = CreateTitleFilmStableKey(prepared.NormalizedTitle, row.FilmYear);
                    if (filmsByStableKey.TryGetValue(titleStableKey, out var titleKeyedFilm)
                        && ImdbIdNormalizer.IsCompatible(titleKeyedFilm.ImdbId, row.ImdbId))
                    {
                        oscarFilm = titleKeyedFilm;
                    }
                }

                var title = FindTitle(row, prepared.NormalizedTitle, titlesByImdbId, titlesByIdentity)
                    ?? (oscarFilm is not null
                        && ImdbIdNormalizer.IsCompatible(oscarFilm.Title.ImdbId, row.ImdbId)
                            ? oscarFilm.Title
                            : null);
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
                var nominationImportKey = CreateNominationImportKey(row, oscarFilm.StableKey);
                if (!nominationsByImportKey.TryGetValue(nominationImportKey, out var nomination))
                {
                    nomination = new OscarNomination
                    {
                        ImportKey = nominationImportKey,
                        ImportedAt = now,
                        UpdatedAt = now
                    };
                    dbContext.OscarNominations.Add(nomination);
                    nominationsByImportKey.Add(nominationImportKey, nomination);
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
        IDictionary<string, List<Title>> titlesByIdentity)
    {
        var imdbId = ImdbIdNormalizer.Normalize(title.ImdbId);
        if (imdbId is not null)
        {
            title.ImdbId = imdbId;
            titlesByImdbId.TryAdd(imdbId, title);
        }

        if (title.MediaType == "movie" && title.Year is { } year)
        {
            var identity = CreateTitleIdentity(title.NormalizedTitle, year);
            if (!titlesByIdentity.TryGetValue(identity, out var candidates))
            {
                candidates = [];
                titlesByIdentity.Add(identity, candidates);
            }

            if (!candidates.Contains(title))
            {
                candidates.Add(title);
            }
        }
    }

    private static Title? FindTitle(
        OscarDatasetRow row,
        string normalizedTitle,
        IReadOnlyDictionary<string, Title> titlesByImdbId,
        IReadOnlyDictionary<string, List<Title>> titlesByIdentity)
    {
        if (row.ImdbId is not null && titlesByImdbId.TryGetValue(row.ImdbId, out var byImdbId))
        {
            return byImdbId;
        }

        return titlesByIdentity.TryGetValue(CreateTitleIdentity(normalizedTitle, row.FilmYear), out var candidates)
            ? candidates.FirstOrDefault(title => ImdbIdNormalizer.IsCompatible(title.ImdbId, row.ImdbId))
            : null;
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

        var imdbId = ImdbIdNormalizer.Normalize(row.ImdbId);
        if (title.ImdbId is null && imdbId is not null)
        {
            title.ImdbId = imdbId;
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
        var filmImdbId = ImdbIdNormalizer.Normalize(film.ImdbId);
        var titleImdbId = ImdbIdNormalizer.Normalize(title.ImdbId);
        var incomingImdbId = ImdbIdNormalizer.Normalize(row.ImdbId);
        if (!ImdbIdNormalizer.IsCompatible(filmImdbId, titleImdbId)
            || !ImdbIdNormalizer.IsCompatible(filmImdbId, incomingImdbId)
            || !ImdbIdNormalizer.IsCompatible(titleImdbId, incomingImdbId))
        {
            throw new InvalidOperationException("Oscar film IMDb identity conflicts with its linked title.");
        }

        film.FilmTitle = row.FilmTitle;
        film.NormalizedTitle = normalizedTitle;
        film.FilmYear = row.FilmYear;
        film.ImdbId = incomingImdbId ?? filmImdbId;
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
            : CreateTitleFilmStableKey(normalizedTitle, row.FilmYear);

    private static string CreateTitleFilmStableKey(string normalizedTitle, int year) =>
        $"title:{CreateTitleIdentity(normalizedTitle, year)}";

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

    private static bool IsImdbIdentityUniqueViolation(DbUpdateException exception) =>
        exception.InnerException is PostgresException
        {
            SqlState: PostgresErrorCodes.UniqueViolation,
            ConstraintName: "ux_titles_imdb_id"
        };

    private sealed record PreparedOscarRow(OscarDatasetRow Row, string NormalizedTitle, string FilmStableKey)
    {
        public string ImportKey { get; init; } = string.Empty;
    }
}