using MediaDock.Application.Metadata;
using MediaDock.Application.Parsing;

namespace MediaDock.Application.Ingestion;

public sealed record IngestionSource(long Id, string StableKey, string Name, string FeedType, string Url);

public sealed record IngestionMatchSettings(string[] ExcludedCountries, string[] ExcludedGenres);

public sealed record IngestionFeedItem(
    string? Title,
    string? FeedEntryId,
    string? TorrentUrl,
    DateTimeOffset? PublishedAt);

public sealed record IngestionParseLog(
    long? SourceId,
    string? SourceItemKey,
    string RawTitle,
    string FeedName,
    bool ParsedSuccessfully,
    string? ParsedTitle,
    int? ParsedYear,
    string OmdbStatus,
    bool Ignored,
    string? IgnoreReason,
    string? ErrorMessage,
    string? Decision,
    DateTimeOffset ProcessedAt,
    string RetryState,
    int AttemptCount,
    DateTimeOffset? LastAttemptAt,
    string? FeedType,
    DateTimeOffset? SourcePublishedAt,
    DateTimeOffset? ObservedAt,
    string? EventKind = "ingestion");

public sealed record IngestionUpsertResult(bool TitleCreated, bool OccurrenceCreated);

public sealed record IngestionRunSummary(
    string Status,
    int FeedsProcessed,
    int EntriesSeen,
    int TitlesCreated,
    int OccurrencesCreated,
    int CacheHits,
    int OmdbRequests,
    int IgnoredEntries,
    int ErrorCount,
    IReadOnlyList<string> ErrorSummary,
    DateTimeOffset FinishedAt);

public sealed record IngestionRunResult(long RunId, IngestionRunSummary Summary);

public interface IRssFeedTransport
{
    Task<byte[]> FetchAsync(string url, CancellationToken cancellationToken = default);
}

public interface IRssIngestionRepository
{
    Task<IReadOnlyList<IngestionSource>> GetEnabledSourcesAsync(CancellationToken cancellationToken = default);

    Task<IngestionMatchSettings> GetMatchSettingsAsync(CancellationToken cancellationToken = default);

    Task<long> StartRunAsync(
        string trigger,
        DateTimeOffset startedAt,
        CancellationToken cancellationToken = default);

    Task<IngestionUpsertResult> UpsertCatalogItemAsync(
        IngestionSource source,
        IngestionFeedItem feedItem,
        string sourceItemKey,
        ParsedRutrackerTitle parsed,
        MetadataDetails metadata,
        DateTimeOffset observedAt,
        CancellationToken cancellationToken = default);

    Task AddParseLogsAsync(
        IReadOnlyCollection<IngestionParseLog> logs,
        CancellationToken cancellationToken = default);

    Task CompleteRunAsync(
        long runId,
        IngestionRunSummary summary,
        CancellationToken cancellationToken = default);
}

public static class SourceItemIdentity
{
    public static string From(string? feedEntryId, string? torrentUrl)
    {
        if (!string.IsNullOrWhiteSpace(feedEntryId))
        {
            return $"entry:{feedEntryId.Trim()}";
        }

        if (!string.IsNullOrWhiteSpace(torrentUrl))
        {
            return $"url:{torrentUrl.Trim()}";
        }

        throw new ArgumentException("A feed entry ID or torrent URL is required.", nameof(feedEntryId));
    }
}