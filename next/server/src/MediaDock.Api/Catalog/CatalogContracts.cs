using System.ComponentModel.DataAnnotations;

namespace MediaDock.Api.Catalog;

/// <summary>Validated catalog search, filter, and pagination parameters.</summary>
public sealed record CatalogQuery
{
    [Range(1, 1_000_000)]
    public int? Page { get; init; }

    [Range(1, 100)]
    public int? PageSize { get; init; }

    [MaxLength(200)]
    public string? Search { get; init; }

    [RegularExpression("^(movie|series|documentary|short)$")]
    public string? MediaType { get; init; }

    [RegularExpression("^(movie|series)$")]
    public string? SourceType { get; init; }

    [RegularExpression("^(standard|documentary|short)$")]
    public string? ContentKind { get; init; }

    [Range(1800, 2200)]
    public int? YearFrom { get; init; }

    [Range(1800, 2200)]
    public int? YearTo { get; init; }

    [MaxLength(100)]
    public string? Genre { get; init; }

    [MaxLength(100)]
    public string? Country { get; init; }

    [Range(1L, long.MaxValue)]
    public long? SourceId { get; init; }
}

/// <summary>Validated pagination parameters for a title's occurrences.</summary>
public sealed record OccurrencesQuery
{
    [Range(1, 1_000_000)]
    public int? Page { get; init; }

    [Range(1, 100)]
    public int? PageSize { get; init; }
}

/// <summary>Compact catalog title data returned in search results.</summary>
public sealed record CatalogTitleResponse(
    long Id,
    string Title,
    int? Year,
    string MediaType,
    string? SourceType,
    string? ContentKind,
    decimal? ImdbRating,
    string? PosterUrl,
    IReadOnlyList<string> Genres,
    IReadOnlyList<string> Countries,
    DateTimeOffset? LastSeenAt,
    int OccurrenceCount);

/// <summary>Full metadata for one catalog title.</summary>
public sealed record TitleDetailsResponse(
    long Id,
    string Title,
    int? Year,
    string MediaType,
    string? SourceType,
    string? ContentKind,
    int? BroadcastRangeStartYear,
    int? BroadcastRangeEndYear,
    string? BroadcastRangeRaw,
    string? ImdbId,
    decimal? ImdbRating,
    long? ImdbVotes,
    decimal? Metascore,
    IReadOnlyList<string> Genres,
    IReadOnlyList<string> Countries,
    string? Director,
    string? Plot,
    string? PosterUrl,
    string? Runtime,
    string? Awards,
    string? BoxOffice,
    DateTimeOffset? FirstSeenAt,
    DateTimeOffset? LastSeenAt,
    DateTimeOffset UpdatedAt,
    int OccurrenceCount);

/// <summary>One observed feed occurrence of a catalog title.</summary>
public sealed record OccurrenceResponse(
    long Id,
    long TitleId,
    long SourceId,
    string SourceName,
    string SourceItemKey,
    string? FeedEntryId,
    string TorrentUrl,
    string RawTitle,
    string SourceFeedName,
    string? FeedType,
    DateTimeOffset? SourcePublishedAt,
    DateTimeOffset? ObservedAt,
    string? Quality,
    string? RipType,
    DateTimeOffset FirstSeenAt,
    DateTimeOffset LastSeenAt);