using MediaDock.Application.Ingestion;
using MediaDock.Infrastructure.Rss;

namespace MediaDock.Infrastructure.Ingestion;

public sealed class RssFeedTransportAdapter(RssFeedTransport transport) : IRssFeedTransport
{
    public Task<byte[]> FetchAsync(string url, CancellationToken cancellationToken = default) =>
        transport.FetchAsync(url, cancellationToken);
}