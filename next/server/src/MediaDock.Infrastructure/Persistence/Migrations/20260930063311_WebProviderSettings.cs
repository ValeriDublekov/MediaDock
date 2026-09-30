using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace MediaDock.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class WebProviderSettings : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "omdb_api_key",
                table: "settings",
                type: "character varying(512)",
                maxLength: 512,
                nullable: true);

            migrationBuilder.AddColumn<int>(
                name: "omdb_daily_request_limit",
                table: "settings",
                type: "integer",
                nullable: false,
                defaultValue: 0);

            migrationBuilder.AddColumn<int>(
                name: "oscar_enrichment_max_films_per_run",
                table: "settings",
                type: "integer",
                nullable: false,
                defaultValue: 0);

            migrationBuilder.AddColumn<int>(
                name: "oscar_enrichment_max_requests_per_day",
                table: "settings",
                type: "integer",
                nullable: false,
                defaultValue: 0);

            migrationBuilder.AddCheckConstraint(
                name: "ck_settings_omdb_daily_request_limit",
                table: "settings",
                sql: "omdb_daily_request_limit >= 0");

            migrationBuilder.AddCheckConstraint(
                name: "ck_settings_oscar_max_films_per_run",
                table: "settings",
                sql: "oscar_enrichment_max_films_per_run BETWEEN 0 AND 100000");

            migrationBuilder.AddCheckConstraint(
                name: "ck_settings_oscar_max_requests_per_day",
                table: "settings",
                sql: "oscar_enrichment_max_requests_per_day >= 0");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropCheckConstraint(
                name: "ck_settings_omdb_daily_request_limit",
                table: "settings");

            migrationBuilder.DropCheckConstraint(
                name: "ck_settings_oscar_max_films_per_run",
                table: "settings");

            migrationBuilder.DropCheckConstraint(
                name: "ck_settings_oscar_max_requests_per_day",
                table: "settings");

            migrationBuilder.DropColumn(
                name: "omdb_api_key",
                table: "settings");

            migrationBuilder.DropColumn(
                name: "omdb_daily_request_limit",
                table: "settings");

            migrationBuilder.DropColumn(
                name: "oscar_enrichment_max_films_per_run",
                table: "settings");

            migrationBuilder.DropColumn(
                name: "oscar_enrichment_max_requests_per_day",
                table: "settings");
        }
    }
}
