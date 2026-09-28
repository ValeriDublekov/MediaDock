namespace MediaDock.Infrastructure.Persistence.Entities;

public sealed class MetadataCacheEntry
{
    public long Id { get; set; }
    public string CacheKey { get; set; } = string.Empty;
    public string LookupTitle { get; set; } = string.Empty;
    public int? LookupYear { get; set; }
    public string LookupYearSemantics { get; set; } = string.Empty;
    public string SourceType { get; set; } = string.Empty;
    public string? LookupIdentity { get; set; }
    public string Status { get; set; } = string.Empty;
    public string? PayloadJson { get; set; }
    public DateTimeOffset FetchedAt { get; set; }
    public DateTimeOffset ExpiresAt { get; set; }
}