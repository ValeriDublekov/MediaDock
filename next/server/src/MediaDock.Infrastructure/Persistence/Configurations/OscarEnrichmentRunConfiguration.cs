using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace MediaDock.Infrastructure.Persistence.Configurations;

internal sealed class OscarEnrichmentRunConfiguration : IEntityTypeConfiguration<OscarEnrichmentRun>
{
    public void Configure(EntityTypeBuilder<OscarEnrichmentRun> builder)
    {
        builder.ToTable("oscar_enrichment_runs", table =>
        {
            table.HasCheckConstraint(
                "ck_oscar_enrichment_runs_status",
                "status IN ('running', 'succeeded', 'partial', 'quota_stopped', 'failed', 'cancelled')");
            table.HasCheckConstraint(
                "ck_oscar_enrichment_runs_trigger",
                "trigger IN ('manual', 'schedule')");
            table.HasCheckConstraint(
                "ck_oscar_enrichment_runs_counts",
                "eligible_films >= 0 AND processed_films >= 0 AND enriched_films >= 0 "
                + "AND not_found_films >= 0 AND temporary_errors >= 0 AND cache_hits >= 0 AND http_attempts >= 0");
            table.HasCheckConstraint(
                "ck_oscar_enrichment_runs_finish_time",
                "(status = 'running' AND finished_at IS NULL) OR (status <> 'running' AND finished_at IS NOT NULL)");
        });
        builder.HasKey(entity => entity.Id).HasName("pk_oscar_enrichment_runs");
        builder.Property(entity => entity.Id).UseIdentityByDefaultColumn().HasColumnName("id");
        builder.Property(entity => entity.StartedAt).HasColumnName("started_at");
        builder.Property(entity => entity.FinishedAt).HasColumnName("finished_at");
        builder.Property(entity => entity.Status).HasColumnName("status").HasMaxLength(16).IsRequired();
        builder.Property(entity => entity.Trigger).HasColumnName("trigger").HasMaxLength(16).IsRequired();
        builder.Property(entity => entity.EligibleFilms).HasColumnName("eligible_films");
        builder.Property(entity => entity.ProcessedFilms).HasColumnName("processed_films");
        builder.Property(entity => entity.EnrichedFilms).HasColumnName("enriched_films");
        builder.Property(entity => entity.NotFoundFilms).HasColumnName("not_found_films");
        builder.Property(entity => entity.TemporaryErrors).HasColumnName("temporary_errors");
        builder.Property(entity => entity.CacheHits).HasColumnName("cache_hits");
        builder.Property(entity => entity.HttpAttempts).HasColumnName("http_attempts");
        builder.Property(entity => entity.ErrorCode).HasColumnName("error_code").HasMaxLength(64);
        builder.HasIndex(entity => entity.StartedAt).HasDatabaseName("ix_oscar_enrichment_runs_started_at");
    }
}