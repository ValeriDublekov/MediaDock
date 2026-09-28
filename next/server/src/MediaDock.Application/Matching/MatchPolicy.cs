using System.Globalization;
using System.Text.RegularExpressions;

namespace MediaDock.Application.Matching;

public enum SourceType
{
    Unknown,
    Movie,
    Series
}

public enum ContentKind
{
    Standard,
    Documentary,
    Short
}

public enum MatchDecisionStatus
{
    Accepted,
    Rejected,
    Ambiguous
}

public sealed record MatchDecision(MatchDecisionStatus Status, string ReasonCode);

public sealed record MediaClassification(SourceType SourceType, ContentKind ContentKind, string MediaType);

public sealed record BroadcastRange(int StartYear, int? EndYear, string Raw)
{
    private const int MinimumYear = 1888;
    private const int MaximumYear = 2035;

    private static readonly Regex RangePattern = new(
        @"^\s*(?<start>\d{4})(?<range>\s*[-–—]\s*(?<end>\d{4}|present|current|ongoing)?)?\s*$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    public bool Contains(int year) => year >= StartYear && (EndYear is null || year <= EndYear.Value);

    public static BroadcastRange? Parse(string? rawValue)
    {
        if (string.IsNullOrWhiteSpace(rawValue) || string.Equals(rawValue.Trim(), "N/A", StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        var raw = rawValue.Trim();
        var match = RangePattern.Match(raw);
        if (!match.Success || !TryParseYear(match.Groups["start"].Value, out var startYear))
        {
            return null;
        }

        int? endYear;
        if (!match.Groups["range"].Success)
        {
            endYear = startYear;
        }
        else if (!match.Groups["end"].Success ||
                 !int.TryParse(match.Groups["end"].Value, NumberStyles.None, CultureInfo.InvariantCulture, out var parsedEnd))
        {
            endYear = null;
        }
        else
        {
            if (parsedEnd < startYear || parsedEnd > MaximumYear)
            {
                return null;
            }

            endYear = parsedEnd;
        }

        return new BroadcastRange(startYear, endYear, raw);
    }

    private static bool TryParseYear(string value, out int year) =>
        int.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out year) &&
        year >= MinimumYear && year <= MaximumYear;
}

public static class MatchReasonCodes
{
    public const string ManualMappingBypass = "manual_mapping_bypass";
    public const string SourceTypeUnknown = "source_type_unknown";
    public const string TypeMismatch = "type_mismatch";
    public const string SeriesSeasonYearUnknown = "series_season_year_unknown";
    public const string SeriesBroadcastRangeUnavailable = "series_broadcast_range_unavailable";
    public const string SeriesSeasonYearInRange = "series_season_year_in_range";
    public const string SeriesSeasonYearOutOfRange = "series_season_year_out_of_range";
    public const string MovieReleaseYearUnknown = "movie_release_year_unknown";
    public const string MovieReleaseYearWithinTolerance = "movie_release_year_within_tolerance";
    public const string MovieReleaseYearMismatch = "movie_release_year_mismatch";
    public const string ExcludedCountry = "excluded_country";
    public const string ExcludedGenre = "excluded_genre";
}

public static class MatchPolicy
{
    public static SourceType NormalizeSourceType(string? value) => value?.Trim().ToLowerInvariant() switch
    {
        "movie" => SourceType.Movie,
        "series" => SourceType.Series,
        _ => SourceType.Unknown
    };

    public static MediaClassification ClassifyMedia(string? rawType, IReadOnlyCollection<string?>? genres = null)
    {
        var sourceType = NormalizeSourceType(rawType);
        var normalizedGenres = NormalizeValues(genres).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var contentKind = normalizedGenres.Contains("documentary")
            ? ContentKind.Documentary
            : normalizedGenres.Contains("short")
                ? ContentKind.Short
                : ContentKind.Standard;
        var mediaType = sourceType == SourceType.Series
            ? "series"
            : contentKind switch
            {
                ContentKind.Documentary => "documentary",
                ContentKind.Short => "short",
                _ => "movie"
            };

        return new MediaClassification(sourceType, contentKind, mediaType);
    }

    public static MatchDecision Evaluate(
        string? expectedSourceType,
        string? actualSourceType = null,
        string? actualMediaType = null,
        int? sourceYear = null,
        int? resolvedYear = null,
        BroadcastRange? broadcastRange = null,
        IReadOnlyCollection<string?>? countries = null,
        IReadOnlyCollection<string?>? genres = null,
        IReadOnlyCollection<string?>? excludedCountries = null,
        IReadOnlyCollection<string?>? excludedGenres = null,
        bool manualMapping = false)
    {
        var expected = NormalizeSourceType(expectedSourceType);
        var actual = NormalizeSourceType(actualSourceType);
        if (actual == SourceType.Unknown)
        {
            actual = actualMediaType?.Trim().ToLowerInvariant() switch
            {
                "series" => SourceType.Series,
                "movie" or "documentary" or "short" => SourceType.Movie,
                _ => SourceType.Unknown
            };
        }

        if (manualMapping)
        {
            return ApplyExclusions(countries, genres, excludedCountries, excludedGenres) ??
                   new MatchDecision(MatchDecisionStatus.Accepted, MatchReasonCodes.ManualMappingBypass);
        }

        if (expected != SourceType.Unknown && actual == SourceType.Unknown)
        {
            return new MatchDecision(MatchDecisionStatus.Ambiguous, MatchReasonCodes.SourceTypeUnknown);
        }

        if (expected != SourceType.Unknown && actual != expected)
        {
            return new MatchDecision(MatchDecisionStatus.Rejected, MatchReasonCodes.TypeMismatch);
        }

        if (expected == SourceType.Unknown && actual == SourceType.Unknown)
        {
            return new MatchDecision(MatchDecisionStatus.Ambiguous, MatchReasonCodes.SourceTypeUnknown);
        }

        if (actual == SourceType.Series)
        {
            if (sourceYear is null)
            {
                return AcceptUnlessExcluded(
                    MatchReasonCodes.SeriesSeasonYearUnknown,
                    countries,
                    genres,
                    excludedCountries,
                    excludedGenres);
            }

            if (broadcastRange is null)
            {
                return AcceptUnlessExcluded(
                    MatchReasonCodes.SeriesBroadcastRangeUnavailable,
                    countries,
                    genres,
                    excludedCountries,
                    excludedGenres);
            }

            return broadcastRange.Contains(sourceYear.Value)
                ? AcceptUnlessExcluded(
                    MatchReasonCodes.SeriesSeasonYearInRange,
                    countries,
                    genres,
                    excludedCountries,
                    excludedGenres)
                : new MatchDecision(MatchDecisionStatus.Rejected, MatchReasonCodes.SeriesSeasonYearOutOfRange);
        }

        if (sourceYear is null || resolvedYear is null)
        {
            return AcceptUnlessExcluded(
                MatchReasonCodes.MovieReleaseYearUnknown,
                countries,
                genres,
                excludedCountries,
                excludedGenres);
        }

        return Math.Abs((long)resolvedYear.Value - sourceYear.Value) <= 1
            ? AcceptUnlessExcluded(
                MatchReasonCodes.MovieReleaseYearWithinTolerance,
                countries,
                genres,
                excludedCountries,
                excludedGenres)
            : new MatchDecision(MatchDecisionStatus.Rejected, MatchReasonCodes.MovieReleaseYearMismatch);
    }

    private static MatchDecision AcceptUnlessExcluded(
        string reasonCode,
        IReadOnlyCollection<string?>? countries,
        IReadOnlyCollection<string?>? genres,
        IReadOnlyCollection<string?>? excludedCountries,
        IReadOnlyCollection<string?>? excludedGenres) =>
        ApplyExclusions(countries, genres, excludedCountries, excludedGenres) ??
        new MatchDecision(MatchDecisionStatus.Accepted, reasonCode);

    private static MatchDecision? ApplyExclusions(
        IReadOnlyCollection<string?>? countries,
        IReadOnlyCollection<string?>? genres,
        IReadOnlyCollection<string?>? excludedCountries,
        IReadOnlyCollection<string?>? excludedGenres)
    {
        var countryValues = NormalizeValues(countries).ToArray();
        var countryExclusions = NormalizeValues(excludedCountries).ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (countryValues.Length > 0 && countryValues.All(countryExclusions.Contains))
        {
            return new MatchDecision(MatchDecisionStatus.Rejected, MatchReasonCodes.ExcludedCountry);
        }

        var genreExclusions = NormalizeValues(excludedGenres).ToHashSet(StringComparer.OrdinalIgnoreCase);
        return NormalizeValues(genres).Any(genreExclusions.Contains)
            ? new MatchDecision(MatchDecisionStatus.Rejected, MatchReasonCodes.ExcludedGenre)
            : null;
    }

    private static IEnumerable<string> NormalizeValues(IReadOnlyCollection<string?>? values) =>
        (values ?? Array.Empty<string?>())
        .Where(value => !string.IsNullOrWhiteSpace(value))
        .Select(value => value!.Trim());
}