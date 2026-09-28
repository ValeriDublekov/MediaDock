namespace MediaDock.Infrastructure.Persistence.Entities;

public sealed class ScanRun
{
    public long Id { get; set; }
    public DateTimeOffset StartedAt { get; set; }
    public DateTimeOffset? FinishedAt { get; set; }
    public string Status { get; set; } = string.Empty;
    public string Trigger { get; set; } = string.Empty;
    public int FeedsProcessed { get; set; }
    public int EntriesSeen { get; set; }
    public int TitlesCreated { get; set; }
    public int OccurrencesCreated { get; set; }
    public int CacheHits { get; set; }
    public int OmdbRequests { get; set; }
    public int IgnoredEntries { get; set; }
    public int ErrorCount { get; set; }
    public string[] ErrorSummary { get; set; } = Array.Empty<string>();
}