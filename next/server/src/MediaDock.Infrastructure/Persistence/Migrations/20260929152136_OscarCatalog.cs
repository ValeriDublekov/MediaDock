using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable

namespace MediaDock.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class OscarCatalog : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "oscar_films",
                columns: table => new
                {
                    id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    title_id = table.Column<long>(type: "bigint", nullable: false),
                    stable_key = table.Column<string>(type: "text", nullable: false),
                    film_title = table.Column<string>(type: "text", nullable: false),
                    normalized_title = table.Column<string>(type: "text", nullable: false),
                    film_year = table.Column<int>(type: "integer", nullable: false),
                    imdb_id = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: true),
                    enrichment_status = table.Column<string>(type: "character varying(24)", maxLength: 24, nullable: false, defaultValue: "pending"),
                    enrichment_attempt_count = table.Column<int>(type: "integer", nullable: false, defaultValue: 0),
                    last_enrichment_attempt_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    next_enrichment_attempt_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    last_enrichment_error = table.Column<string>(type: "text", nullable: true),
                    imported_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    updated_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_oscar_films", x => x.id);
                    table.ForeignKey(
                        name: "fk_oscar_films_titles_title_id",
                        column: x => x.title_id,
                        principalTable: "titles",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "oscar_nominations",
                columns: table => new
                {
                    id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    oscar_film_id = table.Column<long>(type: "bigint", nullable: false),
                    import_key = table.Column<string>(type: "text", nullable: false),
                    ceremony = table.Column<int>(type: "integer", nullable: false),
                    @class = table.Column<string>(name: "class", type: "text", nullable: false),
                    canonical_category = table.Column<string>(type: "text", nullable: false),
                    category = table.Column<string>(type: "text", nullable: false),
                    name = table.Column<string>(type: "text", nullable: false),
                    nominees = table.Column<string>(type: "text", nullable: false),
                    nominee_ids = table.Column<string>(type: "text", nullable: false),
                    detail = table.Column<string>(type: "text", nullable: false),
                    is_winner = table.Column<bool>(type: "boolean", nullable: false),
                    imported_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    updated_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_oscar_nominations", x => x.id);
                    table.ForeignKey(
                        name: "fk_oscar_nominations_films_oscar_film_id",
                        column: x => x.oscar_film_id,
                        principalTable: "oscar_films",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateIndex(
                name: "ix_oscar_films_film_year",
                table: "oscar_films",
                column: "film_year");

            migrationBuilder.CreateIndex(
                name: "IX_oscar_films_title_id",
                table: "oscar_films",
                column: "title_id");

            migrationBuilder.CreateIndex(
                name: "ux_oscar_films_stable_key",
                table: "oscar_films",
                column: "stable_key",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_oscar_nominations_category_ceremony",
                table: "oscar_nominations",
                columns: new[] { "canonical_category", "ceremony" });

            migrationBuilder.CreateIndex(
                name: "IX_oscar_nominations_oscar_film_id",
                table: "oscar_nominations",
                column: "oscar_film_id");

            migrationBuilder.CreateIndex(
                name: "ux_oscar_nominations_import_key",
                table: "oscar_nominations",
                column: "import_key",
                unique: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "oscar_nominations");

            migrationBuilder.DropTable(
                name: "oscar_films");
        }
    }
}
