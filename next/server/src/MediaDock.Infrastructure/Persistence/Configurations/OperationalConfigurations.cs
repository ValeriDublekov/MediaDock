using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace MediaDock.Infrastructure.Persistence.Configurations;

internal sealed class ScanRunConfiguration : IEntityTypeConfiguration<ScanRun>
{
    public void Configure(EntityTypeBuilder<ScanRun> builder)
    {
        builder.ToTable("scan_runs", table =>
        {
            table.HasCheckConstraint("ck_scan_runs_status", "status IN ('running', 'succeeded', 'partial', 'failed')");
            table.HasCheckConstraint("ck_scan_runs_trigger", "trigger IN ('schedule', 'manual', 'local')");
            table.HasCheckConstraint(
                "ck_scan_runs_finish_time",
                "(status = 'running' AND finished_at IS NULL) OR (status <> 'running' AND finished_at IS NOT NULL)");
        });
        builder.HasKey(entity => entity.Id).HasName("pk_scan_runs");
        builder.Property(entity => entity.Id).UseIdentityByDefaultColumn().HasColumnName("id");
        builder.Property(entity => entity.StartedAt).HasColumnName("started_at");
        builder.Property(entity => entity.FinishedAt).HasColumnName("finished_at");
        builder.Property(entity => entity.Status).HasColumnName("status").HasMaxLength(16).IsRequired();
        builder.Property(entity => entity.Trigger).HasColumnName("trigger").HasMaxLength(16).IsRequired();
        builder.Property(entity => entity.FeedsProcessed).HasColumnName("feeds_processed");
        builder.Property(entity => entity.EntriesSeen).HasColumnName("entries_seen");
        builder.Property(entity => entity.TitlesCreated).HasColumnName("titles_created");
        builder.Property(entity => entity.OccurrencesCreated).HasColumnName("occurrences_created");
        builder.Property(entity => entity.CacheHits).HasColumnName("cache_hits");
        builder.Property(entity => entity.OmdbRequests).HasColumnName("omdb_requests");
        builder.Property(entity => entity.IgnoredEntries).HasColumnName("ignored_entries");
        builder.Property(entity => entity.ErrorCount).HasColumnName("error_count");
        builder.Property(entity => entity.ErrorSummary)
            .HasColumnName("error_summary")
            .HasColumnType("text[]")
            .HasDefaultValueSql("ARRAY[]::text[]");
        builder.HasIndex(entity => entity.StartedAt).HasDatabaseName("ix_scan_runs_started_at");
    }
}

internal sealed class ParseLogConfiguration : IEntityTypeConfiguration<ParseLog>
{
    public void Configure(EntityTypeBuilder<ParseLog> builder)
    {
        builder.ToTable("parse_logs", table =>
        {
            table.HasCheckConstraint("ck_parse_logs_retry_state", "retry_state IN ('retryable', 'terminal', 'resolved')");
            table.HasCheckConstraint("ck_parse_logs_attempt_count", "attempt_count >= 0");
        });
        builder.HasKey(entity => entity.Id).HasName("pk_parse_logs");
        builder.Property(entity => entity.Id).UseIdentityByDefaultColumn().HasColumnName("id");
        builder.Property(entity => entity.SourceId).HasColumnName("source_id");
        builder.Property(entity => entity.SourceItemKey).HasColumnName("source_item_key");
        builder.Property(entity => entity.RawTitle).HasColumnName("raw_title").IsRequired();
        builder.Property(entity => entity.FeedName).HasColumnName("feed_name").IsRequired();
        builder.Property(entity => entity.ParsedSuccessfully).HasColumnName("parsed_successfully");
        builder.Property(entity => entity.ParsedTitle).HasColumnName("parsed_title");
        builder.Property(entity => entity.ParsedYear).HasColumnName("parsed_year");
        builder.Property(entity => entity.OmdbStatus).HasColumnName("omdb_status").HasMaxLength(32).IsRequired();
        builder.Property(entity => entity.Ignored).HasColumnName("ignored");
        builder.Property(entity => entity.IgnoreReason).HasColumnName("ignore_reason");
        builder.Property(entity => entity.ErrorMessage).HasColumnName("error_message");
        builder.Property(entity => entity.Decision).HasColumnName("decision").HasMaxLength(64);
        builder.Property(entity => entity.ProcessedAt).HasColumnName("processed_at");
        builder.Property(entity => entity.RetryState).HasColumnName("retry_state").HasMaxLength(16).IsRequired();
        builder.Property(entity => entity.AttemptCount).HasColumnName("attempt_count");
        builder.Property(entity => entity.LastAttemptAt).HasColumnName("last_attempt_at");
        builder.Property(entity => entity.FeedType).HasColumnName("feed_type").HasMaxLength(16);
        builder.Property(entity => entity.SourcePublishedAt).HasColumnName("source_published_at");
        builder.Property(entity => entity.ObservedAt).HasColumnName("observed_at");
        builder.Property(entity => entity.EventKind).HasColumnName("event_kind").HasMaxLength(16);
        builder.HasOne(entity => entity.Source)
            .WithMany(source => source.ParseLogs)
            .HasForeignKey(entity => entity.SourceId)
            .OnDelete(DeleteBehavior.Restrict)
            .HasConstraintName("fk_parse_logs_sources_source_id");
        builder.HasIndex(entity => entity.SourceId).HasDatabaseName("IX_parse_logs_source_id");
        builder.HasIndex(entity => entity.ProcessedAt).HasDatabaseName("ix_parse_logs_processed_at");
    }
}