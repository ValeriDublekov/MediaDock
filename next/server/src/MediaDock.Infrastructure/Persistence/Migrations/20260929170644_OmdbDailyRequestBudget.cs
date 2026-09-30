using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace MediaDock.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class OmdbDailyRequestBudget : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "omdb_daily_usage",
                columns: table => new
                {
                    utc_date = table.Column<DateOnly>(type: "date", nullable: false),
                    total_requests = table.Column<int>(type: "integer", nullable: false),
                    oscar_requests = table.Column<int>(type: "integer", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_omdb_daily_usage", x => x.utc_date);
                    table.CheckConstraint("ck_omdb_daily_usage_counts", "total_requests >= 0 AND oscar_requests >= 0 AND oscar_requests <= total_requests");
                });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "omdb_daily_usage");
        }
    }
}
