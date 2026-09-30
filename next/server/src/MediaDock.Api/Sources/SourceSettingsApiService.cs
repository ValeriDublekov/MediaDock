using MediaDock.Api.Middleware;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using MediaDock.Infrastructure.Rss;
using Microsoft.EntityFrameworkCore;
using Npgsql;

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

    Task<ProviderSettingsResponse> GetProviderSettingsAsync(CancellationToken cancellationToken);

    Task<ProviderSettingsResponse> UpdateProviderSettingsAsync(
        UpdateProviderSettingsRequest request,
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
            .Where(setting => setting.Id == 1)
            .Select(setting => new SettingsResponse(
                setting.ExcludedGenres,
                setting.ExcludedCountries,
                setting.MinMovieRating,
                setting.MinSeriesRating,
                setting.MinImdbVotes,
                setting.UpdatedAt))
            .SingleOrDefaultAsync(cancellationToken);

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

        var settings = await dbContext.Settings.SingleOrDefaultAsync(value => value.Id == 1, cancellationToken)
            ?? await GetOrCreateSettingsAsync(cancellationToken);

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

    public async Task<ProviderSettingsResponse> GetProviderSettingsAsync(CancellationToken cancellationToken)
    {
        var settings = await dbContext.Settings
            .AsNoTracking()
            .Where(setting => setting.Id == 1)
            .Select(setting => new ProviderSettingsResponse(
                !string.IsNullOrWhiteSpace(setting.OmdbApiKey),
                setting.OmdbDailyRequestLimit,
                setting.OscarEnrichmentMaxFilmsPerRun,
                setting.OscarEnrichmentMaxRequestsPerDay,
                setting.UpdatedAt))
            .SingleOrDefaultAsync(cancellationToken);

        return settings ?? new ProviderSettingsResponse(false, 0, 0, 0, null);
    }

    public async Task<ProviderSettingsResponse> UpdateProviderSettingsAsync(
        UpdateProviderSettingsRequest request,
        CancellationToken cancellationToken)
    {
        var settings = await dbContext.Settings.SingleOrDefaultAsync(value => value.Id == 1, cancellationToken);
        var errors = new Dictionary<string, string[]>();
        if (request.ClearOmdbApiKey && !string.IsNullOrWhiteSpace(request.OmdbApiKey))
        {
            errors[nameof(request.OmdbApiKey)] = ["Provide a key or clear the saved key, not both."];
        }

        var hasOmdbApiKey = !request.ClearOmdbApiKey
            && (!string.IsNullOrWhiteSpace(request.OmdbApiKey)
                || !string.IsNullOrWhiteSpace(settings?.OmdbApiKey));
        if (hasOmdbApiKey && request.OmdbDailyRequestLimit <= 0)
        {
            errors[nameof(request.OmdbDailyRequestLimit)] =
                ["A positive shared daily request limit is required when an API key is configured."];
        }

        if (request.OscarEnrichmentMaxFilmsPerRun > 0 && request.OscarEnrichmentMaxRequestsPerDay == 0)
        {
            errors[nameof(request.OscarEnrichmentMaxRequestsPerDay)] =
                ["A positive Oscar request limit is required when enrichment is enabled."];
        }

        if (errors.Count > 0)
        {
            throw new ApiValidationException(errors);
        }

        if (settings is null)
        {
            settings = await GetOrCreateSettingsAsync(cancellationToken);
        }

        if (request.ClearOmdbApiKey)
        {
            settings.OmdbApiKey = null;
        }
        else if (!string.IsNullOrWhiteSpace(request.OmdbApiKey))
        {
            settings.OmdbApiKey = request.OmdbApiKey.Trim();
        }

        settings.OmdbDailyRequestLimit = request.OmdbDailyRequestLimit;
        settings.OscarEnrichmentMaxFilmsPerRun = request.OscarEnrichmentMaxFilmsPerRun;
        settings.OscarEnrichmentMaxRequestsPerDay = request.OscarEnrichmentMaxRequestsPerDay;
        settings.UpdatedAt = DateTimeOffset.UtcNow;
        await dbContext.SaveChangesAsync(cancellationToken);

        return ToProviderSettingsResponse(settings);
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

    private static ProviderSettingsResponse ToProviderSettingsResponse(AppSetting settings) => new(
        !string.IsNullOrWhiteSpace(settings.OmdbApiKey),
        settings.OmdbDailyRequestLimit,
        settings.OscarEnrichmentMaxFilmsPerRun,
        settings.OscarEnrichmentMaxRequestsPerDay,
        settings.UpdatedAt);

    private async Task<AppSetting> GetOrCreateSettingsAsync(CancellationToken cancellationToken)
    {
        var settings = await dbContext.Settings.SingleOrDefaultAsync(value => value.Id == 1, cancellationToken);
        if (settings is not null)
        {
            return settings;
        }

        settings = new AppSetting { Id = 1, UpdatedAt = DateTimeOffset.UtcNow };
        dbContext.Settings.Add(settings);
        try
        {
            await dbContext.SaveChangesAsync(cancellationToken);
            return settings;
        }
        catch (DbUpdateException exception) when (IsSettingsSingletonViolation(exception))
        {
            dbContext.ChangeTracker.Clear();
            return await dbContext.Settings.SingleAsync(value => value.Id == 1, cancellationToken);
        }
    }

    private static bool IsSettingsSingletonViolation(DbUpdateException exception) =>
        exception.InnerException is PostgresException
        {
            SqlState: PostgresErrorCodes.UniqueViolation,
            ConstraintName: "pk_settings"
        };
}