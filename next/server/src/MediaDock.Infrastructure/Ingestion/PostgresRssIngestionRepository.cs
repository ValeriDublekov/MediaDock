using MediaDock.Application.Ingestion;
using MediaDock.Application.Metadata;
using MediaDock.Application.Parsing;
using MediaDock.Infrastructure.Metadata;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace MediaDock.Infrastructure.Ingestion;

public sealed class PostgresRssIngestionRepository(MediaDockDbContext dbContext) : IRssIngestionRepository
{
    public async Task<IReadOnlyList<IngestionSource>> GetEnabledSourcesAsync(
        CancellationToken cancellationToken = default) =>
        await dbContext.Sources
            .AsNoTracking()
            .Where(source => source.IsEnabled)
            .OrderBy(source => source.StableKey)
            .Select(source => new IngestionSource(
                source.Id,
                source.StableKey,
                source.Name,
                source.FeedType,
                source.Url))
            .ToListAsync(cancellationToken);

    public async Task<IngestionMatchSettings> GetMatchSettingsAsync(
        CancellationToken cancellationToken = default)
    {
        var setting = await dbContext.Settings.AsNoTracking()
            .SingleOrDefaultAsync(value => value.Id == 1, cancellationToken);
        return setting is null
            ? new IngestionMatchSettings([], [])
            : new IngestionMatchSettings(setting.ExcludedCountries, setting.ExcludedGenres);
    }

    public async Task<long> StartRunAsync(
        string trigger,
        DateTimeOffset startedAt,
        CancellationToken cancellationToken = default)
    {
        var run = new ScanRun
        {
            StartedAt = startedAt,
            Status = "running",
            Trigger = trigger
        };
        dbContext.ScanRuns.Add(run);
        await dbContext.SaveChangesAsync(cancellationToken);
        return run.Id;
    }

    public async Task<IngestionUpsertResult> UpsertCatalogItemAsync(
        IngestionSource source,
        IngestionFeedItem feedItem,
        string sourceItemKey,
        ParsedRutrackerTitle parsed,
        MetadataDetails metadata,
        DateTimeOffset observedAt,
        CancellationToken cancellationToken = default)
    {
        try
        {
            return await UpsertCatalogItemOnceAsync(
                source, feedItem, sourceItemKey, parsed, metadata, observedAt, cancellationToken);
        }
        catch (DbUpdateException exception) when (IsImdbIdentityUniqueViolation(exception))
        {
            dbContext.ChangeTracker.Clear();
            return await UpsertCatalogItemOnceAsync(
                source, feedItem, sourceItemKey, parsed, metadata, observedAt, cancellationToken);
        }
    }

    private async Task<IngestionUpsertResult> UpsertCatalogItemOnceAsync(
        IngestionSource source,
        IngestionFeedItem feedItem,
        string sourceItemKey,
        ParsedRutrackerTitle parsed,
        MetadataDetails metadata,
        DateTimeOffset observedAt,
        CancellationToken cancellationToken)
    {
        await using var transaction = await dbContext.Database.BeginTransactionAsync(cancellationToken);
        try
        {
                var normalizedTitle = TitleMetadataMapper.NormalizeTitle(metadata.Title);
                var imdbId = ImdbIdNormalizer.Normalize(metadata.ImdbId);
            Title? title = null;
                if (imdbId is not null)
            {
                title = await dbContext.Titles.FirstOrDefaultAsync(
                    entity => entity.ImdbId == imdbId,
                    cancellationToken);
            }

            title ??= await dbContext.Titles
                .Where(entity => entity.NormalizedTitle == normalizedTitle
                    && entity.Year == metadata.Year
                    && entity.MediaType == metadata.MediaType
                    && (imdbId == null || entity.ImdbId == null || entity.ImdbId == imdbId))
                .OrderBy(entity => entity.Id)
                .FirstOrDefaultAsync(cancellationToken);

            var titleCreated = title is null;
            if (title is null)
            {
                title = new Title { FirstSeenAt = observedAt };
                dbContext.Titles.Add(title);
            }

            TitleMetadataMapper.Apply(title, metadata, observedAt);

            var occurrence = await dbContext.Occurrences.FirstOrDefaultAsync(
                entity => entity.SourceId == source.Id && entity.SourceItemKey == sourceItemKey,
                cancellationToken);
            var occurrenceCreated = occurrence is null;
            if (occurrence is null)
            {
                occurrence = new Occurrence
                {
                    SourceId = source.Id,
                    SourceItemKey = sourceItemKey,
                    FirstSeenAt = observedAt
                };
                dbContext.Occurrences.Add(occurrence);
            }

            occurrence.Title = title;
            occurrence.FeedEntryId = feedItem.FeedEntryId;
            occurrence.TorrentUrl = feedItem.TorrentUrl!;
            occurrence.RawTitle = feedItem.Title!;
            occurrence.SourceFeedName = source.Name;
            occurrence.FeedType = source.FeedType;
            occurrence.SourcePublishedAt = feedItem.PublishedAt;
            occurrence.ObservedAt = observedAt;
            occurrence.LastSeenAt = observedAt;

            await dbContext.SaveChangesAsync(cancellationToken);
            await transaction.CommitAsync(cancellationToken);
            return new IngestionUpsertResult(titleCreated, occurrenceCreated);
        }
        catch
        {
            await transaction.RollbackAsync(CancellationToken.None);
            dbContext.ChangeTracker.Clear();
            throw;
        }
    }

    public async Task AddParseLogsAsync(
        IReadOnlyCollection<IngestionParseLog> logs,
        CancellationToken cancellationToken = default)
    {
        if (logs.Count == 0)
        {
            return;
        }

        dbContext.ParseLogs.AddRange(logs.Select(log => new ParseLog
        {
            SourceId = log.SourceId,
            SourceItemKey = log.SourceItemKey,
            RawTitle = log.RawTitle,
            FeedName = log.FeedName,
            ParsedSuccessfully = log.ParsedSuccessfully,
            ParsedTitle = log.ParsedTitle,
            ParsedYear = log.ParsedYear,
            OmdbStatus = log.OmdbStatus,
            Ignored = log.Ignored,
            IgnoreReason = log.IgnoreReason,
            ErrorMessage = log.ErrorMessage,
            Decision = log.Decision,
            ProcessedAt = log.ProcessedAt,
            RetryState = log.RetryState,
            AttemptCount = log.AttemptCount,
            LastAttemptAt = log.LastAttemptAt,
            FeedType = log.FeedType,
            SourcePublishedAt = log.SourcePublishedAt,
            ObservedAt = log.ObservedAt,
            EventKind = log.EventKind
        }));
        await dbContext.SaveChangesAsync(cancellationToken);
    }

    public async Task CompleteRunAsync(
        long runId,
        IngestionRunSummary summary,
        CancellationToken cancellationToken = default)
    {
        var run = await dbContext.ScanRuns.SingleAsync(entity => entity.Id == runId, cancellationToken);
        run.Status = summary.Status;
        run.FinishedAt = summary.FinishedAt;
        run.FeedsProcessed = summary.FeedsProcessed;
        run.EntriesSeen = summary.EntriesSeen;
        run.TitlesCreated = summary.TitlesCreated;
        run.OccurrencesCreated = summary.OccurrencesCreated;
        run.CacheHits = summary.CacheHits;
        run.OmdbRequests = summary.OmdbRequests;
        run.IgnoredEntries = summary.IgnoredEntries;
        run.ErrorCount = summary.ErrorCount;
        run.ErrorSummary = summary.ErrorSummary.ToArray();
        await dbContext.SaveChangesAsync(cancellationToken);
    }

    private static bool IsImdbIdentityUniqueViolation(DbUpdateException exception) =>
        exception.InnerException is PostgresException
        {
            SqlState: PostgresErrorCodes.UniqueViolation,
            ConstraintName: "ux_titles_imdb_id"
        };

}