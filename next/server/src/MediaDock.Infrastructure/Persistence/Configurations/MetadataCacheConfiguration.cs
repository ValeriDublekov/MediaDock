using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace MediaDock.Infrastructure.Persistence.Configurations;

internal sealed class MetadataCacheConfiguration : IEntityTypeConfiguration<MetadataCacheEntry>
{
    public void Configure(EntityTypeBuilder<MetadataCacheEntry> builder)
    {
        builder.ToTable("metadata_cache", table =>
        {
            table.HasCheckConstraint("ck_metadata_cache_status", "status IN ('found', 'confirmed_not_found')");
            table.HasCheckConstraint("ck_metadata_cache_expiry", "expires_at > fetched_at");
        });
        builder.HasKey(entity => entity.Id).HasName("pk_metadata_cache");
        builder.HasAlternateKey(entity => entity.CacheKey).HasName("ak_metadata_cache_cache_key");
        builder.Property(entity => entity.Id).UseIdentityByDefaultColumn().HasColumnName("id");
        builder.Property(entity => entity.CacheKey).HasColumnName("cache_key").IsRequired();
        builder.Property(entity => entity.LookupTitle).HasColumnName("lookup_title").IsRequired();
        builder.Property(entity => entity.LookupYear).HasColumnName("lookup_year");
        builder.Property(entity => entity.LookupYearSemantics).HasColumnName("lookup_year_semantics").HasMaxLength(32).IsRequired();
        builder.Property(entity => entity.SourceType).HasColumnName("source_type").HasMaxLength(16).IsRequired();
        builder.Property(entity => entity.LookupIdentity).HasColumnName("lookup_identity");
        builder.Property(entity => entity.Status).HasColumnName("status").HasMaxLength(32).IsRequired();
        builder.Property(entity => entity.PayloadJson).HasColumnName("payload_json").HasColumnType("jsonb");
        builder.Property(entity => entity.FetchedAt).HasColumnName("fetched_at");
        builder.Property(entity => entity.ExpiresAt).HasColumnName("expires_at");
        builder.HasIndex(entity => entity.ExpiresAt).HasDatabaseName("ix_metadata_cache_expires_at");
    }
}