using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace MediaDock.Infrastructure.Persistence.Configurations;

internal sealed class OmdbDailyUsageConfiguration : IEntityTypeConfiguration<OmdbDailyUsage>
{
    public void Configure(EntityTypeBuilder<OmdbDailyUsage> builder)
    {
        builder.ToTable("omdb_daily_usage", table => table.HasCheckConstraint(
            "ck_omdb_daily_usage_counts",
            "total_requests >= 0 AND oscar_requests >= 0 AND oscar_requests <= total_requests"));
        builder.HasKey(entity => entity.UtcDate).HasName("pk_omdb_daily_usage");
        builder.Property(entity => entity.UtcDate).HasColumnName("utc_date").HasColumnType("date");
        builder.Property(entity => entity.TotalRequests).HasColumnName("total_requests").IsRequired();
        builder.Property(entity => entity.OscarRequests).HasColumnName("oscar_requests").IsRequired();
        builder.Property(entity => entity.ProviderQuotaExceeded)
            .HasColumnName("provider_quota_exceeded")
            .HasDefaultValue(false)
            .IsRequired();
    }
}