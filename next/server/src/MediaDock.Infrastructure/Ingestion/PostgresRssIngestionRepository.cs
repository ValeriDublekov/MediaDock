using MediaDock.Application.Ingestion;
using MediaDock.Application.Metadata;
using MediaDock.Application.Parsing;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;

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
            .OrderBy(value => value.Id)
            .FirstOrDefaultAsync(cancellationToken);
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
        await using var transaction = await dbContext.Database.BeginTransactionAsync(cancellationToken);
        try
        {
            var normalizedTitle = NormalizeTitle(metadata.Title);
            Title? title = null;
            if (!string.IsNullOrWhiteSpace(metadata.ImdbId))
            {
                title = await dbContext.Titles.FirstOrDefaultAsync(
                    entity => entity.ImdbId == metadata.ImdbId,
                    cancellationToken);
            }

            title ??= await dbContext.Titles
                .Where(entity => entity.NormalizedTitle == normalizedTitle
                    && entity.Year == metadata.Year
                    && entity.MediaType == metadata.MediaType)
                .OrderBy(entity => entity.Id)
                .FirstOrDefaultAsync(cancellationToken);

            var titleCreated = title is null;
            if (title is null)
            {
                title = new Title { FirstSeenAt = observedAt };
                dbContext.Titles.Add(title);
            }

            ApplyMetadata(title, metadata, normalizedTitle, observedAt);

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

    private static void ApplyMetadata(
        Title title,
        MetadataDetails metadata,
        string normalizedTitle,
        DateTimeOffset observedAt)
    {
        title.TitleText = metadata.Title;
        title.NormalizedTitle = normalizedTitle;
        title.Year = metadata.Year;
        title.MediaType = metadata.MediaType;
        title.SourceType = metadata.SourceType;
        title.ContentKind = metadata.ContentKind;
        title.BroadcastRangeStartYear = metadata.BroadcastRange?.StartYear;
        title.BroadcastRangeEndYear = metadata.BroadcastRange?.EndYear;
        title.BroadcastRangeRaw = metadata.BroadcastRange?.Raw;
        title.ImdbId = metadata.ImdbId;
        title.ImdbRating = metadata.ImdbRating;
        title.ImdbVotes = metadata.ImdbVotes;
        title.Metascore = metadata.Metascore;
        title.Genres = metadata.Genres;
        title.Countries = metadata.Countries;
        title.Director = metadata.Director;
        title.Plot = metadata.Plot;
        title.PosterUrl = metadata.PosterUrl;
        title.Runtime = metadata.Runtime;
        title.Awards = metadata.Awards;
        title.BoxOffice = metadata.BoxOffice;
        title.LastSeenAt = observedAt;
        title.UpdatedAt = observedAt;
    }

    private static string NormalizeTitle(string title) =>
        string.Join(' ', title.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)).ToLowerInvariant();
}