using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace MediaDock.Infrastructure.Persistence.Configurations;

internal sealed class OscarFilmConfiguration : IEntityTypeConfiguration<OscarFilm>
{
    public void Configure(EntityTypeBuilder<OscarFilm> builder)
    {
        builder.ToTable("oscar_films", table =>
        {
            table.HasCheckConstraint(
                "ck_oscar_films_enrichment_status",
                "enrichment_status IN ('pending', 'enriched', 'not_found', 'temporary_error')");
            table.HasCheckConstraint(
                "ck_oscar_films_enrichment_attempt_count",
                "enrichment_attempt_count >= 0");
        });
        builder.HasKey(entity => entity.Id).HasName("pk_oscar_films");
        builder.Property(entity => entity.Id).UseIdentityByDefaultColumn().HasColumnName("id");
        builder.Property(entity => entity.TitleId).HasColumnName("title_id");
        builder.Property(entity => entity.StableKey).HasColumnName("stable_key").IsRequired();
        builder.Property(entity => entity.FilmTitle).HasColumnName("film_title").IsRequired();
        builder.Property(entity => entity.NormalizedTitle).HasColumnName("normalized_title").IsRequired();
        builder.Property(entity => entity.FilmYear).HasColumnName("film_year");
        builder.Property(entity => entity.ImdbId).HasColumnName("imdb_id").HasMaxLength(32);
        builder.Property(entity => entity.EnrichmentStatus)
            .HasColumnName("enrichment_status")
            .HasMaxLength(24)
            .HasDefaultValue("pending")
            .IsRequired();
        builder.Property(entity => entity.EnrichmentAttemptCount)
            .HasColumnName("enrichment_attempt_count")
            .HasDefaultValue(0);
        builder.Property(entity => entity.LastEnrichmentAttemptAt).HasColumnName("last_enrichment_attempt_at");
        builder.Property(entity => entity.NextEnrichmentAttemptAt).HasColumnName("next_enrichment_attempt_at");
        builder.Property(entity => entity.LastEnrichmentError).HasColumnName("last_enrichment_error");
        builder.Property(entity => entity.ImportedAt).HasColumnName("imported_at");
        builder.Property(entity => entity.UpdatedAt).HasColumnName("updated_at");
        builder.HasIndex(entity => entity.StableKey)
            .IsUnique()
            .HasDatabaseName("ux_oscar_films_stable_key");
        builder.HasIndex(entity => entity.FilmYear).HasDatabaseName("ix_oscar_films_film_year");
        builder.HasOne(entity => entity.Title)
            .WithMany()
            .HasForeignKey(entity => entity.TitleId)
            .OnDelete(DeleteBehavior.Restrict)
            .HasConstraintName("fk_oscar_films_titles_title_id");
    }
}

internal sealed class OscarNominationConfiguration : IEntityTypeConfiguration<OscarNomination>
{
    public void Configure(EntityTypeBuilder<OscarNomination> builder)
    {
        builder.ToTable("oscar_nominations");
        builder.HasKey(entity => entity.Id).HasName("pk_oscar_nominations");
        builder.Property(entity => entity.Id).UseIdentityByDefaultColumn().HasColumnName("id");
        builder.Property(entity => entity.OscarFilmId).HasColumnName("oscar_film_id");
        builder.Property(entity => entity.ImportKey).HasColumnName("import_key").IsRequired();
        builder.Property(entity => entity.Ceremony).HasColumnName("ceremony");
        builder.Property(entity => entity.Class).HasColumnName("class").IsRequired();
        builder.Property(entity => entity.CanonicalCategory).HasColumnName("canonical_category").IsRequired();
        builder.Property(entity => entity.Category).HasColumnName("category").IsRequired();
        builder.Property(entity => entity.Name).HasColumnName("name").IsRequired();
        builder.Property(entity => entity.Nominees).HasColumnName("nominees").IsRequired();
        builder.Property(entity => entity.NomineeIds).HasColumnName("nominee_ids").IsRequired();
        builder.Property(entity => entity.Detail).HasColumnName("detail").IsRequired();
        builder.Property(entity => entity.IsWinner).HasColumnName("is_winner");
        builder.Property(entity => entity.ImportedAt).HasColumnName("imported_at");
        builder.Property(entity => entity.UpdatedAt).HasColumnName("updated_at");
        builder.HasIndex(entity => entity.ImportKey)
            .IsUnique()
            .HasDatabaseName("ux_oscar_nominations_import_key");
        builder.HasIndex(entity => new { entity.CanonicalCategory, entity.Ceremony })
            .HasDatabaseName("ix_oscar_nominations_category_ceremony");
        builder.HasOne(entity => entity.OscarFilm)
            .WithMany(film => film.Nominations)
            .HasForeignKey(entity => entity.OscarFilmId)
            .OnDelete(DeleteBehavior.Restrict)
            .HasConstraintName("fk_oscar_nominations_films_oscar_film_id");
    }
}