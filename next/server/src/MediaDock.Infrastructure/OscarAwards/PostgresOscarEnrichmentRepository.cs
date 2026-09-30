using MediaDock.Application.OscarAwards;
using MediaDock.Infrastructure.Metadata;
using MediaDock.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

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
                film.EnrichmentAttemptCount))
            .ToListAsync(cancellationToken);

    public async Task SaveOutcomeAsync(
        long filmId,
        OscarEnrichmentUpdate update,
        CancellationToken cancellationToken = default)
    {
        var film = await dbContext.OscarFilms
            .Include(candidate => candidate.Title)
            .SingleAsync(candidate => candidate.Id == filmId, cancellationToken);

        film.EnrichmentStatus = update.Status;
        film.EnrichmentAttemptCount = update.AttemptCount;
        film.LastEnrichmentAttemptAt = update.AttemptedAt;
        film.NextEnrichmentAttemptAt = update.NextAttemptAt;
        film.LastEnrichmentError = update.ErrorCode;
        film.UpdatedAt = update.AttemptedAt;

        if (update.Metadata is not null)
        {
            var metadata = update.Metadata with
            {
                ImdbId = update.Metadata.ImdbId ?? film.ImdbId ?? film.Title.ImdbId
            };
            TitleMetadataMapper.Apply(film.Title, metadata, update.AttemptedAt, updateLastSeenAt: false);
            film.ImdbId = metadata.ImdbId;
        }

        await dbContext.SaveChangesAsync(cancellationToken);
    }
}