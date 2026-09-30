namespace MediaDock.Infrastructure.Persistence.Entities;

public sealed class Title
{
    public long Id { get; set; }
    public string TitleText { get; set; } = string.Empty;
    public string NormalizedTitle { get; set; } = string.Empty;
    public int? Year { get; set; }
    public string MediaType { get; set; } = string.Empty;
    public string? SourceType { get; set; }
    public string? ContentKind { get; set; }
    public int? BroadcastRangeStartYear { get; set; }
    public int? BroadcastRangeEndYear { get; set; }
    public string? BroadcastRangeRaw { get; set; }
    public string? ImdbId { get; set; }
    public decimal? ImdbRating { get; set; }
    public long? ImdbVotes { get; set; }
    public decimal? Metascore { get; set; }
    public string[] Genres { get; set; } = Array.Empty<string>();
    public string[] Countries { get; set; } = Array.Empty<string>();
    public string? Director { get; set; }
    public string? Plot { get; set; }
    public string? PosterUrl { get; set; }
    public string? Runtime { get; set; }
    public string? Awards { get; set; }
    public string? BoxOffice { get; set; }
    public DateTimeOffset? FirstSeenAt { get; set; }
    public DateTimeOffset? LastSeenAt { get; set; }
    public DateTimeOffset UpdatedAt { get; set; }

    public ICollection<Occurrence> Occurrences { get; set; } = new List<Occurrence>();
}