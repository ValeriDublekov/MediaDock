using System.Net;
using System.Text;
using System.Text.Json;
using MediaDock.Application.Ingestion;
using MediaDock.Application.Metadata;
using MediaDock.Infrastructure.Ingestion;
using MediaDock.Infrastructure.Metadata;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using MediaDock.Infrastructure.Rss;
using Microsoft.EntityFrameworkCore;
using Testcontainers.PostgreSql;

namespace MediaDock.IntegrationTests;

[Trait("Category", "Ingestion")]
public sealed class IngestionTests
{
    private const string FakeApiKey = "integration-test-only-key";
    private const string SuccessfulFeedUrl = "https://feed.rutracker.cc/success.atom";
    private const string PartialFeedUrl = "https://feed.rutracker.cc/partial.atom";

    [Fact]
    public async Task ScanIsIdempotentCachesConfirmedNegativeAndContinuesAfterEntryAndProviderFailures()
    {
        await using var postgres = new PostgreSqlBuilder()
            .WithImage("postgres:17-alpine")
            .WithDatabase("mediadock_ingestion_test")
            .WithUsername("mediadock")
            .WithPassword("mediadock_test")
            .Build();
        await postgres.StartAsync();

        var options = new DbContextOptionsBuilder<MediaDockDbContext>()
            .UseNpgsql(postgres.GetConnectionString())
            .Options;
        await using var db = new MediaDockDbContext(options);
        await db.Database.MigrateAsync();
        db.Sources.Add(new Source
        {
            StableKey = "movies-main",
            Name = "Movies",
            FeedType = "movie",
            Url = SuccessfulFeedUrl
        });
        await db.SaveChangesAsync();

        var handler = new MockProviderHandler();
        using var httpClient = new HttpClient(handler)
        {
            Timeout = Timeout.InfiniteTimeSpan
        };
        var rssTransport = new RssFeedTransport(httpClient, new PublicDnsResolver());
        var service = CreateService(db, httpClient, rssTransport);

        var first = await service.RunAsync();
        Assert.Equal("succeeded", first.Summary.Status);
        Assert.Equal(1, first.Summary.TitlesCreated);
        Assert.Equal(1, first.Summary.OccurrencesCreated);
        Assert.Equal(3, first.Summary.OmdbRequests);
        Assert.Equal(1, await db.Titles.CountAsync());
        Assert.Equal(1, await db.Occurrences.CountAsync());
        Assert.Contains(await db.MetadataCache.ToListAsync(), entry => entry.Status == "confirmed_not_found");

        var repeated = await service.RunAsync();
        Assert.Equal("succeeded", repeated.Summary.Status);
        Assert.Equal(0, repeated.Summary.TitlesCreated);
        Assert.Equal(0, repeated.Summary.OccurrencesCreated);
        Assert.Equal(2, repeated.Summary.CacheHits);
        Assert.Equal(3, handler.OmdbRequestCount);
        Assert.Equal(1, await db.Titles.CountAsync());
        Assert.Equal(1, await db.Occurrences.CountAsync());

        var source = await db.Sources.SingleAsync();
        source.Url = PartialFeedUrl;
        await db.SaveChangesAsync();

        var partial = await service.RunAsync();
        Assert.Equal("partial", partial.Summary.Status);
        Assert.Equal(3, partial.Summary.EntriesSeen);
        Assert.Equal(2, partial.Summary.ErrorCount);
        Assert.Equal(1, partial.Summary.OccurrencesCreated);
        Assert.Equal(1, partial.Summary.OmdbRequests);
        Assert.Equal(4, handler.OmdbRequestCount);
        Assert.Equal(2, await db.Occurrences.CountAsync());
        Assert.DoesNotContain(await db.MetadataCache.ToListAsync(), entry => entry.LookupTitle == "temporary film");

        var retried = await service.RunAsync();
        Assert.Equal("partial", retried.Summary.Status);
        Assert.Equal(1, retried.Summary.TitlesCreated);
        Assert.Equal(1, retried.Summary.OccurrencesCreated);
        Assert.Equal(5, handler.OmdbRequestCount);
        Assert.Equal(2, await db.Titles.CountAsync());
        Assert.Equal(3, await db.Occurrences.CountAsync());
        Assert.Contains(await db.MetadataCache.ToListAsync(), entry => entry.LookupTitle == "temporary film" && entry.Status == "found");

        var logs = await db.ParseLogs.OrderBy(log => log.Id).ToListAsync();
        Assert.Contains(logs, log => log.IgnoreReason == "malformed_entry");
        Assert.Contains(logs, log => log.OmdbStatus == "provider_error");
        Assert.All(logs, log => Assert.True(log.RawTitle.Length <= 1000));
        Assert.DoesNotContain(logs, log => log.RawTitle.Contains(FakeApiKey, StringComparison.Ordinal));
    }

    private static RssIngestionService CreateService(
        MediaDockDbContext db,
        HttpClient httpClient,
        RssFeedTransport rssTransport)
    {
        var client = new OmdbClient(httpClient, FakeApiKey, TimeSpan.FromSeconds(2));
        var cache = new PostgresMetadataCacheStore(db);
        var resolver = new MetadataResolver(client, cache);
        return new RssIngestionService(
            new PostgresRssIngestionRepository(db),
            new RssFeedTransportAdapter(rssTransport),
            resolver);
    }

    private sealed class MockProviderHandler : HttpMessageHandler
    {
        private int _temporaryRequests;

        public int OmdbRequestCount { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var uri = request.RequestUri!;
            if (uri.Host == RssFeedTransport.AllowedFeedHost)
            {
                return Task.FromResult(FeedResponse(uri.AbsolutePath == "/success.atom" ? SuccessfulFeed : PartialFeed));
            }

            if (uri.Host != "www.omdbapi.com")
            {
                throw new InvalidOperationException("Unexpected test HTTP host.");
            }

            OmdbRequestCount++;
            var query = ParseQuery(uri.Query);
            if (query["t"] == "The Matrix")
            {
                return Task.FromResult(JsonResponse(MoviePayload("The Matrix", "1999", "tt0133093")));
            }

            if (query["t"] == "Unknown Film")
            {
                return Task.FromResult(JsonResponse("""{"Response":"False","Error":"Movie not found!"}"""));
            }

            if (query["t"] == "Temporary Film")
            {
                _temporaryRequests++;
                if (_temporaryRequests == 1)
                {
                    return Task.FromResult(new HttpResponseMessage(HttpStatusCode.ServiceUnavailable));
                }

                return Task.FromResult(JsonResponse(MoviePayload("Temporary Film", "2020", "tt9876543")));
            }

            throw new InvalidOperationException("Unexpected OMDb lookup in the test.");
        }

        private static string SuccessfulFeed => """
            <?xml version="1.0" encoding="utf-8"?>
            <rss version="2.0"><channel>
              <item><title>The Matrix (1999) [1080p]</title><link>https://rutracker.org/forum/viewtopic.php?t=1</link><guid>matrix-1</guid></item>
              <item><title>Unknown Film (2024) [1080p]</title><link>https://rutracker.org/forum/viewtopic.php?t=2</link><guid>unknown-1</guid></item>
            </channel></rss>
            """;

        private static string PartialFeed => """
            <?xml version="1.0" encoding="utf-8"?>
            <rss version="2.0"><channel>
              <item><title>malformed apikey=integration-test-only-key</title><guid>bad-1</guid></item>
              <item><title>Temporary Film (2020) [1080p]</title><link>https://rutracker.org/forum/viewtopic.php?t=3</link><guid>temporary-1</guid></item>
              <item><title>The Matrix (1999) [2160p]</title><link>https://rutracker.org/forum/viewtopic.php?t=4</link><guid>matrix-2</guid></item>
            </channel></rss>
            """;

        private static string MoviePayload(string title, string year, string imdbId) =>
            JsonSerializer.Serialize(new
            {
                Response = "True",
                Title = title,
                Year = year,
                imdbID = imdbId,
                Type = "movie",
                imdbRating = "8.7",
                imdbVotes = "1,234",
                Metascore = "73",
                Genre = "Action, Sci-Fi",
                Country = "USA",
                Director = "Example Director",
                Plot = "Example plot",
                Poster = "https://example.test/poster.jpg",
                Runtime = "120 min",
                Awards = "None",
                BoxOffice = "$100"
            });

        private static HttpResponseMessage FeedResponse(string feed) => new(HttpStatusCode.OK)
        {
            Content = new StringContent(feed, Encoding.UTF8, "application/rss+xml")
        };

        private static HttpResponseMessage JsonResponse(string json) => new(HttpStatusCode.OK)
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json")
        };

        private static Dictionary<string, string> ParseQuery(string query) => query
            .TrimStart('?')
            .Split('&', StringSplitOptions.RemoveEmptyEntries)
            .Select(part => part.Split('=', 2))
            .ToDictionary(
                pair => Uri.UnescapeDataString(pair[0]),
                pair => pair.Length > 1 ? Uri.UnescapeDataString(pair[1]) : string.Empty,
                StringComparer.Ordinal);
    }

    private sealed class PublicDnsResolver : IRssDnsResolver
    {
        public Task<IPAddress[]> ResolveAsync(string hostname, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return Task.FromResult(new[] { IPAddress.Parse("8.8.8.8") });
        }
    }
}