using MediaDock.Application.Metadata;

namespace MediaDock.Application.OscarAwards;

public sealed class OscarEnrichmentService
{
    private readonly IOscarEnrichmentRepository _repository;
    private readonly IOscarEnrichmentRunRepository _runRepository;
    private readonly MetadataResolver _metadataResolver;
    private readonly TimeProvider _timeProvider;

    public OscarEnrichmentService(
        IOscarEnrichmentRepository repository,
        MetadataResolver metadataResolver,
        IOscarEnrichmentRunRepository runRepository,
        TimeProvider? timeProvider = null)
    {
        _repository = repository;
        _metadataResolver = metadataResolver;
        _runRepository = runRepository;
        _timeProvider = timeProvider ?? TimeProvider.System;
    }

    public async Task<OscarEnrichmentRunResult> RunAsync(
        int maximumFilms,
        string trigger,
        CancellationToken cancellationToken = default)
    {
        if (maximumFilms <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maximumFilms));
        }

        var startedAt = _timeProvider.GetUtcNow();
        var runId = await _runRepository.StartAsync(trigger, startedAt, cancellationToken);
        var eligibleFilms = 0;
        var attemptedFilms = 0;
        var enrichedFilms = 0;
        var notFoundFilms = 0;
        var temporaryErrors = 0;
        var cacheHits = 0;
        var httpAttempts = 0;
        var stoppedForQuota = false;
        string? quotaStopErrorCode = null;

        OscarEnrichmentRunProgress CreateProgress() => new(
            eligibleFilms,
            attemptedFilms,
            enrichedFilms,
            notFoundFilms,
            temporaryErrors,
            cacheHits,
            httpAttempts);

        Task SaveProgressAsync(CancellationToken token) =>
            _runRepository.SaveProgressAsync(runId, CreateProgress(), token);

        try
        {
            var candidates = await _repository.GetEligibleCandidatesAsync(
                _timeProvider.GetUtcNow(),
                maximumFilms,
                cancellationToken);
            eligibleFilms = candidates.Count;
            await SaveProgressAsync(cancellationToken);

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
                httpAttempts += resolution.HttpAttempts;
                await SaveProgressAsync(cancellationToken);
                if (resolution.Status == MetadataLookupStatus.RequestBudgetExhausted)
                {
                    stoppedForQuota = true;
                    quotaStopErrorCode = "daily_request_budget_exhausted";
                    break;
                }

                var attemptCount = candidate.AttemptCount + 1;
                var update = CreateUpdate(resolution, candidate, attemptCount, attemptedAt);

                await _repository.SaveOutcomeAsync(candidate.Id, update, cancellationToken);
                attemptedFilms++;
                cacheHits += resolution.CacheHit ? 1 : 0;

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

                await SaveProgressAsync(cancellationToken);
                if (resolution.Status == MetadataLookupStatus.QuotaExceeded)
                {
                    stoppedForQuota = true;
                    quotaStopErrorCode = "provider_quota_exceeded";
                    break;
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            await _runRepository.FinishAsync(
                runId,
                OscarEnrichmentRunStatuses.Cancelled,
                _timeProvider.GetUtcNow(),
                CreateProgress(),
                "cancelled",
                CancellationToken.None);
            throw;
        }
        catch (Exception exception)
        {
            await _runRepository.FinishAsync(
                runId,
                OscarEnrichmentRunStatuses.Failed,
                _timeProvider.GetUtcNow(),
                CreateProgress(),
                exception.GetType().Name,
                CancellationToken.None);
            throw;
        }

        var summary = new OscarEnrichmentSummary(
            eligibleFilms,
            attemptedFilms,
            enrichedFilms,
            notFoundFilms,
            temporaryErrors,
            cacheHits,
            httpAttempts,
            stoppedForQuota);
        var status = stoppedForQuota
            ? OscarEnrichmentRunStatuses.QuotaStopped
            : temporaryErrors > 0
                ? OscarEnrichmentRunStatuses.Partial
                : OscarEnrichmentRunStatuses.Succeeded;
        var finishedAt = _timeProvider.GetUtcNow();
        await _runRepository.FinishAsync(
            runId,
            status,
            finishedAt,
            CreateProgress(),
            quotaStopErrorCode,
            CancellationToken.None);

        return new OscarEnrichmentRunResult(runId, startedAt, finishedAt, status, summary);
    }

    private static OscarEnrichmentUpdate CreateUpdate(
        MetadataResolution resolution,
        OscarEnrichmentCandidate candidate,
        int attemptCount,
        DateTimeOffset attemptedAt)
    {
        if (resolution.Status == MetadataLookupStatus.Found && resolution.Metadata is not null)
        {
            var metadataImdbId = ImdbIdNormalizer.Normalize(resolution.Metadata.ImdbId);
            if (!ImdbIdNormalizer.IsCompatible(candidate.ImdbId, candidate.TitleImdbId)
                || !ImdbIdNormalizer.IsCompatible(candidate.ImdbId, metadataImdbId)
                || !ImdbIdNormalizer.IsCompatible(candidate.TitleImdbId, metadataImdbId))
            {
                return new OscarEnrichmentUpdate(
                    OscarEnrichmentStatuses.TemporaryError,
                    attemptCount,
                    attemptedAt,
                    attemptedAt.Add(GetRetryDelay(attemptCount)),
                    "imdb_id_mismatch",
                    null);
            }

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