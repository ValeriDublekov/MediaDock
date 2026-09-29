using MediaDock.Api.Catalog;
using MediaDock.Api.Common;
using MediaDock.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace MediaDock.Api.Operations;

internal interface IOperationalHistoryApiService
{
    Task<PageResponse<ParseLogResponse>> GetParseLogsAsync(
        ParseLogQuery query,
        CancellationToken cancellationToken);

    Task<PageResponse<ScanRunResponse>> GetScanRunsAsync(
        ScanRunQuery query,
        CancellationToken cancellationToken);
}

internal sealed class OperationalHistoryApiService(MediaDockDbContext dbContext) : IOperationalHistoryApiService
{
    public async Task<PageResponse<ParseLogResponse>> GetParseLogsAsync(
        ParseLogQuery query,
        CancellationToken cancellationToken)
    {
        var page = query.Page ?? 1;
        var pageSize = query.PageSize ?? 25;
        var logs = dbContext.ParseLogs.AsNoTracking();
        if (query.SourceId is { } sourceId)
        {
            logs = logs.Where(log => log.SourceId == sourceId);
        }

        if (query.ParsedSuccessfully is { } parsedSuccessfully)
        {
            logs = logs.Where(log => log.ParsedSuccessfully == parsedSuccessfully);
        }

        if (query.Ignored is { } ignored)
        {
            logs = logs.Where(log => log.Ignored == ignored);
        }

        if (query.RetryState is not null)
        {
            logs = logs.Where(log => log.RetryState == query.RetryState);
        }

        if (!string.IsNullOrWhiteSpace(query.Search))
        {
            var pattern = $"%{query.Search.Trim()}%";
            logs = logs.Where(log => EF.Functions.ILike(log.RawTitle, pattern)
                || EF.Functions.ILike(log.FeedName, pattern)
                || (log.ParsedTitle != null && EF.Functions.ILike(log.ParsedTitle, pattern)));
        }

        var totalCount = await logs.CountAsync(cancellationToken);
        var items = await logs
            .OrderByDescending(log => log.ProcessedAt)
            .ThenByDescending(log => log.Id)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .Select(log => new ParseLogResponse(
                log.Id,
                log.SourceId,
                log.Source == null ? null : log.Source.Name,
                log.SourceItemKey,
                log.RawTitle,
                log.FeedName,
                log.ParsedSuccessfully,
                log.ParsedTitle,
                log.ParsedYear,
                log.OmdbStatus,
                log.Ignored,
                log.IgnoreReason,
                log.ErrorMessage,
                log.Decision,
                log.ProcessedAt,
                log.RetryState,
                log.AttemptCount,
                log.LastAttemptAt,
                log.FeedType,
                log.SourcePublishedAt,
                log.ObservedAt,
                log.EventKind))
            .ToListAsync(cancellationToken);

        return CreatePage(items, page, pageSize, totalCount);
    }

    public async Task<PageResponse<ScanRunResponse>> GetScanRunsAsync(
        ScanRunQuery query,
        CancellationToken cancellationToken)
    {
        var page = query.Page ?? 1;
        var pageSize = query.PageSize ?? 25;
        var runs = dbContext.ScanRuns.AsNoTracking();
        if (query.Status is not null)
        {
            runs = runs.Where(run => run.Status == query.Status);
        }

        if (query.Trigger is not null)
        {
            runs = runs.Where(run => run.Trigger == query.Trigger);
        }

        var totalCount = await runs.CountAsync(cancellationToken);
        var items = await runs
            .OrderByDescending(run => run.StartedAt)
            .ThenByDescending(run => run.Id)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .Select(run => new ScanRunResponse(
                run.Id,
                run.StartedAt,
                run.FinishedAt,
                run.Status,
                run.Trigger,
                run.FeedsProcessed,
                run.EntriesSeen,
                run.TitlesCreated,
                run.OccurrencesCreated,
                run.CacheHits,
                run.OmdbRequests,
                run.IgnoredEntries,
                run.ErrorCount,
                run.ErrorSummary))
            .ToListAsync(cancellationToken);

        return CreatePage(items, page, pageSize, totalCount);
    }

    private static PageResponse<T> CreatePage<T>(IReadOnlyList<T> items, int page, int pageSize, int totalCount) =>
        new(items, page, pageSize, totalCount, totalCount == 0 ? 0 : (totalCount + pageSize - 1) / pageSize);
}