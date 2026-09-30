using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable

namespace MediaDock.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class OscarEnrichmentRuns : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "oscar_enrichment_runs",
                columns: table => new
                {
                    id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    started_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    finished_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    status = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    trigger = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    eligible_films = table.Column<int>(type: "integer", nullable: false),
                    processed_films = table.Column<int>(type: "integer", nullable: false),
                    enriched_films = table.Column<int>(type: "integer", nullable: false),
                    not_found_films = table.Column<int>(type: "integer", nullable: false),
                    temporary_errors = table.Column<int>(type: "integer", nullable: false),
                    cache_hits = table.Column<int>(type: "integer", nullable: false),
                    http_attempts = table.Column<int>(type: "integer", nullable: false),
                    error_code = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_oscar_enrichment_runs", x => x.id);
                    table.CheckConstraint("ck_oscar_enrichment_runs_counts", "eligible_films >= 0 AND processed_films >= 0 AND enriched_films >= 0 AND not_found_films >= 0 AND temporary_errors >= 0 AND cache_hits >= 0 AND http_attempts >= 0");
                    table.CheckConstraint("ck_oscar_enrichment_runs_status", "status IN ('running', 'succeeded', 'partial', 'quota_stopped', 'failed', 'cancelled')");
                    table.CheckConstraint("ck_oscar_enrichment_runs_trigger", "trigger IN ('manual', 'schedule')");
                });

            migrationBuilder.CreateIndex(
                name: "ix_oscar_enrichment_runs_started_at",
                table: "oscar_enrichment_runs",
                column: "started_at");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "oscar_enrichment_runs");
        }
    }
}
