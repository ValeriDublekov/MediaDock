using MediaDock.Application.OscarAwards;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;

namespace MediaDock.Infrastructure.OscarAwards;

public sealed class PostgresOscarEnrichmentRunRepository(MediaDockDbContext dbContext)
    : IOscarEnrichmentRunRepository
{
    public async Task<long> StartAsync(
        string trigger,
        DateTimeOffset startedAt,
        CancellationToken cancellationToken = default)
    {
        var run = new OscarEnrichmentRun
        {
            StartedAt = startedAt,
            Status = OscarEnrichmentRunStatuses.Running,
            Trigger = trigger
        };
        dbContext.OscarEnrichmentRuns.Add(run);
        await dbContext.SaveChangesAsync(cancellationToken);
        return run.Id;
    }

    public async Task SaveProgressAsync(
        long runId,
        OscarEnrichmentRunProgress progress,
        CancellationToken cancellationToken = default)
    {
        var run = await GetRunAsync(runId, cancellationToken);
        ApplyProgress(run, progress);
        await dbContext.SaveChangesAsync(cancellationToken);
    }

    public async Task FinishAsync(
        long runId,
        string status,
        DateTimeOffset finishedAt,
        OscarEnrichmentRunProgress progress,
        string? errorCode,
        CancellationToken cancellationToken = default)
    {
        var run = await GetRunAsync(runId, cancellationToken);
        ApplyProgress(run, progress);
        run.Status = status;
        run.FinishedAt = finishedAt;
        run.ErrorCode = errorCode;
        await dbContext.SaveChangesAsync(cancellationToken);
    }

    private Task<OscarEnrichmentRun> GetRunAsync(long runId, CancellationToken cancellationToken) =>
        dbContext.OscarEnrichmentRuns.SingleAsync(run => run.Id == runId, cancellationToken);

    private static void ApplyProgress(OscarEnrichmentRun run, OscarEnrichmentRunProgress progress)
    {
        run.EligibleFilms = progress.EligibleFilms;
        run.ProcessedFilms = progress.ProcessedFilms;
        run.EnrichedFilms = progress.EnrichedFilms;
        run.NotFoundFilms = progress.NotFoundFilms;
        run.TemporaryErrors = progress.TemporaryErrors;
        run.CacheHits = progress.CacheHits;
        run.HttpAttempts = progress.HttpAttempts;
    }
}