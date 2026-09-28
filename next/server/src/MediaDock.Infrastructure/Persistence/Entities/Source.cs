namespace MediaDock.Infrastructure.Persistence.Entities;

public sealed class Source
{
    public long Id { get; set; }
    public string StableKey { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string FeedType { get; set; } = string.Empty;
    public string Url { get; set; } = string.Empty;
    public bool IsEnabled { get; set; } = true;

    public ICollection<Occurrence> Occurrences { get; set; } = new List<Occurrence>();
    public ICollection<ParseLog> ParseLogs { get; set; } = new List<ParseLog>();
}