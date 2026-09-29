using System.Text.Json;
using MediaDock.Application.Metadata;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;

namespace MediaDock.Infrastructure.Metadata;

public sealed class PostgresMetadataCacheStore(MediaDockDbContext dbContext) : IMetadataCacheStore
{
    public async Task<MetadataCacheValue?> GetAsync(
        string cacheKey,
        CancellationToken cancellationToken = default)
    {
        var entity = await dbContext.MetadataCache
            .SingleOrDefaultAsync(entry => entry.CacheKey == cacheKey, cancellationToken);
        if (entity is null)
        {
            return null;
        }

        if (entity.ExpiresAt <= DateTimeOffset.UtcNow)
        {
            dbContext.MetadataCache.Remove(entity);
            await dbContext.SaveChangesAsync(cancellationToken);
            return null;
        }

        var status = entity.Status switch
        {
            "found" => MetadataLookupStatus.Found,
            "confirmed_not_found" => MetadataLookupStatus.ConfirmedNotFound,
            _ => (MetadataLookupStatus?)null
        };
        if (status is null)
        {
            dbContext.MetadataCache.Remove(entity);
            await dbContext.SaveChangesAsync(cancellationToken);
            return null;
        }

        MetadataDetails? metadata = null;
        if (status == MetadataLookupStatus.Found)
        {
            try
            {
                metadata = JsonSerializer.Deserialize<MetadataDetails>(entity.PayloadJson ?? string.Empty);
            }
            catch (JsonException)
            {
                dbContext.MetadataCache.Remove(entity);
                await dbContext.SaveChangesAsync(cancellationToken);
                return null;
            }

            if (metadata is null)
            {
                dbContext.MetadataCache.Remove(entity);
                await dbContext.SaveChangesAsync(cancellationToken);
                return null;
            }
        }

        return new MetadataCacheValue(
            entity.LookupTitle,
            entity.LookupYear,
            entity.LookupYearSemantics,
            entity.SourceType,
            status.Value,
            metadata,
            entity.FetchedAt,
            entity.ExpiresAt);
    }

    public async Task StoreAsync(
        string cacheKey,
        MetadataCacheValue value,
        CancellationToken cancellationToken = default)
    {
        if (value.Status is not (MetadataLookupStatus.Found or MetadataLookupStatus.ConfirmedNotFound))
        {
            throw new ArgumentOutOfRangeException(nameof(value), "Only confirmed metadata outcomes may be cached.");
        }

        var entity = await dbContext.MetadataCache
            .SingleOrDefaultAsync(entry => entry.CacheKey == cacheKey, cancellationToken);
        if (entity is null)
        {
            entity = new MetadataCacheEntry { CacheKey = cacheKey };
            dbContext.MetadataCache.Add(entity);
        }

        entity.LookupTitle = value.LookupTitle;
        entity.LookupYear = value.LookupYear;
        entity.LookupYearSemantics = value.LookupYearSemantics;
        entity.SourceType = value.SourceType;
        entity.Status = value.Status == MetadataLookupStatus.Found ? "found" : "confirmed_not_found";
        entity.PayloadJson = value.Metadata is null ? null : JsonSerializer.Serialize(value.Metadata);
        entity.FetchedAt = value.FetchedAt;
        entity.ExpiresAt = value.ExpiresAt;
        await dbContext.SaveChangesAsync(cancellationToken);
    }
}