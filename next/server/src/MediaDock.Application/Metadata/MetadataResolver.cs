using System.Security.Cryptography;
using System.Text;

namespace MediaDock.Application.Metadata;

public sealed class MetadataResolver
{
    private static readonly TimeSpan FoundTtl = TimeSpan.FromDays(30);
    private static readonly TimeSpan NotFoundTtl = TimeSpan.FromDays(2);

    private readonly IOmdbClient _client;
    private readonly IMetadataCacheStore _cache;

    public MetadataResolver(IOmdbClient client, IMetadataCacheStore cache)
    {
        _client = client;
        _cache = cache;
    }

    public async Task<MetadataResolution> ResolveAsync(
        string title,
        int? year,
        string sourceType,
        DateTimeOffset now,
        CancellationToken cancellationToken = default,
        OmdbRequestPurpose requestPurpose = OmdbRequestPurpose.RssIngestion)
    {
        var normalizedTitle = NormalizeTitle(title);
        var normalizedSourceType = sourceType.Trim().ToLowerInvariant();
        if (normalizedTitle.Length == 0 || normalizedSourceType is not ("movie" or "series"))
        {
            return new MetadataResolution(
                MetadataLookupStatus.InvalidRequest,
                null,
                false,
                0,
                "invalid_lookup");
        }

        var yearSemantics = normalizedSourceType == "series"
            ? "series_season_year"
            : "movie_release_year";
        var cacheKey = CreateCacheKey(normalizedTitle, year, normalizedSourceType, yearSemantics);
        var cached = await _cache.GetAsync(cacheKey, cancellationToken);
        if (cached is not null && cached.ExpiresAt > now)
        {
            return new MetadataResolution(cached.Status, cached.Metadata, true, 0);
        }

        var result = await _client.LookupAsync(
            title.Trim(),
            year,
            normalizedSourceType,
            cancellationToken,
            requestPurpose);
        if (result.Status == MetadataLookupStatus.Found && result.Metadata is not null)
        {
            await StoreAsync(
                cacheKey,
                normalizedTitle,
                year,
                yearSemantics,
                normalizedSourceType,
                MetadataLookupStatus.Found,
                result.Metadata,
                now,
                FoundTtl,
                cancellationToken);
        }
        else if (result.Status == MetadataLookupStatus.ConfirmedNotFound)
        {
            await StoreAsync(
                cacheKey,
                normalizedTitle,
                year,
                yearSemantics,
                normalizedSourceType,
                MetadataLookupStatus.ConfirmedNotFound,
                null,
                now,
                NotFoundTtl,
                cancellationToken);
        }
        else if (result.Status == MetadataLookupStatus.Found)
        {
            result = result with
            {
                Status = MetadataLookupStatus.ProviderFailure,
                ErrorCode = "invalid_metadata"
            };
        }

        return new MetadataResolution(
            result.Status,
            result.Metadata,
            false,
            result.HttpAttempts,
            result.ErrorCode);
    }

    private async Task StoreAsync(
        string cacheKey,
        string normalizedTitle,
        int? year,
        string yearSemantics,
        string sourceType,
        MetadataLookupStatus status,
        MetadataDetails? metadata,
        DateTimeOffset now,
        TimeSpan ttl,
        CancellationToken cancellationToken)
    {
        await _cache.StoreAsync(
            cacheKey,
            new MetadataCacheValue(
                normalizedTitle,
                year,
                yearSemantics,
                sourceType,
                status,
                metadata,
                now,
                now.Add(ttl)),
            cancellationToken);
    }

    private static string CreateCacheKey(
        string title,
        int? year,
        string sourceType,
        string yearSemantics)
    {
        var identity = $"v1:{title}:{year?.ToString() ?? ""}:{sourceType}:{yearSemantics}";
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(identity))).ToLowerInvariant();
    }

    private static string NormalizeTitle(string? title) =>
        string.Join(' ', (title ?? string.Empty).Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries))
            .ToLowerInvariant();
}