namespace MediaDock.Infrastructure.Persistence.Entities;

public sealed class OscarFilm
{
    public long Id { get; set; }
    public long TitleId { get; set; }
    public string StableKey { get; set; } = string.Empty;
    public string FilmTitle { get; set; } = string.Empty;
    public string NormalizedTitle { get; set; } = string.Empty;
    public int FilmYear { get; set; }
    public string? ImdbId { get; set; }
    public string EnrichmentStatus { get; set; } = "pending";
    public int EnrichmentAttemptCount { get; set; }
    public DateTimeOffset? LastEnrichmentAttemptAt { get; set; }
    public DateTimeOffset? NextEnrichmentAttemptAt { get; set; }
    public string? LastEnrichmentError { get; set; }
    public DateTimeOffset ImportedAt { get; set; }
    public DateTimeOffset UpdatedAt { get; set; }

    public Title Title { get; set; } = null!;
    public ICollection<OscarNomination> Nominations { get; set; } = new List<OscarNomination>();
}