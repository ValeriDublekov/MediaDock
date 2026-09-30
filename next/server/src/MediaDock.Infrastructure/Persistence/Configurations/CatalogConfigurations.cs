using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace MediaDock.Infrastructure.Persistence.Configurations;

internal sealed class TitleConfiguration : IEntityTypeConfiguration<Title>
{
    public void Configure(EntityTypeBuilder<Title> builder)
    {
        builder.ToTable("titles", table =>
        {
            table.HasCheckConstraint("ck_titles_media_type", "media_type IN ('movie', 'series', 'documentary', 'short')");
            table.HasCheckConstraint("ck_titles_source_type", "source_type IS NULL OR source_type IN ('movie', 'series')");
            table.HasCheckConstraint("ck_titles_content_kind", "content_kind IS NULL OR content_kind IN ('standard', 'documentary', 'short')");
            table.HasCheckConstraint(
                "ck_titles_seen_range",
                "(first_seen_at IS NULL AND last_seen_at IS NULL) OR (first_seen_at IS NOT NULL AND last_seen_at IS NOT NULL AND first_seen_at <= last_seen_at)");
        });
        builder.HasKey(entity => entity.Id).HasName("pk_titles");
        builder.Property(entity => entity.Id).UseIdentityByDefaultColumn().HasColumnName("id");
        builder.Property(entity => entity.TitleText).HasColumnName("title").IsRequired();
        builder.Property(entity => entity.NormalizedTitle).HasColumnName("normalized_title").IsRequired();
        builder.Property(entity => entity.Year).HasColumnName("year");
        builder.Property(entity => entity.MediaType).HasColumnName("media_type").HasMaxLength(32).IsRequired();
        builder.Property(entity => entity.SourceType).HasColumnName("source_type").HasMaxLength(16);
        builder.Property(entity => entity.ContentKind).HasColumnName("content_kind").HasMaxLength(16);
        builder.Property(entity => entity.BroadcastRangeStartYear).HasColumnName("broadcast_range_start_year");
        builder.Property(entity => entity.BroadcastRangeEndYear).HasColumnName("broadcast_range_end_year");
        builder.Property(entity => entity.BroadcastRangeRaw).HasColumnName("broadcast_range_raw");
        builder.Property(entity => entity.ImdbId).HasColumnName("imdb_id").HasMaxLength(32);
        builder.Property(entity => entity.ImdbRating).HasColumnName("imdb_rating").HasPrecision(4, 1);
        builder.Property(entity => entity.ImdbVotes).HasColumnName("imdb_votes");
        builder.Property(entity => entity.Metascore).HasColumnName("metascore").HasPrecision(5, 2);
        builder.Property(entity => entity.Genres)
            .HasColumnName("genres")
            .HasColumnType("text[]")
            .HasDefaultValueSql("ARRAY[]::text[]");
        builder.Property(entity => entity.Countries)
            .HasColumnName("countries")
            .HasColumnType("text[]")
            .HasDefaultValueSql("ARRAY[]::text[]");
        builder.Property(entity => entity.Director).HasColumnName("director");
        builder.Property(entity => entity.Plot).HasColumnName("plot");
        builder.Property(entity => entity.PosterUrl).HasColumnName("poster_url");
        builder.Property(entity => entity.Runtime).HasColumnName("runtime");
        builder.Property(entity => entity.Awards).HasColumnName("awards");
        builder.Property(entity => entity.BoxOffice).HasColumnName("box_office");
        builder.Property(entity => entity.FirstSeenAt).HasColumnName("first_seen_at");
        builder.Property(entity => entity.LastSeenAt).HasColumnName("last_seen_at");
        builder.Property(entity => entity.UpdatedAt).HasColumnName("updated_at");
        builder.HasIndex(entity => entity.ImdbId)
            .IsUnique()
            .HasDatabaseName("ux_titles_imdb_id")
            .HasFilter("imdb_id IS NOT NULL AND btrim(imdb_id) <> ''");
        builder.HasIndex(entity => new { entity.NormalizedTitle, entity.Year, entity.MediaType })
            .HasDatabaseName("ix_titles_normalized_title_year_media_type");
    }
}

internal sealed class SourceConfiguration : IEntityTypeConfiguration<Source>
{
    public void Configure(EntityTypeBuilder<Source> builder)
    {
        builder.ToTable("sources", table =>
            table.HasCheckConstraint("ck_sources_feed_type", "feed_type IN ('movie', 'series')"));
        builder.HasKey(entity => entity.Id).HasName("pk_sources");
        builder.HasAlternateKey(entity => entity.StableKey).HasName("ak_sources_stable_key");
        builder.Property(entity => entity.Id).UseIdentityByDefaultColumn().HasColumnName("id");
        builder.Property(entity => entity.StableKey).HasColumnName("stable_key").IsRequired();
        builder.Property(entity => entity.Name).HasColumnName("name").IsRequired();
        builder.Property(entity => entity.FeedType).HasColumnName("feed_type").HasMaxLength(16).IsRequired();
        builder.Property(entity => entity.Url).HasColumnName("url").IsRequired();
        builder.Property(entity => entity.IsEnabled).HasColumnName("is_enabled").HasDefaultValue(true);
    }
}

internal sealed class OccurrenceConfiguration : IEntityTypeConfiguration<Occurrence>
{
    public void Configure(EntityTypeBuilder<Occurrence> builder)
    {
        builder.ToTable("occurrences", table =>
            table.HasCheckConstraint("ck_occurrences_seen_range", "first_seen_at <= last_seen_at"));
        builder.HasKey(entity => entity.Id).HasName("pk_occurrences");
        builder.HasAlternateKey(entity => new { entity.SourceId, entity.SourceItemKey })
            .HasName("ak_occurrences_source_id_source_item_key");
        builder.Property(entity => entity.Id).UseIdentityByDefaultColumn().HasColumnName("id");
        builder.Property(entity => entity.TitleId).HasColumnName("title_id");
        builder.Property(entity => entity.SourceId).HasColumnName("source_id");
        builder.Property(entity => entity.SourceItemKey).HasColumnName("source_item_key").IsRequired();
        builder.Property(entity => entity.FeedEntryId).HasColumnName("feed_entry_id");
        builder.Property(entity => entity.TorrentUrl).HasColumnName("torrent_url").IsRequired();
        builder.Property(entity => entity.RawTitle).HasColumnName("raw_title").IsRequired();
        builder.Property(entity => entity.SourceFeedName).HasColumnName("source_feed_name").IsRequired();
        builder.Property(entity => entity.FeedType).HasColumnName("feed_type").HasMaxLength(16);
        builder.Property(entity => entity.SourcePublishedAt).HasColumnName("source_published_at");
        builder.Property(entity => entity.ObservedAt).HasColumnName("observed_at");
        builder.Property(entity => entity.Quality).HasColumnName("quality");
        builder.Property(entity => entity.RipType).HasColumnName("rip_type");
        builder.Property(entity => entity.FirstSeenAt).HasColumnName("first_seen_at");
        builder.Property(entity => entity.LastSeenAt).HasColumnName("last_seen_at");
        builder.HasOne(entity => entity.Title)
            .WithMany(title => title.Occurrences)
            .HasForeignKey(entity => entity.TitleId)
            .OnDelete(DeleteBehavior.Restrict)
            .HasConstraintName("fk_occurrences_titles_title_id");
        builder.HasOne(entity => entity.Source)
            .WithMany(source => source.Occurrences)
            .HasForeignKey(entity => entity.SourceId)
            .OnDelete(DeleteBehavior.Restrict)
            .HasConstraintName("fk_occurrences_sources_source_id");
        builder.HasIndex(entity => new { entity.TitleId, entity.LastSeenAt })
            .HasDatabaseName("ix_occurrences_title_id_last_seen_at");
    }
}