using MediaDock.Api.Middleware;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using MediaDock.Infrastructure.Rss;
using Microsoft.EntityFrameworkCore;

namespace MediaDock.Api.Sources;

internal interface ISourceSettingsApiService
{
    Task<IReadOnlyList<SourceResponse>> GetSourcesAsync(CancellationToken cancellationToken);

    Task<SourceResponse> GetSourceAsync(long id, CancellationToken cancellationToken);

    Task<SourceResponse> CreateSourceAsync(CreateSourceRequest request, CancellationToken cancellationToken);

    Task<SourceResponse> UpdateSourceAsync(
        long id,
        UpdateSourceRequest request,
        CancellationToken cancellationToken);

    Task<SettingsResponse> GetSettingsAsync(CancellationToken cancellationToken);

    Task<SettingsResponse> UpdateSettingsAsync(
        UpdateSettingsRequest request,
        CancellationToken cancellationToken);
}

internal sealed class SourceSettingsApiService(MediaDockDbContext dbContext) : ISourceSettingsApiService
{
    public async Task<IReadOnlyList<SourceResponse>> GetSourcesAsync(CancellationToken cancellationToken) =>
        await dbContext.Sources
            .AsNoTracking()
            .OrderBy(source => source.Name)
            .ThenBy(source => source.Id)
            .Select(source => ToResponse(source))
            .ToListAsync(cancellationToken);

    public async Task<SourceResponse> GetSourceAsync(long id, CancellationToken cancellationToken)
    {
        var source = await dbContext.Sources
            .AsNoTracking()
            .Where(entity => entity.Id == id)
            .Select(entity => new SourceResponse(
                entity.Id,
                entity.StableKey,
                entity.Name,
                entity.FeedType,
                entity.Url,
                entity.IsEnabled))
            .FirstOrDefaultAsync(cancellationToken);

        return source ?? throw new ApiNotFoundException("Source not found.");
    }

    public async Task<SourceResponse> CreateSourceAsync(
        CreateSourceRequest request,
        CancellationToken cancellationToken)
    {
        ValidateFeedUrl(request.Url);

        var stableKey = request.StableKey.Trim();
        if (await dbContext.Sources.AnyAsync(source => source.StableKey == stableKey, cancellationToken))
        {
            throw new ApiConflictException("A source with this stable key already exists.");
        }

        var source = new Source
        {
            StableKey = stableKey,
            Name = request.Name.Trim(),
            FeedType = request.FeedType.Trim(),
            Url = request.Url.Trim(),
            IsEnabled = request.IsEnabled
        };
        dbContext.Sources.Add(source);
        await dbContext.SaveChangesAsync(cancellationToken);
        return ToResponse(source);
    }

    public async Task<SourceResponse> UpdateSourceAsync(
        long id,
        UpdateSourceRequest request,
        CancellationToken cancellationToken)
    {
        ValidateFeedUrl(request.Url);

        var source = await dbContext.Sources.FirstOrDefaultAsync(entity => entity.Id == id, cancellationToken)
            ?? throw new ApiNotFoundException("Source not found.");
        var stableKey = request.StableKey.Trim();
        if (await dbContext.Sources.AnyAsync(
                entity => entity.Id != id && entity.StableKey == stableKey,
                cancellationToken))
        {
            throw new ApiConflictException("A source with this stable key already exists.");
        }

        source.StableKey = stableKey;
        source.Name = request.Name.Trim();
        source.FeedType = request.FeedType.Trim();
        source.Url = request.Url.Trim();
        source.IsEnabled = request.IsEnabled;
        await dbContext.SaveChangesAsync(cancellationToken);
        return ToResponse(source);
    }

    public async Task<SettingsResponse> GetSettingsAsync(CancellationToken cancellationToken)
    {
        var settings = await dbContext.Settings
            .AsNoTracking()
            .OrderBy(setting => setting.Id)
            .Select(setting => new SettingsResponse(
                setting.ExcludedGenres,
                setting.ExcludedCountries,
                setting.MinMovieRating,
                setting.MinSeriesRating,
                setting.MinImdbVotes,
                setting.UpdatedAt))
            .FirstOrDefaultAsync(cancellationToken);

        return settings ?? new SettingsResponse([], [], 0m, 0m, 0, null);
    }

    public async Task<SettingsResponse> UpdateSettingsAsync(
        UpdateSettingsRequest request,
        CancellationToken cancellationToken)
    {
        var errors = new Dictionary<string, string[]>();
        var excludedGenres = NormalizeFilterValues(request.ExcludedGenres, nameof(request.ExcludedGenres), errors);
        var excludedCountries = NormalizeFilterValues(request.ExcludedCountries, nameof(request.ExcludedCountries), errors);
        if (errors.Count > 0)
        {
            throw new ApiValidationException(errors);
        }

        var settings = await dbContext.Settings.OrderBy(value => value.Id).FirstOrDefaultAsync(cancellationToken);
        if (settings is null)
        {
            settings = new AppSetting();
            dbContext.Settings.Add(settings);
        }

        settings.ExcludedGenres = excludedGenres;
        settings.ExcludedCountries = excludedCountries;
        settings.MinMovieRating = request.MinMovieRating;
        settings.MinSeriesRating = request.MinSeriesRating;
        settings.MinImdbVotes = request.MinImdbVotes;
        settings.UpdatedAt = DateTimeOffset.UtcNow;
        await dbContext.SaveChangesAsync(cancellationToken);

        return new SettingsResponse(
            settings.ExcludedGenres,
            settings.ExcludedCountries,
            settings.MinMovieRating,
            settings.MinSeriesRating,
            settings.MinImdbVotes,
            settings.UpdatedAt);
    }

    private static void ValidateFeedUrl(string url)
    {
        if (url.Length <= 2048
            && !url.Any(char.IsWhiteSpace)
            && Uri.TryCreate(url, UriKind.Absolute, out var uri)
            && string.Equals(uri.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase)
            && string.IsNullOrEmpty(uri.UserInfo)
            && string.Equals(
                uri.IdnHost.TrimEnd('.'),
                RssFeedTransport.AllowedFeedHost,
                StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        throw new ApiValidationException(new Dictionary<string, string[]>
        {
            [nameof(CreateSourceRequest.Url)] =
            ["Feed URLs must use HTTPS on the configured feed host."]
        });
    }

    private static string[] NormalizeFilterValues(
        string[]? values,
        string propertyName,
        IDictionary<string, string[]> errors)
    {
        if (values is null || values.Any(value =>
                string.IsNullOrWhiteSpace(value) || value.Trim().Length > 100))
        {
            errors[propertyName] = ["Values must be non-empty and at most 100 characters."];
            return [];
        }

        return values
            .Select(value => value.Trim())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(value => value, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    private static SourceResponse ToResponse(Source source) => new(
        source.Id,
        source.StableKey,
        source.Name,
        source.FeedType,
        source.Url,
        source.IsEnabled);
}