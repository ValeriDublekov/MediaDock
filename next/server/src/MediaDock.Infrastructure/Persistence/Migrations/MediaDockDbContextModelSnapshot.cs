using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Metadata;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

namespace MediaDock.Infrastructure.Persistence.Migrations;

[DbContext(typeof(MediaDockDbContext))]
public sealed class MediaDockDbContextModelSnapshot : ModelSnapshot
{
    protected override void BuildModel(ModelBuilder modelBuilder)
    {
        BuildSnapshot(modelBuilder);
    }

    internal static void BuildSnapshot(ModelBuilder modelBuilder)
    {
        modelBuilder
            .HasAnnotation("ProductVersion", "10.0.0")
            .HasAnnotation("Relational:MaxIdentifierLength", 63);

        modelBuilder.Entity<Title>(entity =>
        {
            entity.Property<long>("Id")
                .ValueGeneratedOnAdd()
                .HasColumnType("bigint")
                .HasColumnName("id")
                .HasAnnotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn);
            entity.Property<string>("TitleText").IsRequired().HasColumnType("text").HasColumnName("title");
            entity.Property<string>("NormalizedTitle").IsRequired().HasColumnType("text").HasColumnName("normalized_title");
            entity.Property<int?>("Year").HasColumnType("integer").HasColumnName("year");
            entity.Property<string>("MediaType").IsRequired().HasMaxLength(32).HasColumnType("character varying(32)").HasColumnName("media_type");
            entity.Property<string>("SourceType").HasMaxLength(16).HasColumnType("character varying(16)").HasColumnName("source_type");
            entity.Property<string>("ContentKind").HasMaxLength(16).HasColumnType("character varying(16)").HasColumnName("content_kind");
            entity.Property<int?>("BroadcastRangeStartYear").HasColumnType("integer").HasColumnName("broadcast_range_start_year");
            entity.Property<int?>("BroadcastRangeEndYear").HasColumnType("integer").HasColumnName("broadcast_range_end_year");
            entity.Property<string>("BroadcastRangeRaw").HasColumnType("text").HasColumnName("broadcast_range_raw");
            entity.Property<string>("ImdbId").HasMaxLength(32).HasColumnType("character varying(32)").HasColumnName("imdb_id");
            entity.Property<decimal?>("ImdbRating").HasPrecision(4, 1).HasColumnType("numeric(4,1)").HasColumnName("imdb_rating");
            entity.Property<long?>("ImdbVotes").HasColumnType("bigint").HasColumnName("imdb_votes");
            entity.Property<decimal?>("Metascore").HasPrecision(5, 2).HasColumnType("numeric(5,2)").HasColumnName("metascore");
            entity.Property<string[]>("Genres").IsRequired().HasColumnType("text[]").HasDefaultValueSql("ARRAY[]::text[]").HasColumnName("genres");
            entity.Property<string[]>("Countries").IsRequired().HasColumnType("text[]").HasDefaultValueSql("ARRAY[]::text[]").HasColumnName("countries");
            entity.Property<string>("Director").HasColumnType("text").HasColumnName("director");
            entity.Property<string>("Plot").HasColumnType("text").HasColumnName("plot");
            entity.Property<string>("PosterUrl").HasColumnType("text").HasColumnName("poster_url");
            entity.Property<string>("Runtime").HasColumnType("text").HasColumnName("runtime");
            entity.Property<string>("Awards").HasColumnType("text").HasColumnName("awards");
            entity.Property<string>("BoxOffice").HasColumnType("text").HasColumnName("box_office");
            entity.Property<DateTimeOffset>("FirstSeenAt").IsRequired().HasColumnType("timestamp with time zone").HasColumnName("first_seen_at");
            entity.Property<DateTimeOffset>("LastSeenAt").IsRequired().HasColumnType("timestamp with time zone").HasColumnName("last_seen_at");
            entity.Property<DateTimeOffset>("UpdatedAt").IsRequired().HasColumnType("timestamp with time zone").HasColumnName("updated_at");
            entity.HasKey("Id").HasName("pk_titles");
            entity.HasIndex("NormalizedTitle").HasDatabaseName("ix_titles_normalized_title");
            entity.ToTable("titles", (string)null, table =>
            {
                table.HasCheckConstraint("ck_titles_media_type", "media_type IN ('movie', 'series', 'documentary', 'short')");
                table.HasCheckConstraint("ck_titles_source_type", "source_type IS NULL OR source_type IN ('movie', 'series')");
                table.HasCheckConstraint("ck_titles_content_kind", "content_kind IS NULL OR content_kind IN ('standard', 'documentary', 'short')");
            });
        });

        modelBuilder.Entity<Source>(entity =>
        {
            entity.Property<long>("Id")
                .ValueGeneratedOnAdd()
                .HasColumnType("bigint")
                .HasColumnName("id")
                .HasAnnotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn);
            entity.Property<string>("StableKey").IsRequired().HasColumnType("text").HasColumnName("stable_key");
            entity.Property<string>("Name").IsRequired().HasColumnType("text").HasColumnName("name");
            entity.Property<string>("FeedType").IsRequired().HasMaxLength(16).HasColumnType("character varying(16)").HasColumnName("feed_type");
            entity.Property<string>("Url").IsRequired().HasColumnType("text").HasColumnName("url");
            entity.Property<bool>("IsEnabled").IsRequired().ValueGeneratedOnAdd().HasColumnType("boolean").HasDefaultValue(true).HasColumnName("is_enabled");
            entity.HasKey("Id").HasName("pk_sources");
            entity.HasAlternateKey("StableKey").HasName("ak_sources_stable_key");
            entity.ToTable("sources", (string)null, table =>
                table.HasCheckConstraint("ck_sources_feed_type", "feed_type IN ('movie', 'series')"));
        });

        modelBuilder.Entity<Occurrence>(entity =>
        {
            entity.Property<long>("Id")
                .ValueGeneratedOnAdd()
                .HasColumnType("bigint")
                .HasColumnName("id")
                .HasAnnotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn);
            entity.Property<long>("TitleId").IsRequired().HasColumnType("bigint").HasColumnName("title_id");
            entity.Property<long>("SourceId").IsRequired().HasColumnType("bigint").HasColumnName("source_id");
            entity.Property<string>("SourceItemKey").IsRequired().HasColumnType("text").HasColumnName("source_item_key");
            entity.Property<string>("FeedEntryId").HasColumnType("text").HasColumnName("feed_entry_id");
            entity.Property<string>("TorrentUrl").IsRequired().HasColumnType("text").HasColumnName("torrent_url");
            entity.Property<string>("RawTitle").IsRequired().HasColumnType("text").HasColumnName("raw_title");
            entity.Property<string>("SourceFeedName").IsRequired().HasColumnType("text").HasColumnName("source_feed_name");
            entity.Property<string>("FeedType").HasMaxLength(16).HasColumnType("character varying(16)").HasColumnName("feed_type");
            entity.Property<DateTimeOffset?>("SourcePublishedAt").HasColumnType("timestamp with time zone").HasColumnName("source_published_at");
            entity.Property<DateTimeOffset?>("ObservedAt").HasColumnType("timestamp with time zone").HasColumnName("observed_at");
            entity.Property<string>("Quality").HasColumnType("text").HasColumnName("quality");
            entity.Property<string>("RipType").HasColumnType("text").HasColumnName("rip_type");
            entity.Property<DateTimeOffset>("FirstSeenAt").IsRequired().HasColumnType("timestamp with time zone").HasColumnName("first_seen_at");
            entity.Property<DateTimeOffset>("LastSeenAt").IsRequired().HasColumnType("timestamp with time zone").HasColumnName("last_seen_at");
            entity.HasKey("Id").HasName("pk_occurrences");
            entity.HasAlternateKey("SourceId", "SourceItemKey").HasName("ak_occurrences_source_id_source_item_key");
            entity.HasIndex("TitleId", "LastSeenAt").HasDatabaseName("ix_occurrences_title_id_last_seen_at");
            entity.ToTable("occurrences");
            entity.HasOne("MediaDock.Infrastructure.Persistence.Entities.Source", "Source")
                .WithMany("Occurrences")
                .HasForeignKey("SourceId")
                .OnDelete(DeleteBehavior.Restrict)
                .IsRequired()
                .HasConstraintName("fk_occurrences_sources_source_id");
            entity.HasOne("MediaDock.Infrastructure.Persistence.Entities.Title", "Title")
                .WithMany("Occurrences")
                .HasForeignKey("TitleId")
                .OnDelete(DeleteBehavior.Restrict)
                .IsRequired()
                .HasConstraintName("fk_occurrences_titles_title_id");
            entity.Navigation("Source");
            entity.Navigation("Title");
        });

        modelBuilder.Entity<ScanRun>(entity =>
        {
            entity.Property<long>("Id")
                .ValueGeneratedOnAdd()
                .HasColumnType("bigint")
                .HasColumnName("id")
                .HasAnnotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn);
            entity.Property<DateTimeOffset>("StartedAt").IsRequired().HasColumnType("timestamp with time zone").HasColumnName("started_at");
            entity.Property<DateTimeOffset?>("FinishedAt").HasColumnType("timestamp with time zone").HasColumnName("finished_at");
            entity.Property<string>("Status").IsRequired().HasMaxLength(16).HasColumnType("character varying(16)").HasColumnName("status");
            entity.Property<string>("Trigger").IsRequired().HasMaxLength(16).HasColumnType("character varying(16)").HasColumnName("trigger");
            entity.Property<int>("FeedsProcessed").IsRequired().HasColumnType("integer").HasColumnName("feeds_processed");
            entity.Property<int>("EntriesSeen").IsRequired().HasColumnType("integer").HasColumnName("entries_seen");
            entity.Property<int>("TitlesCreated").IsRequired().HasColumnType("integer").HasColumnName("titles_created");
            entity.Property<int>("OccurrencesCreated").IsRequired().HasColumnType("integer").HasColumnName("occurrences_created");
            entity.Property<int>("CacheHits").IsRequired().HasColumnType("integer").HasColumnName("cache_hits");
            entity.Property<int>("OmdbRequests").IsRequired().HasColumnType("integer").HasColumnName("omdb_requests");
            entity.Property<int>("IgnoredEntries").IsRequired().HasColumnType("integer").HasColumnName("ignored_entries");
            entity.Property<int>("ErrorCount").IsRequired().HasColumnType("integer").HasColumnName("error_count");
            entity.Property<string[]>("ErrorSummary").IsRequired().HasColumnType("text[]").HasDefaultValueSql("ARRAY[]::text[]").HasColumnName("error_summary");
            entity.HasKey("Id").HasName("pk_scan_runs");
            entity.HasIndex("StartedAt").HasDatabaseName("ix_scan_runs_started_at");
            entity.ToTable("scan_runs", (string)null, table =>
            {
                table.HasCheckConstraint("ck_scan_runs_status", "status IN ('running', 'succeeded', 'partial', 'failed')");
                table.HasCheckConstraint("ck_scan_runs_trigger", "trigger IN ('schedule', 'manual', 'local')");
            });
        });

        modelBuilder.Entity<ParseLog>(entity =>
        {
            entity.Property<long>("Id")
                .ValueGeneratedOnAdd()
                .HasColumnType("bigint")
                .HasColumnName("id")
                .HasAnnotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn);
            entity.Property<long?>("SourceId").HasColumnType("bigint").HasColumnName("source_id");
            entity.Property<string>("SourceItemKey").HasColumnType("text").HasColumnName("source_item_key");
            entity.Property<string>("RawTitle").IsRequired().HasColumnType("text").HasColumnName("raw_title");
            entity.Property<string>("FeedName").IsRequired().HasColumnType("text").HasColumnName("feed_name");
            entity.Property<bool>("ParsedSuccessfully").IsRequired().HasColumnType("boolean").HasColumnName("parsed_successfully");
            entity.Property<string>("ParsedTitle").HasColumnType("text").HasColumnName("parsed_title");
            entity.Property<int?>("ParsedYear").HasColumnType("integer").HasColumnName("parsed_year");
            entity.Property<string>("OmdbStatus").IsRequired().HasMaxLength(32).HasColumnType("character varying(32)").HasColumnName("omdb_status");
            entity.Property<bool>("Ignored").IsRequired().HasColumnType("boolean").HasColumnName("ignored");
            entity.Property<string>("IgnoreReason").HasColumnType("text").HasColumnName("ignore_reason");
            entity.Property<string>("ErrorMessage").HasColumnType("text").HasColumnName("error_message");
            entity.Property<string>("Decision").HasMaxLength(64).HasColumnType("character varying(64)").HasColumnName("decision");
            entity.Property<DateTimeOffset>("ProcessedAt").IsRequired().HasColumnType("timestamp with time zone").HasColumnName("processed_at");
            entity.Property<string>("RetryState").IsRequired().HasMaxLength(16).HasColumnType("character varying(16)").HasColumnName("retry_state");
            entity.Property<int>("AttemptCount").IsRequired().HasColumnType("integer").HasColumnName("attempt_count");
            entity.Property<DateTimeOffset?>("LastAttemptAt").HasColumnType("timestamp with time zone").HasColumnName("last_attempt_at");
            entity.Property<string>("FeedType").HasMaxLength(16).HasColumnType("character varying(16)").HasColumnName("feed_type");
            entity.Property<DateTimeOffset?>("SourcePublishedAt").HasColumnType("timestamp with time zone").HasColumnName("source_published_at");
            entity.Property<DateTimeOffset?>("ObservedAt").HasColumnType("timestamp with time zone").HasColumnName("observed_at");
            entity.Property<string>("EventKind").HasMaxLength(16).HasColumnType("character varying(16)").HasColumnName("event_kind");
            entity.HasKey("Id").HasName("pk_parse_logs");
            entity.HasIndex("SourceId").HasDatabaseName("IX_parse_logs_source_id");
            entity.HasIndex("ProcessedAt").HasDatabaseName("ix_parse_logs_processed_at");
            entity.ToTable("parse_logs", (string)null, table =>
            {
                table.HasCheckConstraint("ck_parse_logs_retry_state", "retry_state IN ('retryable', 'terminal', 'resolved')");
                table.HasCheckConstraint("ck_parse_logs_attempt_count", "attempt_count >= 0");
            });
            entity.HasOne("MediaDock.Infrastructure.Persistence.Entities.Source", "Source")
                .WithMany("ParseLogs")
                .HasForeignKey("SourceId")
                .OnDelete(DeleteBehavior.Restrict)
                .HasConstraintName("fk_parse_logs_sources_source_id");
            entity.Navigation("Source");
        });

        modelBuilder.Entity<Title>().Navigation("Occurrences");
        modelBuilder.Entity<Source>().Navigation("Occurrences");
        modelBuilder.Entity<Source>().Navigation("ParseLogs");

        modelBuilder.Entity<AppSetting>(entity =>
        {
            entity.Property<long>("Id")
                .ValueGeneratedOnAdd()
                .HasColumnType("bigint")
                .HasColumnName("id")
                .HasAnnotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn);
            entity.Property<string[]>("ExcludedGenres").IsRequired().HasColumnType("text[]").HasDefaultValueSql("ARRAY[]::text[]").HasColumnName("excluded_genres");
            entity.Property<string[]>("ExcludedCountries").IsRequired().HasColumnType("text[]").HasDefaultValueSql("ARRAY[]::text[]").HasColumnName("excluded_countries");
            entity.Property<decimal>("MinMovieRating").IsRequired().HasPrecision(3, 1).HasColumnType("numeric(3,1)").HasColumnName("min_movie_rating");
            entity.Property<decimal>("MinSeriesRating").IsRequired().HasPrecision(3, 1).HasColumnType("numeric(3,1)").HasColumnName("min_series_rating");
            entity.Property<long>("MinImdbVotes").IsRequired().HasColumnType("bigint").HasColumnName("min_imdb_votes");
            entity.Property<DateTimeOffset>("UpdatedAt").IsRequired().HasColumnType("timestamp with time zone").HasColumnName("updated_at");
            entity.HasKey("Id").HasName("pk_settings");
            entity.ToTable("settings", (string)null, table =>
            {
                table.HasCheckConstraint("ck_settings_min_movie_rating", "min_movie_rating BETWEEN 0 AND 10");
                table.HasCheckConstraint("ck_settings_min_series_rating", "min_series_rating BETWEEN 0 AND 10");
                table.HasCheckConstraint("ck_settings_min_imdb_votes", "min_imdb_votes BETWEEN 0 AND 1000000000");
            });
        });

        modelBuilder.Entity<MetadataCacheEntry>(entity =>
        {
            entity.Property<long>("Id")
                .ValueGeneratedOnAdd()
                .HasColumnType("bigint")
                .HasColumnName("id")
                .HasAnnotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn);
            entity.Property<string>("CacheKey").IsRequired().HasColumnType("text").HasColumnName("cache_key");
            entity.Property<string>("LookupTitle").IsRequired().HasColumnType("text").HasColumnName("lookup_title");
            entity.Property<int?>("LookupYear").HasColumnType("integer").HasColumnName("lookup_year");
            entity.Property<string>("LookupYearSemantics").IsRequired().HasMaxLength(32).HasColumnType("character varying(32)").HasColumnName("lookup_year_semantics");
            entity.Property<string>("SourceType").IsRequired().HasMaxLength(16).HasColumnType("character varying(16)").HasColumnName("source_type");
            entity.Property<string>("LookupIdentity").HasColumnType("text").HasColumnName("lookup_identity");
            entity.Property<string>("Status").IsRequired().HasMaxLength(32).HasColumnType("character varying(32)").HasColumnName("status");
            entity.Property<string>("PayloadJson").HasColumnType("jsonb").HasColumnName("payload_json");
            entity.Property<DateTimeOffset>("FetchedAt").IsRequired().HasColumnType("timestamp with time zone").HasColumnName("fetched_at");
            entity.Property<DateTimeOffset>("ExpiresAt").IsRequired().HasColumnType("timestamp with time zone").HasColumnName("expires_at");
            entity.HasKey("Id").HasName("pk_metadata_cache");
            entity.HasAlternateKey("CacheKey").HasName("ak_metadata_cache_cache_key");
            entity.HasIndex("ExpiresAt").HasDatabaseName("ix_metadata_cache_expires_at");
            entity.ToTable("metadata_cache", (string)null, table =>
            {
                table.HasCheckConstraint("ck_metadata_cache_status", "status IN ('found', 'confirmed_not_found')");
                table.HasCheckConstraint("ck_metadata_cache_expiry", "expires_at > fetched_at");
            });
        });
    }
}