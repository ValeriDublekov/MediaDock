using System.ComponentModel.DataAnnotations;

namespace MediaDock.Api.Sources;

/// <summary>Source configuration returned by the API.</summary>
public sealed record SourceResponse(
    long Id,
    string StableKey,
    string Name,
    string FeedType,
    string Url,
    bool IsEnabled);

/// <summary>Validated payload for adding a feed source.</summary>
public sealed record CreateSourceRequest
{
    [Required, MaxLength(100), RegularExpression("^[a-z0-9][a-z0-9._-]{0,99}$")]
    public string StableKey { get; init; } = string.Empty;

    [Required, MaxLength(200)]
    public string Name { get; init; } = string.Empty;

    [Required, RegularExpression("^(movie|series)$")]
    public string FeedType { get; init; } = string.Empty;

    [Required, Url, MaxLength(2048)]
    public string Url { get; init; } = string.Empty;

    public bool IsEnabled { get; init; } = true;
}

/// <summary>Validated payload for replacing a feed source's configuration.</summary>
public sealed record UpdateSourceRequest
{
    [Required, MaxLength(100), RegularExpression("^[a-z0-9][a-z0-9._-]{0,99}$")]
    public string StableKey { get; init; } = string.Empty;

    [Required, MaxLength(200)]
    public string Name { get; init; } = string.Empty;

    [Required, RegularExpression("^(movie|series)$")]
    public string FeedType { get; init; } = string.Empty;

    [Required, Url, MaxLength(2048)]
    public string Url { get; init; } = string.Empty;

    public bool IsEnabled { get; init; }
}

/// <summary>Application matching settings returned by the API.</summary>
public sealed record SettingsResponse(
    IReadOnlyList<string> ExcludedGenres,
    IReadOnlyList<string> ExcludedCountries,
    decimal MinMovieRating,
    decimal MinSeriesRating,
    long MinImdbVotes,
    DateTimeOffset? UpdatedAt);

/// <summary>Validated payload for replacing application matching settings.</summary>
public sealed record UpdateSettingsRequest
{
    [Required, MaxLength(100)]
    public string[]? ExcludedGenres { get; init; } = [];

    [Required, MaxLength(100)]
    public string[]? ExcludedCountries { get; init; } = [];

    [Range(0, 10)]
    public decimal MinMovieRating { get; init; }

    [Range(0, 10)]
    public decimal MinSeriesRating { get; init; }

    [Range(0L, 1_000_000_000L)]
    public long MinImdbVotes { get; init; }
}

/// <summary>Provider settings returned without exposing saved credentials.</summary>
public sealed record ProviderSettingsResponse(
    bool OmdbApiKeyConfigured,
    int OmdbDailyRequestLimit,
    int OscarEnrichmentMaxFilmsPerRun,
    int OscarEnrichmentMaxRequestsPerDay,
    DateTimeOffset? UpdatedAt);

/// <summary>Validated payload for replacing OMDb provider settings.</summary>
public sealed record UpdateProviderSettingsRequest
{
    [MaxLength(512)]
    public string? OmdbApiKey { get; init; }

    public bool ClearOmdbApiKey { get; init; }

    [Range(0, int.MaxValue)]
    public int OmdbDailyRequestLimit { get; init; }

    [Range(0, 100_000)]
    public int OscarEnrichmentMaxFilmsPerRun { get; init; }

    [Range(0, int.MaxValue)]
    public int OscarEnrichmentMaxRequestsPerDay { get; init; }
}