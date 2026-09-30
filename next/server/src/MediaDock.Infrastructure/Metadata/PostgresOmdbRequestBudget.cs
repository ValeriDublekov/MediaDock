using MediaDock.Application.Metadata;
using MediaDock.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace MediaDock.Infrastructure.Metadata;

public sealed class PostgresOmdbRequestBudget(MediaDockDbContext dbContext) : IOmdbRequestBudget
{
    public async Task<bool> TryReserveAsync(
        DateOnly utcDate,
        OmdbRequestPurpose requestPurpose,
        int dailyRequestLimit,
        int oscarDailyRequestLimit,
        CancellationToken cancellationToken = default)
    {
        if (requestPurpose is not (OmdbRequestPurpose.RssIngestion or OmdbRequestPurpose.OscarEnrichment))
        {
            throw new ArgumentOutOfRangeException(nameof(requestPurpose));
        }

        if (dailyRequestLimit <= 0 || oscarDailyRequestLimit < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(dailyRequestLimit));
        }

        var isOscarRequest = requestPurpose == OmdbRequestPurpose.OscarEnrichment;
        if (isOscarRequest && oscarDailyRequestLimit == 0)
        {
            return false;
        }

        var oscarIncrement = isOscarRequest ? 1 : 0;
        var affectedRows = await dbContext.Database.ExecuteSqlInterpolatedAsync(
            $"""
            INSERT INTO omdb_daily_usage (utc_date, total_requests, oscar_requests)
            VALUES ({utcDate}, 1, {oscarIncrement})
            ON CONFLICT (utc_date) DO UPDATE
            SET total_requests = omdb_daily_usage.total_requests + 1,
                oscar_requests = omdb_daily_usage.oscar_requests + EXCLUDED.oscar_requests
            WHERE omdb_daily_usage.total_requests < {dailyRequestLimit}
                            AND NOT omdb_daily_usage.provider_quota_exceeded
              AND ({!isOscarRequest} OR omdb_daily_usage.oscar_requests < {oscarDailyRequestLimit});
            """,
            cancellationToken);

        return affectedRows == 1;
    }

    public async Task MarkProviderQuotaExceededAsync(
        DateOnly utcDate,
        CancellationToken cancellationToken = default)
    {
        await dbContext.Database.ExecuteSqlInterpolatedAsync(
            $"UPDATE omdb_daily_usage SET provider_quota_exceeded = TRUE WHERE utc_date = {utcDate};",
            cancellationToken);
    }
}