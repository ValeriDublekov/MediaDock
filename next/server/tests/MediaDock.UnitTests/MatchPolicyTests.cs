using MediaDock.Application.Matching;

namespace MediaDock.UnitTests;

[Trait("Category", "Matching")]
public sealed class MatchPolicyTests
{
    [Theory]
    [InlineData(2024, 2024, MatchDecisionStatus.Accepted, MatchReasonCodes.MovieReleaseYearWithinTolerance)]
    [InlineData(2024, 2023, MatchDecisionStatus.Accepted, MatchReasonCodes.MovieReleaseYearWithinTolerance)]
    [InlineData(2024, 2025, MatchDecisionStatus.Accepted, MatchReasonCodes.MovieReleaseYearWithinTolerance)]
    [InlineData(2024, 2022, MatchDecisionStatus.Rejected, MatchReasonCodes.MovieReleaseYearMismatch)]
    public void MovieYearsUseInclusiveOneYearTolerance(
        int sourceYear,
        int resolvedYear,
        MatchDecisionStatus expectedStatus,
        string expectedReason)
    {
        var decision = MatchPolicy.Evaluate(
            expectedSourceType: "movie",
            actualSourceType: "movie",
            sourceYear: sourceYear,
            resolvedYear: resolvedYear);

        Assert.Equal(expectedStatus, decision.Status);
        Assert.Equal(expectedReason, decision.ReasonCode);
    }

    [Theory]
    [InlineData("2007–2015", 2007, MatchDecisionStatus.Accepted, MatchReasonCodes.SeriesSeasonYearInRange)]
    [InlineData("2007-2015", 2015, MatchDecisionStatus.Accepted, MatchReasonCodes.SeriesSeasonYearInRange)]
    [InlineData("2007-2015", 2006, MatchDecisionStatus.Rejected, MatchReasonCodes.SeriesSeasonYearOutOfRange)]
    [InlineData("2019-", 2026, MatchDecisionStatus.Accepted, MatchReasonCodes.SeriesSeasonYearInRange)]
    [InlineData("2019-Present", 2018, MatchDecisionStatus.Rejected, MatchReasonCodes.SeriesSeasonYearOutOfRange)]
    public void SeriesSeasonYearUsesBroadcastRange(
        string rawRange,
        int sourceYear,
        MatchDecisionStatus expectedStatus,
        string expectedReason)
    {
        var decision = MatchPolicy.Evaluate(
            expectedSourceType: "series",
            actualSourceType: "series",
            sourceYear: sourceYear,
            resolvedYear: 2007,
            broadcastRange: BroadcastRange.Parse(rawRange));

        Assert.Equal(expectedStatus, decision.Status);
        Assert.Equal(expectedReason, decision.ReasonCode);
    }

    [Fact]
    public void UnknownYearsAndUnavailableSeriesRangeAreNonDisqualifying()
    {
        var unknownMovieYear = MatchPolicy.Evaluate("movie", "movie");
        var unknownSeriesYear = MatchPolicy.Evaluate("series", "series", sourceYear: null);
        var unavailableRange = MatchPolicy.Evaluate("series", "series", sourceYear: 2026, resolvedYear: 2007);

        Assert.Equal(MatchReasonCodes.MovieReleaseYearUnknown, unknownMovieYear.ReasonCode);
        Assert.Equal(MatchReasonCodes.SeriesSeasonYearUnknown, unknownSeriesYear.ReasonCode);
        Assert.Equal(MatchReasonCodes.SeriesBroadcastRangeUnavailable, unavailableRange.ReasonCode);
        Assert.All(new[] { unknownMovieYear, unknownSeriesYear, unavailableRange }, decision =>
            Assert.Equal(MatchDecisionStatus.Accepted, decision.Status));
    }

    [Fact]
    public void UnknownTypeIsAmbiguousAndKnownMismatchIsRejected()
    {
        var ambiguous = MatchPolicy.Evaluate(expectedSourceType: "series");
        var mismatch = MatchPolicy.Evaluate(expectedSourceType: "movie", actualSourceType: "series");

        Assert.Equal(MatchDecisionStatus.Ambiguous, ambiguous.Status);
        Assert.Equal(MatchReasonCodes.SourceTypeUnknown, ambiguous.ReasonCode);
        Assert.Equal(MatchDecisionStatus.Rejected, mismatch.Status);
        Assert.Equal(MatchReasonCodes.TypeMismatch, mismatch.ReasonCode);
    }

    [Fact]
    public void UnknownFeedCanUseResolvedTypeAndMediaClassificationKeepsSourceType()
    {
        var inferred = MatchPolicy.Evaluate(
            expectedSourceType: null,
            actualMediaType: "documentary",
            sourceYear: 2024,
            resolvedYear: 2024);
        var documentarySeries = MatchPolicy.ClassifyMedia("series", new[] { "Documentary", "History" });
        var shortMovie = MatchPolicy.ClassifyMedia("movie", new[] { "Short" });

        Assert.Equal(MatchDecisionStatus.Accepted, inferred.Status);
        Assert.Equal(SourceType.Series, documentarySeries.SourceType);
        Assert.Equal(ContentKind.Documentary, documentarySeries.ContentKind);
        Assert.Equal("series", documentarySeries.MediaType);
        Assert.Equal(ContentKind.Short, shortMovie.ContentKind);
        Assert.Equal("short", shortMovie.MediaType);
    }

    [Fact]
    public void CountryAndGenreExclusionsAreAppliedWithoutOverRejectingMixedCountries()
    {
        var allCountriesExcluded = MatchPolicy.Evaluate(
            "movie",
            "movie",
            countries: new[] { " Russia ", "RUSSIA" },
            excludedCountries: new[] { "russia" });
        var mixedCountries = MatchPolicy.Evaluate(
            "movie",
            "movie",
            countries: new[] { "Russia", "Canada" },
            excludedCountries: new[] { "Russia" });
        var excludedGenre = MatchPolicy.Evaluate(
            "movie",
            "movie",
            genres: new[] { "Drama", " Horror " },
            excludedGenres: new[] { "horror" });

        Assert.Equal(MatchReasonCodes.ExcludedCountry, allCountriesExcluded.ReasonCode);
        Assert.Equal(MatchDecisionStatus.Rejected, allCountriesExcluded.Status);
        Assert.Equal(MatchDecisionStatus.Accepted, mixedCountries.Status);
        Assert.Equal(MatchReasonCodes.ExcludedGenre, excludedGenre.ReasonCode);
        Assert.Equal(MatchDecisionStatus.Rejected, excludedGenre.Status);
    }

    [Fact]
    public void ManualMappingBypassesTypeAndYearButStillHonorsExclusions()
    {
        var accepted = MatchPolicy.Evaluate(
            "movie",
            "series",
            sourceYear: 1990,
            resolvedYear: 2024,
            manualMapping: true);
        var excluded = MatchPolicy.Evaluate(
            "movie",
            "series",
            countries: new[] { "Russia" },
            excludedCountries: new[] { "Russia" },
            manualMapping: true);

        Assert.Equal(MatchDecisionStatus.Accepted, accepted.Status);
        Assert.Equal(MatchReasonCodes.ManualMappingBypass, accepted.ReasonCode);
        Assert.Equal(MatchDecisionStatus.Rejected, excluded.Status);
        Assert.Equal(MatchReasonCodes.ExcludedCountry, excluded.ReasonCode);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("N/A")]
    [InlineData("unknown")]
    [InlineData("2015-2007")]
    [InlineData("2150-")]
    public void MalformedBroadcastRangesAreUnavailable(string? rawRange)
    {
        Assert.Null(BroadcastRange.Parse(rawRange));
    }

    [Fact]
    public void SingleYearBroadcastRangeIsClosed()
    {
        var range = Assert.IsType<BroadcastRange>(BroadcastRange.Parse("2012"));

        Assert.Equal(2012, range.StartYear);
        Assert.Equal(2012, range.EndYear);
        Assert.True(range.Contains(2012));
        Assert.False(range.Contains(2013));
    }
}