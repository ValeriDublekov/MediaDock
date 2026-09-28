namespace MediaDock.Infrastructure.Persistence.Entities;

public sealed class Occurrence
{
    public long Id { get; set; }
    public long TitleId { get; set; }
    public long SourceId { get; set; }
    public string SourceItemKey { get; set; } = string.Empty;
    public string? FeedEntryId { get; set; }
    public string TorrentUrl { get; set; } = string.Empty;
    public string RawTitle { get; set; } = string.Empty;
    public string SourceFeedName { get; set; } = string.Empty;
    public string? FeedType { get; set; }
    public DateTimeOffset? SourcePublishedAt { get; set; }
    public DateTimeOffset? ObservedAt { get; set; }
    public string? Quality { get; set; }
    public string? RipType { get; set; }
    public DateTimeOffset FirstSeenAt { get; set; }
    public DateTimeOffset LastSeenAt { get; set; }

    public Title Title { get; set; } = null!;
    public Source Source { get; set; } = null!;
}