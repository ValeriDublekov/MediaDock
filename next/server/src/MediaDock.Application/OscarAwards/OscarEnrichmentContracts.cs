using MediaDock.Application.Metadata;

namespace MediaDock.Application.OscarAwards;

public static class OscarEnrichmentStatuses
{
    public const string Pending = "pending";
    public const string Enriched = "enriched";
    public const string NotFound = "not_found";
    public const string TemporaryError = "temporary_error";
}

public sealed record OscarEnrichmentCandidate(
    long Id,
    string FilmTitle,
    int FilmYear,
    string? ImdbId,
    int AttemptCount);

public sealed record OscarEnrichmentUpdate(
    string Status,
    int AttemptCount,
    DateTimeOffset AttemptedAt,
    DateTimeOffset? NextAttemptAt,
    string? ErrorCode,
    MetadataDetails? Metadata);

public sealed record OscarEnrichmentSummary(
    int EligibleFilms,
    int AttemptedFilms,
    int EnrichedFilms,
    int NotFoundFilms,
    int TemporaryErrors,
    int CacheHits,
    int HttpAttempts,
    bool StoppedForQuota);

public interface IOscarEnrichmentRepository
{
    Task<IReadOnlyList<OscarEnrichmentCandidate>> GetEligibleCandidatesAsync(
        DateTimeOffset now,
        int limit,
        CancellationToken cancellationToken = default);

    Task SaveOutcomeAsync(
        long filmId,
        OscarEnrichmentUpdate update,
        CancellationToken cancellationToken = default);
}