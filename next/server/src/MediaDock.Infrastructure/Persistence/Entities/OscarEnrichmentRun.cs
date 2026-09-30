namespace MediaDock.Infrastructure.Persistence.Entities;

public sealed class OscarEnrichmentRun
{
    public long Id { get; set; }
    public DateTimeOffset StartedAt { get; set; }
    public DateTimeOffset? FinishedAt { get; set; }
    public string Status { get; set; } = string.Empty;
    public string Trigger { get; set; } = string.Empty;
    public int EligibleFilms { get; set; }
    public int ProcessedFilms { get; set; }
    public int EnrichedFilms { get; set; }
    public int NotFoundFilms { get; set; }
    public int TemporaryErrors { get; set; }
    public int CacheHits { get; set; }
    public int HttpAttempts { get; set; }
    public string? ErrorCode { get; set; }
}