namespace MediaDock.Infrastructure.Persistence.Entities;

public sealed class AppSetting
{
    public long Id { get; set; }
    public string[] ExcludedGenres { get; set; } = Array.Empty<string>();
    public string[] ExcludedCountries { get; set; } = Array.Empty<string>();
    public decimal MinMovieRating { get; set; }
    public decimal MinSeriesRating { get; set; }
    public long MinImdbVotes { get; set; }
    public string? OmdbApiKey { get; set; }
    public int OmdbDailyRequestLimit { get; set; }
    public int OscarEnrichmentMaxFilmsPerRun { get; set; }
    public int OscarEnrichmentMaxRequestsPerDay { get; set; }
    public DateTimeOffset UpdatedAt { get; set; }
}