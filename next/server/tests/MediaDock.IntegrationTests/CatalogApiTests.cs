using System.Net;
using System.Net.Http.Json;
using MediaDock.Api.Catalog;
using MediaDock.Api.Common;
using MediaDock.Api.Health;
using MediaDock.Api.Operations;
using MediaDock.Api.Sources;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;

namespace MediaDock.IntegrationTests;

[Trait("Category", "Api")]
public sealed class CatalogApiTests
{
    [Fact]
    public async Task CatalogApiValidatesPaginatesAndQueriesPostgresBackedResources()
    {
        await using var postgres = PostgreSqlTestContainerBuilder.Create("mediadock_api_test").Build();
        await postgres.StartAsync();

        var connectionString = postgres.GetConnectionString();
        var dbOptions = new DbContextOptionsBuilder<MediaDockDbContext>()
            .UseNpgsql(connectionString)
            .Options;
        await using var db = new MediaDockDbContext(dbOptions);
        await db.Database.MigrateAsync();

        using var factory = new ApiFactory(connectionString);
        using var client = factory.CreateClient();

        using var liveResponse = await client.GetAsync("/health/live");
        Assert.Equal(HttpStatusCode.OK, liveResponse.StatusCode);
        Assert.Equal("ok", (await liveResponse.Content.ReadFromJsonAsync<HealthResponse>())?.Status);

        using var readyResponse = await client.GetAsync("/health/ready");
        Assert.Equal(HttpStatusCode.OK, readyResponse.StatusCode);

        using var openApiResponse = await client.GetAsync("/openapi/v1.json");
        Assert.Equal(HttpStatusCode.OK, openApiResponse.StatusCode);
        Assert.Contains("/api/catalog", await openApiResponse.Content.ReadAsStringAsync(), StringComparison.Ordinal);

        using var emptyResponse = await client.GetAsync("/api/catalog");
        Assert.Equal(HttpStatusCode.OK, emptyResponse.StatusCode);
        var emptyCatalog = await emptyResponse.Content.ReadFromJsonAsync<PageResponse<CatalogTitleResponse>>();
        Assert.NotNull(emptyCatalog);
        Assert.Empty(emptyCatalog.Items);
        Assert.Equal(0, emptyCatalog.TotalCount);

        using var invalidPageResponse = await client.GetAsync("/api/catalog?page=0&pageSize=25");
        Assert.Equal(HttpStatusCode.BadRequest, invalidPageResponse.StatusCode);
        Assert.Equal("application/problem+json", invalidPageResponse.Content.Headers.ContentType?.MediaType);
        var invalidPageProblem = await invalidPageResponse.Content.ReadFromJsonAsync<ValidationProblemDetails>();
        Assert.NotNull(invalidPageProblem);
        Assert.NotEmpty(invalidPageProblem.Errors);

        var source = new Source
        {
            StableKey = "movies-main",
            Name = "Movies",
            FeedType = "movie",
            Url = "https://feed.rutracker.cc/movies.atom",
            IsEnabled = true
        };
        var olderTitle = CreateTitle("The Matrix", "the matrix", 1999, "movie", ["Action", "Sci-Fi"]);
        var newerTitle = CreateTitle("The Matrix Reloaded", "the matrix reloaded", 2003, "movie", ["Action", "Sci-Fi"]);
        var seriesTitle = CreateTitle("Example Series", "example series", 2010, "series", ["Drama"]);
        db.Sources.Add(source);
        db.Titles.AddRange(olderTitle, newerTitle, seriesTitle);
        await db.SaveChangesAsync();

        var firstSeen = new DateTimeOffset(2024, 1, 1, 0, 0, 0, TimeSpan.Zero);
        db.Occurrences.AddRange(
            CreateOccurrence(olderTitle.Id, source.Id, "matrix-1999", "The Matrix (1999)", firstSeen),
            CreateOccurrence(newerTitle.Id, source.Id, "matrix-2003", "The Matrix Reloaded (2003)", firstSeen.AddDays(1)));
        db.ParseLogs.AddRange(
            new ParseLog
            {
                SourceId = source.Id,
                SourceItemKey = "matrix-1999",
                RawTitle = "The Matrix (1999)",
                FeedName = "Movies",
                ParsedSuccessfully = true,
                ParsedTitle = "The Matrix",
                ParsedYear = 1999,
                OmdbStatus = "found",
                Ignored = false,
                ProcessedAt = firstSeen,
                RetryState = "resolved"
            },
            new ParseLog
            {
                SourceId = source.Id,
                SourceItemKey = "bad-entry",
                RawTitle = "Malformed entry",
                FeedName = "Movies",
                ParsedSuccessfully = false,
                OmdbStatus = "not_requested",
                Ignored = true,
                IgnoreReason = "malformed_entry",
                ProcessedAt = firstSeen.AddMinutes(1),
                RetryState = "terminal"
            });
        db.ScanRuns.Add(new ScanRun
        {
            StartedAt = firstSeen,
            FinishedAt = firstSeen.AddMinutes(1),
            Status = "succeeded",
            Trigger = "local",
            FeedsProcessed = 1,
            EntriesSeen = 2
        });
        await db.SaveChangesAsync();

        using var catalogResponse = await client.GetAsync(
            "/api/catalog?page=1&pageSize=1&search=matrix&mediaType=movie&yearFrom=1990&yearTo=2005&genre=Sci-Fi&country=USA");
        Assert.Equal(HttpStatusCode.OK, catalogResponse.StatusCode);
        var firstPage = await catalogResponse.Content.ReadFromJsonAsync<PageResponse<CatalogTitleResponse>>();
        Assert.NotNull(firstPage);
        Assert.Equal(2, firstPage.TotalCount);
        Assert.Equal(2, firstPage.TotalPages);
        Assert.Equal("The Matrix Reloaded", Assert.Single(firstPage.Items).Title);

        using var secondPageResponse = await client.GetAsync(
            "/api/catalog?page=2&pageSize=1&search=matrix&mediaType=movie");
        var secondPage = await secondPageResponse.Content.ReadFromJsonAsync<PageResponse<CatalogTitleResponse>>();
        Assert.NotNull(secondPage);
        Assert.Equal("The Matrix", Assert.Single(secondPage.Items).Title);

        using var reversedYearsResponse = await client.GetAsync("/api/catalog?yearFrom=2005&yearTo=1999");
        Assert.Equal(HttpStatusCode.BadRequest, reversedYearsResponse.StatusCode);
        Assert.NotNull(await reversedYearsResponse.Content.ReadFromJsonAsync<ValidationProblemDetails>());

        using var titleResponse = await client.GetAsync($"/api/titles/{olderTitle.Id}");
        var titleDetails = await titleResponse.Content.ReadFromJsonAsync<TitleDetailsResponse>();
        Assert.NotNull(titleDetails);
        Assert.Equal("The Matrix", titleDetails.Title);
        Assert.Equal(1, titleDetails.OccurrenceCount);

        using var missingTitleResponse = await client.GetAsync("/api/titles/999999");
        Assert.Equal(HttpStatusCode.NotFound, missingTitleResponse.StatusCode);
        Assert.NotNull(await missingTitleResponse.Content.ReadFromJsonAsync<ProblemDetails>());

        using var occurrencesResponse = await client.GetAsync($"/api/titles/{olderTitle.Id}/occurrences?page=1&pageSize=10");
        var occurrences = await occurrencesResponse.Content.ReadFromJsonAsync<PageResponse<OccurrenceResponse>>();
        Assert.NotNull(occurrences);
        Assert.Equal(1, occurrences.TotalCount);
        Assert.Equal("Movies", Assert.Single(occurrences.Items).SourceName);

        using var sourcesResponse = await client.GetAsync("/api/sources");
        var sources = await sourcesResponse.Content.ReadFromJsonAsync<List<SourceResponse>>();
        Assert.NotNull(sources);
        Assert.Equal("movies-main", Assert.Single(sources).StableKey);

        using var updateSourceResponse = await client.PutAsJsonAsync($"/api/sources/{source.Id}", new UpdateSourceRequest
        {
            StableKey = "movies-main",
            Name = "Main Movies",
            FeedType = "movie",
            Url = "https://feed.rutracker.cc/movies.atom",
            IsEnabled = false
        });
        Assert.Equal(HttpStatusCode.OK, updateSourceResponse.StatusCode);
        Assert.Equal("Main Movies", (await updateSourceResponse.Content.ReadFromJsonAsync<SourceResponse>())?.Name);

        using var createdSourceResponse = await client.PostAsJsonAsync("/api/sources", new CreateSourceRequest
        {
            StableKey = "series-feed",
            Name = "Series",
            FeedType = "series",
            Url = "https://feed.rutracker.cc/series.atom"
        });
        Assert.Equal(HttpStatusCode.Created, createdSourceResponse.StatusCode);
        Assert.NotNull(createdSourceResponse.Headers.Location);

        using var invalidSourceResponse = await client.PostAsJsonAsync("/api/sources", new CreateSourceRequest
        {
            StableKey = "unsafe-feed",
            Name = "Unsafe",
            FeedType = "movie",
            Url = "https://example.test/feed.atom"
        });
        Assert.Equal(HttpStatusCode.BadRequest, invalidSourceResponse.StatusCode);
        Assert.NotNull(await invalidSourceResponse.Content.ReadFromJsonAsync<ValidationProblemDetails>());

        using var duplicateSourceResponse = await client.PostAsJsonAsync("/api/sources", new CreateSourceRequest
        {
            StableKey = "movies-main",
            Name = "Duplicate",
            FeedType = "movie",
            Url = "https://feed.rutracker.cc/movies.atom"
        });
        Assert.Equal(HttpStatusCode.Conflict, duplicateSourceResponse.StatusCode);
        Assert.NotNull(await duplicateSourceResponse.Content.ReadFromJsonAsync<ProblemDetails>());

        using var settingsResponse = await client.GetAsync("/api/settings");
        var defaultSettings = await settingsResponse.Content.ReadFromJsonAsync<SettingsResponse>();
        Assert.NotNull(defaultSettings);
        Assert.Empty(defaultSettings.ExcludedGenres);
        Assert.Null(defaultSettings.UpdatedAt);

        using var updateSettingsResponse = await client.PutAsJsonAsync("/api/settings", new UpdateSettingsRequest
        {
            ExcludedGenres = ["Horror"],
            ExcludedCountries = ["USA"],
            MinMovieRating = 6.5m,
            MinSeriesRating = 7m,
            MinImdbVotes = 1000
        });
        Assert.Equal(HttpStatusCode.OK, updateSettingsResponse.StatusCode);
        Assert.Equal(6.5m, (await updateSettingsResponse.Content.ReadFromJsonAsync<SettingsResponse>())?.MinMovieRating);

        using var invalidSettingsResponse = await client.PutAsJsonAsync("/api/settings", new UpdateSettingsRequest
        {
            MinMovieRating = 11,
            MinSeriesRating = 0,
            MinImdbVotes = 0
        });
        Assert.Equal(HttpStatusCode.BadRequest, invalidSettingsResponse.StatusCode);
        Assert.NotNull(await invalidSettingsResponse.Content.ReadFromJsonAsync<ValidationProblemDetails>());

        using var defaultProviderSettingsResponse = await client.GetAsync("/api/settings/providers/omdb");
        var defaultProviderSettings = await defaultProviderSettingsResponse.Content
            .ReadFromJsonAsync<ProviderSettingsResponse>();
        Assert.NotNull(defaultProviderSettings);
        Assert.False(defaultProviderSettings.OmdbApiKeyConfigured);

        using var invalidProviderSettingsResponse = await client.PutAsJsonAsync(
            "/api/settings/providers/omdb",
            new UpdateProviderSettingsRequest
            {
                OmdbApiKey = "test-omdb-key-value",
                OscarEnrichmentMaxFilmsPerRun = 5
            });
        Assert.Equal(HttpStatusCode.BadRequest, invalidProviderSettingsResponse.StatusCode);
        Assert.NotNull(await invalidProviderSettingsResponse.Content.ReadFromJsonAsync<ValidationProblemDetails>());

        const string testOmdbApiKey = "test-omdb-key-value";
        using var updateProviderSettingsResponse = await client.PutAsJsonAsync(
            "/api/settings/providers/omdb",
            new UpdateProviderSettingsRequest
            {
                OmdbApiKey = testOmdbApiKey,
                OmdbDailyRequestLimit = 20,
                OscarEnrichmentMaxFilmsPerRun = 5,
                OscarEnrichmentMaxRequestsPerDay = 8
            });
        Assert.Equal(HttpStatusCode.OK, updateProviderSettingsResponse.StatusCode);
        var providerSettingsJson = await updateProviderSettingsResponse.Content.ReadAsStringAsync();
        Assert.DoesNotContain(testOmdbApiKey, providerSettingsJson);
        var savedProviderSettings = await updateProviderSettingsResponse.Content
            .ReadFromJsonAsync<ProviderSettingsResponse>();
        Assert.NotNull(savedProviderSettings);
        Assert.True(savedProviderSettings.OmdbApiKeyConfigured);
        Assert.Equal(20, savedProviderSettings.OmdbDailyRequestLimit);
        Assert.Equal(5, savedProviderSettings.OscarEnrichmentMaxFilmsPerRun);
        Assert.Equal(8, savedProviderSettings.OscarEnrichmentMaxRequestsPerDay);

        db.ChangeTracker.Clear();
        var providerSettingsInDatabase = await db.Settings.AsNoTracking().SingleAsync();
        Assert.Equal(1, providerSettingsInDatabase.Id);
        Assert.Equal(testOmdbApiKey, providerSettingsInDatabase.OmdbApiKey);

        using var clearProviderSettingsResponse = await client.PutAsJsonAsync(
            "/api/settings/providers/omdb",
            new UpdateProviderSettingsRequest
            {
                ClearOmdbApiKey = true,
                OmdbDailyRequestLimit = 20,
                OscarEnrichmentMaxFilmsPerRun = 5,
                OscarEnrichmentMaxRequestsPerDay = 8
            });
        Assert.Equal(HttpStatusCode.OK, clearProviderSettingsResponse.StatusCode);
        Assert.False((await clearProviderSettingsResponse.Content
            .ReadFromJsonAsync<ProviderSettingsResponse>())?.OmdbApiKeyConfigured);

        using var logsResponse = await client.GetAsync("/api/parse-logs?page=1&pageSize=1&ignored=true");
        var logs = await logsResponse.Content.ReadFromJsonAsync<PageResponse<ParseLogResponse>>();
        Assert.NotNull(logs);
        Assert.Equal(1, logs.TotalCount);
        Assert.True(Assert.Single(logs.Items).Ignored);

        using var runsResponse = await client.GetAsync("/api/scan-runs?page=1&pageSize=10&status=succeeded");
        var runs = await runsResponse.Content.ReadFromJsonAsync<PageResponse<ScanRunResponse>>();
        Assert.NotNull(runs);
        Assert.Equal("succeeded", Assert.Single(runs.Items).Status);
    }

    private static Title CreateTitle(string title, string normalizedTitle, int year, string mediaType, string[] genres)
    {
        var seenAt = new DateTimeOffset(year, 1, 1, 0, 0, 0, TimeSpan.Zero);
        return new Title
        {
            TitleText = title,
            NormalizedTitle = normalizedTitle,
            Year = year,
            MediaType = mediaType,
            SourceType = mediaType,
            ContentKind = "standard",
            ImdbId = $"tt{year}",
            ImdbRating = 8.0m,
            ImdbVotes = 1000,
            Genres = genres,
            Countries = ["USA"],
            FirstSeenAt = seenAt,
            LastSeenAt = seenAt,
            UpdatedAt = seenAt
        };
    }

    private static Occurrence CreateOccurrence(
        long titleId,
        long sourceId,
        string sourceItemKey,
        string rawTitle,
        DateTimeOffset lastSeenAt) => new()
    {
        TitleId = titleId,
        SourceId = sourceId,
        SourceItemKey = sourceItemKey,
        TorrentUrl = "https://rutracker.org/forum/viewtopic.php?t=1",
        RawTitle = rawTitle,
        SourceFeedName = "Movies",
        FeedType = "movie",
        FirstSeenAt = lastSeenAt,
        LastSeenAt = lastSeenAt
    };

    private sealed class ApiFactory(string connectionString) : WebApplicationFactory<Program>
    {
        protected override void ConfigureWebHost(IWebHostBuilder builder)
        {
            builder.ConfigureAppConfiguration((_, configuration) =>
                configuration.AddInMemoryCollection(new Dictionary<string, string?>
                {
                    ["ConnectionStrings:MediaDock"] = connectionString
                }));
        }
    }
}