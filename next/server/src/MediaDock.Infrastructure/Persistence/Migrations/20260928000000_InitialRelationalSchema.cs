using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

namespace MediaDock.Infrastructure.Persistence.Migrations;

[DbContext(typeof(MediaDockDbContext))]
[Migration("20260928000000_InitialRelationalSchema")]
public partial class InitialRelationalSchema : Migration
{
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.CreateTable(
            name: "sources",
            columns: table => new
            {
                id = table.Column<long>(type: "bigint", nullable: false)
                    .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                stable_key = table.Column<string>(type: "text", nullable: false),
                name = table.Column<string>(type: "text", nullable: false),
                feed_type = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                url = table.Column<string>(type: "text", nullable: false),
                is_enabled = table.Column<bool>(type: "boolean", nullable: false, defaultValue: true)
            },
            constraints: table =>
            {
                table.PrimaryKey("pk_sources", entity => entity.id);
                table.UniqueConstraint("ak_sources_stable_key", entity => entity.stable_key);
                table.CheckConstraint("ck_sources_feed_type", "feed_type IN ('movie', 'series')");
            });

        migrationBuilder.CreateTable(
            name: "scan_runs",
            columns: table => new
            {
                id = table.Column<long>(type: "bigint", nullable: false)
                    .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                started_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                finished_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                status = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                trigger = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                feeds_processed = table.Column<int>(type: "integer", nullable: false),
                entries_seen = table.Column<int>(type: "integer", nullable: false),
                titles_created = table.Column<int>(type: "integer", nullable: false),
                occurrences_created = table.Column<int>(type: "integer", nullable: false),
                cache_hits = table.Column<int>(type: "integer", nullable: false),
                omdb_requests = table.Column<int>(type: "integer", nullable: false),
                ignored_entries = table.Column<int>(type: "integer", nullable: false),
                error_count = table.Column<int>(type: "integer", nullable: false),
                error_summary = table.Column<string[]>(type: "text[]", nullable: false, defaultValueSql: "ARRAY[]::text[]")
            },
            constraints: table =>
            {
                table.PrimaryKey("pk_scan_runs", entity => entity.id);
                table.CheckConstraint("ck_scan_runs_status", "status IN ('running', 'succeeded', 'partial', 'failed')");
                table.CheckConstraint("ck_scan_runs_trigger", "trigger IN ('schedule', 'manual', 'local')");
            });

        migrationBuilder.CreateTable(
            name: "settings",
            columns: table => new
            {
                id = table.Column<long>(type: "bigint", nullable: false)
                    .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                excluded_genres = table.Column<string[]>(type: "text[]", nullable: false, defaultValueSql: "ARRAY[]::text[]"),
                excluded_countries = table.Column<string[]>(type: "text[]", nullable: false, defaultValueSql: "ARRAY[]::text[]"),
                min_movie_rating = table.Column<decimal>(type: "numeric(3,1)", precision: 3, scale: 1, nullable: false),
                min_series_rating = table.Column<decimal>(type: "numeric(3,1)", precision: 3, scale: 1, nullable: false),
                min_imdb_votes = table.Column<long>(type: "bigint", nullable: false),
                updated_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
            },
            constraints: table =>
            {
                table.PrimaryKey("pk_settings", entity => entity.id);
                table.CheckConstraint("ck_settings_min_movie_rating", "min_movie_rating BETWEEN 0 AND 10");
                table.CheckConstraint("ck_settings_min_series_rating", "min_series_rating BETWEEN 0 AND 10");
                table.CheckConstraint("ck_settings_min_imdb_votes", "min_imdb_votes BETWEEN 0 AND 1000000000");
            });

        migrationBuilder.CreateTable(
            name: "titles",
            columns: table => new
            {
                id = table.Column<long>(type: "bigint", nullable: false)
                    .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                title = table.Column<string>(type: "text", nullable: false),
                normalized_title = table.Column<string>(type: "text", nullable: false),
                year = table.Column<int>(type: "integer", nullable: true),
                media_type = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                source_type = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: true),
                content_kind = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: true),
                broadcast_range_start_year = table.Column<int>(type: "integer", nullable: true),
                broadcast_range_end_year = table.Column<int>(type: "integer", nullable: true),
                broadcast_range_raw = table.Column<string>(type: "text", nullable: true),
                imdb_id = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: true),
                imdb_rating = table.Column<decimal>(type: "numeric(4,1)", precision: 4, scale: 1, nullable: true),
                imdb_votes = table.Column<long>(type: "bigint", nullable: true),
                metascore = table.Column<decimal>(type: "numeric(5,2)", precision: 5, scale: 2, nullable: true),
                genres = table.Column<string[]>(type: "text[]", nullable: false, defaultValueSql: "ARRAY[]::text[]"),
                countries = table.Column<string[]>(type: "text[]", nullable: false, defaultValueSql: "ARRAY[]::text[]"),
                director = table.Column<string>(type: "text", nullable: true),
                plot = table.Column<string>(type: "text", nullable: true),
                poster_url = table.Column<string>(type: "text", nullable: true),
                runtime = table.Column<string>(type: "text", nullable: true),
                awards = table.Column<string>(type: "text", nullable: true),
                box_office = table.Column<string>(type: "text", nullable: true),
                first_seen_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                last_seen_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                updated_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
            },
            constraints: table =>
            {
                table.PrimaryKey("pk_titles", entity => entity.id);
                table.CheckConstraint("ck_titles_media_type", "media_type IN ('movie', 'series', 'documentary', 'short')");
                table.CheckConstraint("ck_titles_source_type", "source_type IS NULL OR source_type IN ('movie', 'series')");
                table.CheckConstraint("ck_titles_content_kind", "content_kind IS NULL OR content_kind IN ('standard', 'documentary', 'short')");
            });

        migrationBuilder.CreateTable(
            name: "metadata_cache",
            columns: table => new
            {
                id = table.Column<long>(type: "bigint", nullable: false)
                    .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                cache_key = table.Column<string>(type: "text", nullable: false),
                lookup_title = table.Column<string>(type: "text", nullable: false),
                lookup_year = table.Column<int>(type: "integer", nullable: true),
                lookup_year_semantics = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                source_type = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                lookup_identity = table.Column<string>(type: "text", nullable: true),
                status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                payload_json = table.Column<string>(type: "jsonb", nullable: true),
                fetched_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                expires_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
            },
            constraints: table =>
            {
                table.PrimaryKey("pk_metadata_cache", entity => entity.id);
                table.UniqueConstraint("ak_metadata_cache_cache_key", entity => entity.cache_key);
                table.CheckConstraint("ck_metadata_cache_status", "status IN ('found', 'confirmed_not_found')");
                table.CheckConstraint("ck_metadata_cache_expiry", "expires_at > fetched_at");
            });

        migrationBuilder.CreateTable(
            name: "occurrences",
            columns: table => new
            {
                id = table.Column<long>(type: "bigint", nullable: false)
                    .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                title_id = table.Column<long>(type: "bigint", nullable: false),
                source_id = table.Column<long>(type: "bigint", nullable: false),
                source_item_key = table.Column<string>(type: "text", nullable: false),
                feed_entry_id = table.Column<string>(type: "text", nullable: true),
                torrent_url = table.Column<string>(type: "text", nullable: false),
                raw_title = table.Column<string>(type: "text", nullable: false),
                source_feed_name = table.Column<string>(type: "text", nullable: false),
                feed_type = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: true),
                source_published_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                observed_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                quality = table.Column<string>(type: "text", nullable: true),
                rip_type = table.Column<string>(type: "text", nullable: true),
                first_seen_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                last_seen_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
            },
            constraints: table =>
            {
                table.PrimaryKey("pk_occurrences", entity => entity.id);
                table.UniqueConstraint("ak_occurrences_source_id_source_item_key", entity => new { entity.source_id, entity.source_item_key });
                table.ForeignKey(
                    name: "fk_occurrences_sources_source_id",
                    column: entity => entity.source_id,
                    principalTable: "sources",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Restrict);
                table.ForeignKey(
                    name: "fk_occurrences_titles_title_id",
                    column: entity => entity.title_id,
                    principalTable: "titles",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Restrict);
            });

        migrationBuilder.CreateTable(
            name: "parse_logs",
            columns: table => new
            {
                id = table.Column<long>(type: "bigint", nullable: false)
                    .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                source_id = table.Column<long>(type: "bigint", nullable: true),
                source_item_key = table.Column<string>(type: "text", nullable: true),
                raw_title = table.Column<string>(type: "text", nullable: false),
                feed_name = table.Column<string>(type: "text", nullable: false),
                parsed_successfully = table.Column<bool>(type: "boolean", nullable: false),
                parsed_title = table.Column<string>(type: "text", nullable: true),
                parsed_year = table.Column<int>(type: "integer", nullable: true),
                omdb_status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                ignored = table.Column<bool>(type: "boolean", nullable: false),
                ignore_reason = table.Column<string>(type: "text", nullable: true),
                error_message = table.Column<string>(type: "text", nullable: true),
                decision = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                processed_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                retry_state = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                attempt_count = table.Column<int>(type: "integer", nullable: false),
                last_attempt_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                feed_type = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: true),
                source_published_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                observed_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                event_kind = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: true)
            },
            constraints: table =>
            {
                table.PrimaryKey("pk_parse_logs", entity => entity.id);
                table.ForeignKey(
                    name: "fk_parse_logs_sources_source_id",
                    column: entity => entity.source_id,
                    principalTable: "sources",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Restrict);
                table.CheckConstraint("ck_parse_logs_retry_state", "retry_state IN ('retryable', 'terminal', 'resolved')");
                table.CheckConstraint("ck_parse_logs_attempt_count", "attempt_count >= 0");
            });

        migrationBuilder.CreateIndex(
            name: "ix_titles_normalized_title",
            table: "titles",
            column: "normalized_title");
        migrationBuilder.CreateIndex(
            name: "ix_occurrences_title_id_last_seen_at",
            table: "occurrences",
            columns: new[] { "title_id", "last_seen_at" });
        migrationBuilder.CreateIndex(
            name: "ix_scan_runs_started_at",
            table: "scan_runs",
            column: "started_at");
        migrationBuilder.CreateIndex(
            name: "ix_parse_logs_processed_at",
            table: "parse_logs",
            column: "processed_at");
        migrationBuilder.CreateIndex(
            name: "IX_parse_logs_source_id",
            table: "parse_logs",
            column: "source_id");
        migrationBuilder.CreateIndex(
            name: "ix_metadata_cache_expires_at",
            table: "metadata_cache",
            column: "expires_at");
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.DropTable(name: "occurrences");
        migrationBuilder.DropTable(name: "parse_logs");
        migrationBuilder.DropTable(name: "metadata_cache");
        migrationBuilder.DropTable(name: "scan_runs");
        migrationBuilder.DropTable(name: "settings");
        migrationBuilder.DropTable(name: "sources");
        migrationBuilder.DropTable(name: "titles");
    }

    protected override void BuildTargetModel(ModelBuilder modelBuilder)
    {
        InitialRelationalSchemaModelBuilder.Build(modelBuilder);
    }
}