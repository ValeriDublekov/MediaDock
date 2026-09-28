namespace MediaDock.Infrastructure.Persistence.Entities;

public sealed class ParseLog
{
    public long Id { get; set; }
    public long? SourceId { get; set; }
    public string? SourceItemKey { get; set; }
    public string RawTitle { get; set; } = string.Empty;
    public string FeedName { get; set; } = string.Empty;
    public bool ParsedSuccessfully { get; set; }
    public string? ParsedTitle { get; set; }
    public int? ParsedYear { get; set; }
    public string OmdbStatus { get; set; } = string.Empty;
    public bool Ignored { get; set; }
    public string? IgnoreReason { get; set; }
    public string? ErrorMessage { get; set; }
    public string? Decision { get; set; }
    public DateTimeOffset ProcessedAt { get; set; }
    public string RetryState { get; set; } = string.Empty;
    public int AttemptCount { get; set; }
    public DateTimeOffset? LastAttemptAt { get; set; }
    public string? FeedType { get; set; }
    public DateTimeOffset? SourcePublishedAt { get; set; }
    public DateTimeOffset? ObservedAt { get; set; }
    public string? EventKind { get; set; }

    public Source? Source { get; set; }
}