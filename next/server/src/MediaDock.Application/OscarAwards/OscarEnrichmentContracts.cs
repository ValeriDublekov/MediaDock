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
    string? TitleImdbId,
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

public static class OscarEnrichmentRunStatuses
{
    public const string Running = "running";
    public const string Succeeded = "succeeded";
    public const string Partial = "partial";
    public const string QuotaStopped = "quota_stopped";
    public const string Failed = "failed";
    public const string Cancelled = "cancelled";
}

public sealed record OscarEnrichmentRunProgress(
    int EligibleFilms,
    int ProcessedFilms,
    int EnrichedFilms,
    int NotFoundFilms,
    int TemporaryErrors,
    int CacheHits,
    int HttpAttempts);

public sealed record OscarEnrichmentRunResult(
    long RunId,
    DateTimeOffset StartedAt,
    DateTimeOffset FinishedAt,
    string Status,
    OscarEnrichmentSummary Summary);

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

public interface IOscarEnrichmentRunRepository
{
    Task<long> StartAsync(
        string trigger,
        DateTimeOffset startedAt,
        CancellationToken cancellationToken = default);

    Task SaveProgressAsync(
        long runId,
        OscarEnrichmentRunProgress progress,
        CancellationToken cancellationToken = default);

    Task FinishAsync(
        long runId,
        string status,
        DateTimeOffset finishedAt,
        OscarEnrichmentRunProgress progress,
        string? errorCode,
        CancellationToken cancellationToken = default);
}