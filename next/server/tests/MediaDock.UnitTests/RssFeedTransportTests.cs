using System.Net;
using System.Text;
using MediaDock.Infrastructure.Rss;

namespace MediaDock.UnitTests;

[Trait("Category", "RssTransport")]
public sealed class RssFeedTransportTests
{
    private const string FeedUrl = "https://feed.rutracker.cc/feed.atom";
    private static readonly IPAddress PublicAddress = IPAddress.Parse("8.8.8.8");

    [Fact]
    public async Task FetchesWellFormedRssAndAtom()
    {
        foreach (var (body, mediaType) in new[]
        {
            ("<rss version='2.0'><channel><item /></channel></rss>", "application/rss+xml"),
            ("<feed xmlns='http://www.w3.org/2005/Atom'><entry /></feed>", "application/atom+xml")
        })
        {
            using var client = CreateClient(new FakeHttpHandler((_, _) =>
                Task.FromResult(FeedResponse(body, mediaType))));
            var transport = new RssFeedTransport(client, new FakeDnsResolver());

            var fetchedBody = await transport.FetchAsync(FeedUrl);

            Assert.Equal(Encoding.UTF8.GetBytes(body), fetchedBody);
        }
    }

    [Fact]
    public async Task RejectsInvalidSchemeHostAndCredentialsBeforeHttp()
    {
        var handler = new FakeHttpHandler((_, _) =>
            Task.FromResult(FeedResponse("<rss><channel /></rss>", "application/rss+xml")));
        using var client = CreateClient(handler);
        var dns = new FakeDnsResolver();
        var transport = new RssFeedTransport(client, dns);

        foreach (var url in new[]
        {
            "http://feed.rutracker.cc/feed.xml",
            "file:///feed.xml",
            "https://user:password@feed.rutracker.cc/feed.xml",
            "https://other.example.test/feed.xml",
            "https://feed.rutracker.cc/feed path.xml"
        })
        {
            await Assert.ThrowsAsync<RssFeedUrlException>(() => transport.FetchAsync(url));
        }

        Assert.Empty(handler.Requests);
        Assert.Empty(dns.Hosts);
    }

    [Fact]
    public async Task RejectsPrivateOrMixedDnsResultsBeforeHttp()
    {
        foreach (var addresses in new[]
        {
            new[] { IPAddress.Loopback },
            new[] { PublicAddress, IPAddress.Parse("10.1.2.3") },
            new[] { IPAddress.Parse("::ffff:127.0.0.1") }
        })
        {
            var handler = new FakeHttpHandler((_, _) =>
                Task.FromResult(FeedResponse("<rss><channel /></rss>", "application/rss+xml")));
            using var client = CreateClient(handler);
            var transport = new RssFeedTransport(client, new FakeDnsResolver(addresses));

            await Assert.ThrowsAsync<RssFeedDnsException>(() => transport.FetchAsync(FeedUrl));

            Assert.Empty(handler.Requests);
        }
    }

    [Fact]
    public async Task RevalidatesRedirectHostAndDnsBeforeFollowing()
    {
        var handler = new FakeHttpHandler((request, _) =>
        {
            if (request.RequestUri!.AbsolutePath == "/start.atom")
            {
                var redirect = new HttpResponseMessage(HttpStatusCode.Redirect);
                redirect.Headers.Location = new Uri("/next.atom", UriKind.Relative);
                return Task.FromResult(redirect);
            }

            return Task.FromResult(FeedResponse("<rss><channel /></rss>", "application/rss+xml"));
        });
        using var client = CreateClient(handler);
        var dns = new FakeDnsResolver(new[] { PublicAddress }, new[] { PublicAddress });
        var transport = new RssFeedTransport(client, dns);

        await transport.FetchAsync("https://feed.rutracker.cc/start.atom");

        Assert.Equal(2, handler.Requests.Count);
        Assert.Equal(new[] { "/start.atom", "/next.atom" }, handler.Requests.Select(uri => uri.AbsolutePath));
        Assert.Equal(2, dns.Hosts.Count);
    }

    [Fact]
    public async Task RejectsRedirectToDisallowedHostAndPrivateAddress()
    {
        var disallowedHandler = new FakeHttpHandler((_, _) =>
        {
            var redirect = new HttpResponseMessage(HttpStatusCode.Redirect);
            redirect.Headers.Location = new Uri("https://other.example.test/feed.xml");
            return Task.FromResult(redirect);
        });
        using (var client = CreateClient(disallowedHandler))
        {
            var transport = new RssFeedTransport(client, new FakeDnsResolver());
            await Assert.ThrowsAsync<RssFeedUrlException>(() => transport.FetchAsync(FeedUrl));
            Assert.Single(disallowedHandler.Requests);
        }

        var privateHandler = new FakeHttpHandler((_, _) =>
        {
            var redirect = new HttpResponseMessage(HttpStatusCode.Redirect);
            redirect.Headers.Location = new Uri("/private.xml", UriKind.Relative);
            return Task.FromResult(redirect);
        });
        using (var client = CreateClient(privateHandler))
        {
            var dns = new FakeDnsResolver(new[] { PublicAddress }, new[] { IPAddress.Parse("127.0.0.1") });
            var transport = new RssFeedTransport(client, dns);
            await Assert.ThrowsAsync<RssFeedDnsException>(() => transport.FetchAsync(FeedUrl));
            Assert.Single(privateHandler.Requests);
        }
    }

    [Fact]
    public async Task ConvertsRequestCancellationToTimeout()
    {
        var handler = new FakeHttpHandler(async (_, cancellationToken) =>
        {
            await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
            return FeedResponse("<rss><channel /></rss>", "application/rss+xml");
        });
        using var client = CreateClient(handler);
        var transport = new RssFeedTransport(
            client,
            new FakeDnsResolver(),
            requestTimeout: TimeSpan.FromMilliseconds(50));

        await Assert.ThrowsAsync<RssFeedTimeoutException>(() => transport.FetchAsync(FeedUrl));
    }

    [Fact]
    public async Task EnforcesResponseBodyLimit()
    {
        using var client = CreateClient(new FakeHttpHandler((_, _) =>
            Task.FromResult(FeedResponse("123456", "application/rss+xml"))));
        var transport = new RssFeedTransport(
            client,
            new FakeDnsResolver(),
            maxResponseBytes: 5);

        await Assert.ThrowsAsync<RssFeedSizeLimitException>(() => transport.FetchAsync(FeedUrl));
    }

    [Fact]
    public async Task RejectsMalformedFeedsAndEntryAmplification()
    {
        foreach (var body in new[] { "<rss><channel>", "<html />", "<rss />" })
        {
            using var client = CreateClient(new FakeHttpHandler((_, _) =>
                Task.FromResult(FeedResponse(body, "application/rss+xml"))));
            var transport = new RssFeedTransport(client, new FakeDnsResolver());

            await Assert.ThrowsAsync<RssFeedFormatException>(() => transport.FetchAsync(FeedUrl));
        }

        using var oversizedClient = CreateClient(new FakeHttpHandler((_, _) =>
            Task.FromResult(FeedResponse(
                "<rss><channel><item /><item /></channel></rss>",
                "application/rss+xml"))));
        var limitedTransport = new RssFeedTransport(
            oversizedClient,
            new FakeDnsResolver(),
            maxEntries: 1);

        await Assert.ThrowsAsync<RssFeedEntryLimitException>(() => limitedTransport.FetchAsync(FeedUrl));
    }

    private static HttpClient CreateClient(HttpMessageHandler handler) =>
        new(handler, disposeHandler: true) { Timeout = Timeout.InfiniteTimeSpan };

    private static HttpResponseMessage FeedResponse(string body, string mediaType) =>
        new(HttpStatusCode.OK)
        {
            Content = new StringContent(body, Encoding.UTF8, mediaType)
        };

    private sealed class FakeHttpHandler(
        Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> send) : HttpMessageHandler
    {
        public List<Uri> Requests { get; } = [];

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            Requests.Add(request.RequestUri!);
            return send(request, cancellationToken);
        }
    }

    private sealed class FakeDnsResolver : IRssDnsResolver
    {
        private readonly Queue<IPAddress[]> _answers;

        public FakeDnsResolver(params IPAddress[][] answers)
        {
            _answers = new Queue<IPAddress[]>(answers);
        }

        public List<string> Hosts { get; } = [];

        public Task<IPAddress[]> ResolveAsync(string hostname, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Hosts.Add(hostname);
            return Task.FromResult(_answers.Count > 0 ? _answers.Dequeue() : new[] { PublicAddress });
        }
    }
}