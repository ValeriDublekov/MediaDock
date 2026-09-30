using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace MediaDock.Infrastructure.Persistence.Configurations;

internal sealed class SettingsConfiguration : IEntityTypeConfiguration<AppSetting>
{
    public void Configure(EntityTypeBuilder<AppSetting> builder)
    {
        builder.ToTable("settings", table =>
        {
            table.HasCheckConstraint("ck_settings_singleton_id", "id = 1");
            table.HasCheckConstraint("ck_settings_min_movie_rating", "min_movie_rating BETWEEN 0 AND 10");
            table.HasCheckConstraint("ck_settings_min_series_rating", "min_series_rating BETWEEN 0 AND 10");
            table.HasCheckConstraint("ck_settings_min_imdb_votes", "min_imdb_votes BETWEEN 0 AND 1000000000");
            table.HasCheckConstraint("ck_settings_omdb_daily_request_limit", "omdb_daily_request_limit >= 0");
            table.HasCheckConstraint("ck_settings_oscar_max_films_per_run", "oscar_enrichment_max_films_per_run BETWEEN 0 AND 100000");
            table.HasCheckConstraint("ck_settings_oscar_max_requests_per_day", "oscar_enrichment_max_requests_per_day >= 0");
        });
        builder.HasKey(entity => entity.Id).HasName("pk_settings");
        builder.Property(entity => entity.Id).UseIdentityByDefaultColumn().HasColumnName("id");
        builder.Property(entity => entity.ExcludedGenres)
            .HasColumnName("excluded_genres")
            .HasColumnType("text[]")
            .HasDefaultValueSql("ARRAY[]::text[]");
        builder.Property(entity => entity.ExcludedCountries)
            .HasColumnName("excluded_countries")
            .HasColumnType("text[]")
            .HasDefaultValueSql("ARRAY[]::text[]");
        builder.Property(entity => entity.MinMovieRating).HasColumnName("min_movie_rating").HasPrecision(3, 1);
        builder.Property(entity => entity.MinSeriesRating).HasColumnName("min_series_rating").HasPrecision(3, 1);
        builder.Property(entity => entity.MinImdbVotes).HasColumnName("min_imdb_votes");
        builder.Property(entity => entity.OmdbApiKey).HasColumnName("omdb_api_key").HasMaxLength(512);
        builder.Property(entity => entity.OmdbDailyRequestLimit).HasColumnName("omdb_daily_request_limit");
        builder.Property(entity => entity.OscarEnrichmentMaxFilmsPerRun).HasColumnName("oscar_enrichment_max_films_per_run");
        builder.Property(entity => entity.OscarEnrichmentMaxRequestsPerDay).HasColumnName("oscar_enrichment_max_requests_per_day");
        builder.Property(entity => entity.UpdatedAt).HasColumnName("updated_at");
    }
}