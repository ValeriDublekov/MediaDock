namespace MediaDock.Infrastructure.Persistence.Entities;

public sealed class OmdbDailyUsage
{
    public DateOnly UtcDate { get; set; }
    public int TotalRequests { get; set; }
    public int OscarRequests { get; set; }
    public bool ProviderQuotaExceeded { get; set; }
}