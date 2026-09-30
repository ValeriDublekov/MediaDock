using MediaDock.Application.Metadata;

namespace MediaDock.Application.OscarAwards;

public sealed class OscarEnrichmentService
{
    private readonly IOscarEnrichmentRepository _repository;
    private readonly MetadataResolver _metadataResolver;
    private readonly TimeProvider _timeProvider;

    public OscarEnrichmentService(
        IOscarEnrichmentRepository repository,
        MetadataResolver metadataResolver,
        TimeProvider? timeProvider = null)
    {
        _repository = repository;
        _metadataResolver = metadataResolver;
        _timeProvider = timeProvider ?? TimeProvider.System;
    }

    public async Task<OscarEnrichmentSummary> RunAsync(
        int maximumFilms,
        CancellationToken cancellationToken = default)
    {
        if (maximumFilms <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maximumFilms));
        }

        var candidates = await _repository.GetEligibleCandidatesAsync(
            _timeProvider.GetUtcNow(),
            maximumFilms,
            cancellationToken);
        var attemptedFilms = 0;
        var enrichedFilms = 0;
        var notFoundFilms = 0;
        var temporaryErrors = 0;
        var cacheHits = 0;
        var httpAttempts = 0;
        var stoppedForQuota = false;

        foreach (var candidate in candidates)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var attemptedAt = _timeProvider.GetUtcNow();
            var resolution = await _metadataResolver.ResolveAsync(
                candidate.FilmTitle,
                candidate.FilmYear,
                "movie",
                attemptedAt,
                cancellationToken,
                OmdbRequestPurpose.OscarEnrichment);
            if (resolution.Status == MetadataLookupStatus.RequestBudgetExhausted)
            {
                httpAttempts += resolution.HttpAttempts;
                stoppedForQuota = true;
                break;
            }

            var attemptCount = candidate.AttemptCount + 1;
            var update = CreateUpdate(resolution, attemptCount, attemptedAt);

            await _repository.SaveOutcomeAsync(candidate.Id, update, cancellationToken);
            attemptedFilms++;
            cacheHits += resolution.CacheHit ? 1 : 0;
            httpAttempts += resolution.HttpAttempts;

            switch (update.Status)
            {
                case OscarEnrichmentStatuses.Enriched:
                    enrichedFilms++;
                    break;
                case OscarEnrichmentStatuses.NotFound:
                    notFoundFilms++;
                    break;
                default:
                    temporaryErrors++;
                    break;
            }

            if (resolution.Status == MetadataLookupStatus.QuotaExceeded)
            {
                stoppedForQuota = true;
                break;
            }
        }

        return new OscarEnrichmentSummary(
            candidates.Count,
            attemptedFilms,
            enrichedFilms,
            notFoundFilms,
            temporaryErrors,
            cacheHits,
            httpAttempts,
            stoppedForQuota);
    }

    private static OscarEnrichmentUpdate CreateUpdate(
        MetadataResolution resolution,
        int attemptCount,
        DateTimeOffset attemptedAt)
    {
        if (resolution.Status == MetadataLookupStatus.Found && resolution.Metadata is not null)
        {
            return new OscarEnrichmentUpdate(
                OscarEnrichmentStatuses.Enriched,
                attemptCount,
                attemptedAt,
                null,
                null,
                resolution.Metadata);
        }

        if (resolution.Status == MetadataLookupStatus.ConfirmedNotFound)
        {
            return new OscarEnrichmentUpdate(
                OscarEnrichmentStatuses.NotFound,
                attemptCount,
                attemptedAt,
                null,
                resolution.ErrorCode ?? "not_found",
                null);
        }

        var nextAttemptAt = resolution.Status == MetadataLookupStatus.QuotaExceeded
            ? NextUtcDay(attemptedAt)
            : attemptedAt.Add(GetRetryDelay(attemptCount));
        return new OscarEnrichmentUpdate(
            OscarEnrichmentStatuses.TemporaryError,
            attemptCount,
            attemptedAt,
            nextAttemptAt,
            resolution.ErrorCode ?? resolution.Status.ToString().ToLowerInvariant(),
            null);
    }

    private static TimeSpan GetRetryDelay(int attemptCount)
    {
        var exponent = Math.Clamp(attemptCount - 1, 0, 5);
        return TimeSpan.FromHours(Math.Min(24, Math.Pow(2, exponent)));
    }

    private static DateTimeOffset NextUtcDay(DateTimeOffset value) =>
        new(value.UtcDateTime.Date.AddDays(1), TimeSpan.Zero);
}