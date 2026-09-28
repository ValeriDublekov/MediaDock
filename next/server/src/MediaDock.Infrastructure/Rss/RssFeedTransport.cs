using System.Net;
using System.Net.Http.Headers;

namespace MediaDock.Infrastructure.Rss;

public sealed class RssFeedTransport
{
    public const string AllowedFeedHost = "feed.rutracker.cc";
    public static readonly TimeSpan DefaultConnectTimeout = TimeSpan.FromSeconds(5);
    public static readonly TimeSpan DefaultRequestTimeout = TimeSpan.FromSeconds(20);
    public const int DefaultMaxResponseBytes = 4 * 1024 * 1024;
    public const int DefaultMaxEntries = 500;
    public const int DefaultMaxRedirects = 3;

    private static readonly HashSet<string> AllowedContentTypes = new(StringComparer.OrdinalIgnoreCase)
    {
        "application/atom+xml",
        "application/rdf+xml",
        "application/rss+xml",
        "application/xml",
        "text/atom",
        "text/rss",
        "text/xml"
    };

    private readonly HttpClient _httpClient;
    private readonly IRssDnsResolver _dnsResolver;
    private readonly TimeSpan _requestTimeout;
    private readonly int _maxResponseBytes;
    private readonly int _maxEntries;
    private readonly int _maxRedirects;
    private readonly int _chunkSize;

    public RssFeedTransport(
        HttpClient httpClient,
        IRssDnsResolver? dnsResolver = null,
        TimeSpan? requestTimeout = null,
        int maxResponseBytes = DefaultMaxResponseBytes,
        int maxEntries = DefaultMaxEntries,
        int maxRedirects = DefaultMaxRedirects,
        int chunkSize = 64 * 1024)
    {
        ArgumentNullException.ThrowIfNull(httpClient);
        if ((requestTimeout ?? DefaultRequestTimeout) <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(nameof(requestTimeout));
        }

        if (maxResponseBytes <= 0 || maxEntries <= 0 || maxRedirects < 0 || chunkSize <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maxResponseBytes), "Feed bounds must be positive.");
        }

        _httpClient = httpClient;
        _dnsResolver = dnsResolver ?? new SystemRssDnsResolver();
        _requestTimeout = requestTimeout ?? DefaultRequestTimeout;
        _maxResponseBytes = maxResponseBytes;
        _maxEntries = maxEntries;
        _maxRedirects = maxRedirects;
        _chunkSize = chunkSize;
    }

    public async Task<byte[]> FetchAsync(string url, CancellationToken cancellationToken = default)
    {
        var currentUri = ValidateUrl(url);
        using var timeoutSource = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutSource.CancelAfter(_requestTimeout);

        try
        {
            for (var redirectCount = 0; redirectCount <= _maxRedirects; redirectCount++)
            {
                await RssFeedAddressPolicy.ResolvePublicAddressesAsync(
                    _dnsResolver,
                    NormalizeHost(currentUri),
                    timeoutSource.Token);

                using var request = new HttpRequestMessage(HttpMethod.Get, currentUri);
                request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/rss+xml"));
                request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/atom+xml"));
                request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/xml"));

                using var response = await _httpClient.SendAsync(
                    request,
                    HttpCompletionOption.ResponseHeadersRead,
                    timeoutSource.Token);

                if (IsRedirect(response.StatusCode))
                {
                    if (redirectCount == _maxRedirects)
                    {
                        throw new RssFeedResponseException("feed redirect limit exceeded");
                    }

                    if (response.Headers.Location is not { } location
                        || !Uri.TryCreate(currentUri, location, out var redirectedUri))
                    {
                        throw new RssFeedResponseException("feed redirect has no valid location");
                    }

                    currentUri = ValidateUrl(redirectedUri.AbsoluteUri);
                    continue;
                }

                if ((int)response.StatusCode is < 200 or >= 300)
                {
                    throw new RssFeedResponseException("feed server returned a non-success status");
                }

                var contentType = response.Content.Headers.ContentType?.MediaType;
                if (contentType is null || !AllowedContentTypes.Contains(contentType))
                {
                    throw new RssFeedResponseException("feed server returned an unsupported content type");
                }

                var body = await ReadBoundedBodyAsync(response.Content, timeoutSource.Token);
                RssFeedXmlValidator.Validate(body, _maxEntries);
                return body;
            }
        }
        catch (OperationCanceledException exception) when (!cancellationToken.IsCancellationRequested)
        {
            throw new RssFeedTimeoutException("feed request timed out", exception);
        }
        catch (HttpRequestException exception)
        {
            throw new RssFeedResponseException("feed request failed", exception);
        }

        throw new RssFeedResponseException("feed redirect limit exceeded");
    }

    private async Task<byte[]> ReadBoundedBodyAsync(HttpContent content, CancellationToken cancellationToken)
    {
        await using var stream = await content.ReadAsStreamAsync(cancellationToken);
        using var output = new MemoryStream();
        var buffer = new byte[Math.Min(_chunkSize, _maxResponseBytes)];

        while (true)
        {
            var remainingBytes = _maxResponseBytes - output.Length;
            var readLimit = (int)Math.Min(buffer.Length, remainingBytes + 1);
            var bytesRead = await stream.ReadAsync(buffer.AsMemory(0, readLimit), cancellationToken);
            if (bytesRead == 0)
            {
                break;
            }

            if (bytesRead > remainingBytes)
            {
                throw new RssFeedSizeLimitException("decompressed feed response exceeded the byte limit");
            }

            output.Write(buffer, 0, bytesRead);
        }

        if (output.Length == 0)
        {
            throw new RssFeedResponseException("feed response body is empty");
        }

        return output.ToArray();
    }

    private static Uri ValidateUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url))
        {
            throw new RssFeedUrlException("feed URL must be a non-empty HTTPS URL");
        }

        var candidate = url.Trim();
        if (candidate.Length > 2048 || candidate.Any(char.IsWhiteSpace)
            || !Uri.TryCreate(candidate, UriKind.Absolute, out var uri)
            || !string.Equals(uri.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase)
            || !string.IsNullOrEmpty(uri.UserInfo)
            || !string.Equals(NormalizeHost(uri), AllowedFeedHost, StringComparison.Ordinal))
        {
            throw new RssFeedUrlException("feed URL is not allowed");
        }

        return uri;
    }

    private static string NormalizeHost(Uri uri) =>
        uri.IdnHost.TrimEnd('.').ToLowerInvariant();

    private static bool IsRedirect(HttpStatusCode statusCode) =>
        statusCode is HttpStatusCode.MovedPermanently
            or HttpStatusCode.Redirect
            or HttpStatusCode.RedirectMethod
            or HttpStatusCode.TemporaryRedirect
            or HttpStatusCode.PermanentRedirect;
}