using System.Net;
using System.Net.Http;

namespace MediaDock.Infrastructure.Rss;

public static class RssFeedHttpClientFactory
{
    public static HttpClient Create(IRssDnsResolver? dnsResolver = null)
    {
        var resolver = dnsResolver ?? new SystemRssDnsResolver();
        var handler = new SocketsHttpHandler
        {
            AllowAutoRedirect = false,
            AutomaticDecompression = DecompressionMethods.All,
            ConnectTimeout = RssFeedTransport.DefaultConnectTimeout,
            ConnectCallback = (context, cancellationToken) =>
                RssFeedAddressPolicy.ConnectAsync(context, resolver, cancellationToken)
        };

        return new HttpClient(handler)
        {
            Timeout = Timeout.InfiniteTimeSpan
        };
    }
}