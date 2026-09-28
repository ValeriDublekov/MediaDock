using MediaDock.Application.Parsing;

namespace MediaDock.UnitTests;

[Trait("Category", "Parsing")]
public sealed class RutrackerTitleParserTests
{
    [Fact]
    public void SelectsLatinTitleAndPreservesEmbeddedSlash()
    {
        var parsed = RutrackerTitleParser.Parse(
            "Без лица / Face/Off (Джон Ву) [1997, США, BDRip 1080p]",
            "movie");

        Assert.Equal("Face/Off", parsed.Title);
        Assert.Equal("face/off", parsed.NormalizedTitle);
        Assert.Equal(1997, parsed.Year);
        Assert.False(parsed.IsSeries);
        Assert.Contains("embedded_slash_preserved", parsed.ReasonCodes);
    }

    [Fact]
    public void ConfiguredFeedTypeOverridesSeriesMarkers()
    {
        const string rawTitle = "Example / Example Title / Сезон: 1 / Серии: 1-8 из 8 [2026]";

        var movie = RutrackerTitleParser.Parse(rawTitle, "movie");
        var series = RutrackerTitleParser.Parse(rawTitle, "series");

        Assert.Equal("Example", movie.Title);
        Assert.False(movie.IsSeries);
        Assert.Contains("feed_type_authoritative_movie", movie.ReasonCodes);
        Assert.Equal("Example", series.Title);
        Assert.True(series.IsSeries);
        Assert.Contains("feed_type_authoritative_series", series.ReasonCodes);
    }

    [Fact]
    public void UnknownFeedInfersSeriesFromExplicitMarkerWithoutSubstringFalsePositives()
    {
        var series = RutrackerTitleParser.Parse("Monarch: Legacy of Monsters / Season 2 [2024]");
        var movie = RutrackerTitleParser.Parse("Season of the Witch [2011]");

        Assert.Equal("Monarch: Legacy of Monsters", series.Title);
        Assert.True(series.IsSeries);
        Assert.Contains("series_inferred_from_markers", series.ReasonCodes);
        Assert.Equal("Season of the Witch", movie.Title);
        Assert.False(movie.IsSeries);
    }

    [Fact]
    public void ExtractsRealisticYearsAndReportsMissingOrInvalidYears()
    {
        var lowerBoundary = RutrackerTitleParser.Parse("Old Film [1888, BDRip]");
        var upperBoundary = RutrackerTitleParser.Parse("Future Film [2035, BDRip]");
        var missing = RutrackerTitleParser.Parse("Film [1080p, BDRip]");
        var invalid = RutrackerTitleParser.Parse("Film [2150, BDRip]");

        Assert.Equal(1888, lowerBoundary.Year);
        Assert.Equal(2035, upperBoundary.Year);
        Assert.Null(missing.Year);
        Assert.Contains("year_missing", missing.ReasonCodes);
        Assert.Null(invalid.Year);
        Assert.Contains("invalid_year_range", invalid.ReasonCodes);
    }

    [Fact]
    public void PreservesMeaningfulParenthesesAndHandlesEmptyInput()
    {
        var titled = RutrackerTitleParser.Parse(
            "The Lord of the Rings: The Two Towers (Extended Edition) [2002]");
        var empty = RutrackerTitleParser.Parse(null);

        Assert.Equal("The Lord of the Rings: The Two Towers (Extended Edition)", titled.Title);
        Assert.Equal("the lord of the rings: the two towers (extended edition)", titled.NormalizedTitle);
        Assert.Equal(string.Empty, empty.Title);
        Assert.Null(empty.Year);
        Assert.Contains("empty_raw_title", empty.ReasonCodes);
    }
}