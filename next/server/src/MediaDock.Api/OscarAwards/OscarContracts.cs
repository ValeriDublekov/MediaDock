using System.ComponentModel.DataAnnotations;

namespace MediaDock.Api.OscarAwards;

public sealed record OscarCatalogQuery
{
    [Range(1, 1_000_000)]
    public int? Page { get; init; }

    [Range(1, 100)]
    public int? PageSize { get; init; }

    [MaxLength(200)]
    public string? Search { get; init; }

    [Range(1800, 2200)]
    public int? YearFrom { get; init; }

    [Range(1800, 2200)]
    public int? YearTo { get; init; }

    [MaxLength(100)]
    public string? Category { get; init; }

    [RegularExpression("^(winner|nominee)$")]
    public string? Result { get; init; }

    [RegularExpression("^(pending|enriched|not_found|temporary_error)$")]
    public string? EnrichmentStatus { get; init; }
}

public sealed record OscarFilmResponse(
    long Id,
    long TitleId,
    string Title,
    string MetadataTitle,
    int? MetadataYear,
    int FilmYear,
    string? ImdbId,
    string EnrichmentStatus,
    int EnrichmentAttemptCount,
    DateTimeOffset? LastEnrichmentAttemptAt,
    DateTimeOffset? NextEnrichmentAttemptAt,
    string? LastEnrichmentError,
    string MediaType,
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
    IReadOnlyList<OscarNominationResponse> Nominations);

public sealed record OscarNominationResponse(
    long Id,
    int Ceremony,
    string Class,
    string CanonicalCategory,
    string Category,
    string Name,
    string Nominees,
    string NomineeIds,
    string Detail,
    bool IsWinner);