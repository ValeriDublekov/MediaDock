using MediaDock.Application.OscarAwards;
using MediaDock.Application.Metadata;
using MediaDock.Infrastructure.Metadata;
using MediaDock.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace MediaDock.Infrastructure.OscarAwards;

public sealed class PostgresOscarEnrichmentRepository(MediaDockDbContext dbContext) : IOscarEnrichmentRepository
{
    public async Task<IReadOnlyList<OscarEnrichmentCandidate>> GetEligibleCandidatesAsync(
        DateTimeOffset now,
        int limit,
        CancellationToken cancellationToken = default) =>
        await dbContext.OscarFilms
            .AsNoTracking()
            .Where(film => (film.EnrichmentStatus == OscarEnrichmentStatuses.Pending
                    || film.EnrichmentStatus == OscarEnrichmentStatuses.TemporaryError)
                && (film.NextEnrichmentAttemptAt == null || film.NextEnrichmentAttemptAt <= now))
            .OrderByDescending(film => film.FilmYear)
            .ThenBy(film => film.StableKey)
            .ThenBy(film => film.Id)
            .Take(limit)
            .Select(film => new OscarEnrichmentCandidate(
                film.Id,
                film.FilmTitle,
                film.FilmYear,
                film.ImdbId,
                film.Title.ImdbId,
                film.EnrichmentAttemptCount))
            .ToListAsync(cancellationToken);

    public async Task SaveOutcomeAsync(
        long filmId,
        OscarEnrichmentUpdate update,
        CancellationToken cancellationToken = default)
    {
        try
        {
            await SaveOutcomeOnceAsync(filmId, update, cancellationToken);
        }
        catch (DbUpdateException exception) when (IsImdbIdentityUniqueViolation(exception))
        {
            dbContext.ChangeTracker.Clear();
            await SaveOutcomeOnceAsync(filmId, update, cancellationToken);
        }
    }

    private async Task SaveOutcomeOnceAsync(
        long filmId,
        OscarEnrichmentUpdate update,
        CancellationToken cancellationToken)
    {
        var film = await dbContext.OscarFilms
            .Include(candidate => candidate.Title)
            .SingleAsync(candidate => candidate.Id == filmId, cancellationToken);

        var metadata = update.Metadata;
        var filmImdbId = ImdbIdNormalizer.Normalize(film.ImdbId);
        var titleImdbId = ImdbIdNormalizer.Normalize(film.Title.ImdbId);
        var metadataImdbId = ImdbIdNormalizer.Normalize(metadata?.ImdbId);
        if (metadata is not null
            && (!ImdbIdNormalizer.IsCompatible(filmImdbId, titleImdbId)
                || !ImdbIdNormalizer.IsCompatible(filmImdbId, metadataImdbId)
                || !ImdbIdNormalizer.IsCompatible(titleImdbId, metadataImdbId)))
        {
            throw new InvalidOperationException("Oscar enrichment IMDb identity conflicts with its linked title.");
        }

        film.EnrichmentStatus = update.Status;
        film.EnrichmentAttemptCount = update.AttemptCount;
        film.LastEnrichmentAttemptAt = update.AttemptedAt;
        film.NextEnrichmentAttemptAt = update.NextAttemptAt;
        film.LastEnrichmentError = update.ErrorCode;
        film.UpdatedAt = update.AttemptedAt;

        if (metadata is not null)
        {
            film.ImdbId = filmImdbId;
            film.Title.ImdbId = titleImdbId;
            var imdbId = metadataImdbId ?? filmImdbId ?? titleImdbId;
            if (imdbId is not null)
            {
                var canonicalTitle = await dbContext.Titles
                    .SingleOrDefaultAsync(
                        title => title.Id != film.TitleId && title.ImdbId == imdbId,
                        cancellationToken);
                if (canonicalTitle is not null)
                {
                    film.Title = canonicalTitle;
                    film.TitleId = canonicalTitle.Id;
                }
            }

            var normalizedMetadata = metadata with { ImdbId = imdbId };
            TitleMetadataMapper.Apply(film.Title, normalizedMetadata, update.AttemptedAt, updateLastSeenAt: false);
            film.ImdbId = imdbId;
        }

        await dbContext.SaveChangesAsync(cancellationToken);
    }

    private static bool IsImdbIdentityUniqueViolation(DbUpdateException exception) =>
        exception.InnerException is PostgresException
        {
            SqlState: PostgresErrorCodes.UniqueViolation,
            ConstraintName: "ux_titles_imdb_id"
        };
}