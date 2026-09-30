using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json;
using MediaDock.Application.Matching;
using MediaDock.Application.Metadata;

namespace MediaDock.Infrastructure.Metadata;

public sealed class OmdbClient : IOmdbClient
{
    private const string Endpoint = "https://www.omdbapi.com/";
    private const int DefaultMaximumResponseBytes = 1024 * 1024;

    private readonly HttpClient _httpClient;
    private readonly string _apiKey;
    private readonly TimeSpan _timeout;
    private readonly int _maximumResponseBytes;
    private readonly IOmdbRequestBudget? _requestBudget;
    private readonly int _dailyRequestLimit;
    private readonly int _oscarDailyRequestLimit;
    private readonly TimeProvider _timeProvider;

    public OmdbClient(
        HttpClient httpClient,
        string apiKey,
        TimeSpan? timeout = null,
        int maximumResponseBytes = DefaultMaximumResponseBytes,
        IOmdbRequestBudget? requestBudget = null,
        int dailyRequestLimit = int.MaxValue,
        int oscarDailyRequestLimit = int.MaxValue,
        TimeProvider? timeProvider = null)
    {
        ArgumentNullException.ThrowIfNull(httpClient);
        if (string.IsNullOrWhiteSpace(apiKey))
        {
            throw new InvalidOperationException("OMDb API key is required on the server.");
        }

        if ((timeout ?? TimeSpan.FromSeconds(8)) <= TimeSpan.Zero || maximumResponseBytes <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(timeout));
        }

        if (requestBudget is not null && (dailyRequestLimit <= 0 || oscarDailyRequestLimit < 0))
        {
            throw new ArgumentOutOfRangeException(nameof(dailyRequestLimit));
        }

        _httpClient = httpClient;
        _apiKey = apiKey;
        _timeout = timeout ?? TimeSpan.FromSeconds(8);
        _maximumResponseBytes = maximumResponseBytes;
        _requestBudget = requestBudget;
        _dailyRequestLimit = dailyRequestLimit;
        _oscarDailyRequestLimit = oscarDailyRequestLimit;
        _timeProvider = timeProvider ?? TimeProvider.System;
    }

    public async Task<MetadataLookupResult> LookupAsync(
        string title,
        int? year,
        string sourceType,
        CancellationToken cancellationToken = default,
        OmdbRequestPurpose requestPurpose = OmdbRequestPurpose.RssIngestion)
    {
        if (string.IsNullOrWhiteSpace(title) || sourceType is not ("movie" or "series"))
        {
            return new MetadataLookupResult(MetadataLookupStatus.InvalidRequest, ErrorCode: "invalid_lookup");
        }

        var first = await RequestAsync(title.Trim(), year, sourceType, requestPurpose, cancellationToken);
        if (first.Status != MetadataLookupStatus.ConfirmedNotFound || year is null || sourceType == "series")
        {
            return first;
        }

        var fallback = await RequestAsync(title.Trim(), null, sourceType, requestPurpose, cancellationToken);
        return fallback with { HttpAttempts = first.HttpAttempts + fallback.HttpAttempts };
    }

    private async Task<MetadataLookupResult> RequestAsync(
        string title,
        int? year,
        string sourceType,
        OmdbRequestPurpose requestPurpose,
        CancellationToken cancellationToken)
    {
        var utcDate = DateOnly.FromDateTime(_timeProvider.GetUtcNow().UtcDateTime);
        if (_requestBudget is not null)
        {
            if (requestPurpose == OmdbRequestPurpose.OscarEnrichment && _oscarDailyRequestLimit == 0)
            {
                return new MetadataLookupResult(
                    MetadataLookupStatus.RequestBudgetExhausted,
                    ErrorCode: "daily_budget_exhausted");
            }

            var reserved = await _requestBudget.TryReserveAsync(
                utcDate,
                requestPurpose,
                _dailyRequestLimit,
                _oscarDailyRequestLimit,
                cancellationToken);
            if (!reserved)
            {
                return new MetadataLookupResult(
                    MetadataLookupStatus.RequestBudgetExhausted,
                    ErrorCode: "daily_budget_exhausted");
            }
        }

        var query = new StringBuilder()
            .Append("apikey=").Append(Uri.EscapeDataString(_apiKey))
            .Append("&t=").Append(Uri.EscapeDataString(title))
            .Append("&type=").Append(Uri.EscapeDataString(sourceType));
        if (year is not null && sourceType != "series")
        {
            query.Append("&y=").Append(year.Value.ToString(CultureInfo.InvariantCulture));
        }

        using var request = new HttpRequestMessage(HttpMethod.Get, Endpoint + "?" + query);
        using var timeoutSource = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutSource.CancelAfter(_timeout);

        try
        {
            using var response = await _httpClient.SendAsync(
                request,
                HttpCompletionOption.ResponseHeadersRead,
                timeoutSource.Token);
            if (response.StatusCode == HttpStatusCode.TooManyRequests)
            {
                await MarkProviderQuotaExceededAsync(utcDate, cancellationToken);
                return new MetadataLookupResult(MetadataLookupStatus.QuotaExceeded, HttpAttempts: 1, ErrorCode: "quota_exceeded");
            }

            if (response.StatusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden)
            {
                return new MetadataLookupResult(MetadataLookupStatus.AuthenticationFailure, HttpAttempts: 1, ErrorCode: "authentication_failed");
            }

            if ((int)response.StatusCode is < 200 or >= 300)
            {
                return new MetadataLookupResult(MetadataLookupStatus.ProviderFailure, HttpAttempts: 1, ErrorCode: "http_error");
            }

            var body = await ReadBoundedAsync(response.Content, timeoutSource.Token);
            var result = ParseResponse(body);
            if (result.Status == MetadataLookupStatus.QuotaExceeded)
            {
                await MarkProviderQuotaExceededAsync(utcDate, cancellationToken);
            }

            return result;
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            return new MetadataLookupResult(MetadataLookupStatus.TransportFailure, HttpAttempts: 1, ErrorCode: "timeout");
        }
        catch (HttpRequestException)
        {
            return new MetadataLookupResult(MetadataLookupStatus.TransportFailure, HttpAttempts: 1, ErrorCode: "transport_error");
        }
        catch (IOException)
        {
            return new MetadataLookupResult(MetadataLookupStatus.TransportFailure, HttpAttempts: 1, ErrorCode: "transport_error");
        }
        catch (JsonException)
        {
            return new MetadataLookupResult(MetadataLookupStatus.ProviderFailure, HttpAttempts: 1, ErrorCode: "invalid_response");
        }
        catch (InvalidDataException)
        {
            return new MetadataLookupResult(MetadataLookupStatus.ProviderFailure, HttpAttempts: 1, ErrorCode: "response_too_large");
        }
    }

    private async Task MarkProviderQuotaExceededAsync(DateOnly utcDate, CancellationToken cancellationToken)
    {
        if (_requestBudget is not null)
        {
            await _requestBudget.MarkProviderQuotaExceededAsync(utcDate, cancellationToken);
        }
    }

    private async Task<byte[]> ReadBoundedAsync(HttpContent content, CancellationToken cancellationToken)
    {
        if (content.Headers.ContentLength is > 0 and var contentLength && contentLength > _maximumResponseBytes)
        {
            throw new InvalidDataException("OMDb response exceeded the configured size limit.");
        }

        await using var input = await content.ReadAsStreamAsync(cancellationToken);
        using var output = new MemoryStream();
        var buffer = new byte[8192];
        while (true)
        {
            var bytesRead = await input.ReadAsync(buffer, cancellationToken);
            if (bytesRead == 0)
            {
                break;
            }

            if (output.Length + bytesRead > _maximumResponseBytes)
            {
                throw new InvalidDataException("OMDb response exceeded the configured size limit.");
            }

            output.Write(buffer, 0, bytesRead);
        }

        return output.ToArray();
    }

    private static MetadataLookupResult ParseResponse(byte[] body)
    {
        using var document = JsonDocument.Parse(body);
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object)
        {
            return new MetadataLookupResult(MetadataLookupStatus.ProviderFailure, HttpAttempts: 1, ErrorCode: "invalid_response");
        }

        var response = GetString(root, "Response");
        if (string.Equals(response, "False", StringComparison.OrdinalIgnoreCase))
        {
            var error = GetString(root, "Error") ?? string.Empty;
            var status = ClassifyError(error);
            return new MetadataLookupResult(status, HttpAttempts: 1, ErrorCode: ErrorCode(status));
        }

        if (!string.Equals(response, "True", StringComparison.OrdinalIgnoreCase))
        {
            return new MetadataLookupResult(MetadataLookupStatus.ProviderFailure, HttpAttempts: 1, ErrorCode: "invalid_response");
        }

        var title = GetString(root, "Title");
        if (string.IsNullOrWhiteSpace(title))
        {
            return new MetadataLookupResult(MetadataLookupStatus.ProviderFailure, HttpAttempts: 1, ErrorCode: "invalid_metadata");
        }

        var genres = SplitList(GetString(root, "Genre"));
        var countries = SplitList(GetString(root, "Country"));
        var classification = MatchPolicy.ClassifyMedia(GetString(root, "Type"), genres);
        var sourceType = classification.SourceType switch
        {
            SourceType.Movie => "movie",
            SourceType.Series => "series",
            _ => "unknown"
        };
        var contentKind = classification.ContentKind.ToString().ToLowerInvariant();
        var rawYear = GetString(root, "Year");
        var broadcastRange = sourceType == "series" ? BroadcastRange.Parse(rawYear) : null;
        var year = broadcastRange?.StartYear ?? ParseYear(rawYear);

        return new MetadataLookupResult(
            MetadataLookupStatus.Found,
            new MetadataDetails(
                title.Trim(),
                year,
                GetOptionalString(root, "imdbID"),
                classification.MediaType,
                sourceType,
                contentKind,
                broadcastRange,
                ParseDecimal(GetString(root, "imdbRating")),
                ParseLong(GetString(root, "imdbVotes")),
                ParseDecimal(GetString(root, "Metascore")),
                genres,
                countries,
                GetOptionalString(root, "Director"),
                GetOptionalString(root, "Plot"),
                GetOptionalString(root, "Poster"),
                GetOptionalString(root, "Runtime"),
                GetOptionalString(root, "Awards"),
                GetOptionalString(root, "BoxOffice")),
            1);
    }

    private static MetadataLookupStatus ClassifyError(string error)
    {
        var normalized = error.ToLowerInvariant();
        if (normalized.Contains("limit reached", StringComparison.Ordinal)
            || normalized.Contains("request limit", StringComparison.Ordinal))
        {
            return MetadataLookupStatus.QuotaExceeded;
        }

        if (normalized.Contains("invalid api key", StringComparison.Ordinal)
            || normalized.Contains("authentication", StringComparison.Ordinal)
            || normalized.Contains("unauthorized", StringComparison.Ordinal))
        {
            return MetadataLookupStatus.AuthenticationFailure;
        }

        if (normalized.Contains("not found", StringComparison.Ordinal)
            || normalized.Contains("not exist", StringComparison.Ordinal)
            || normalized.Contains("incorrect imdb id", StringComparison.Ordinal))
        {
            return MetadataLookupStatus.ConfirmedNotFound;
        }

        if (normalized.Contains("invalid request", StringComparison.Ordinal)
            || normalized.Contains("invalid parameter", StringComparison.Ordinal))
        {
            return MetadataLookupStatus.InvalidRequest;
        }

        return MetadataLookupStatus.ProviderFailure;
    }

    private static string ErrorCode(MetadataLookupStatus status) => status switch
    {
        MetadataLookupStatus.QuotaExceeded => "quota_exceeded",
        MetadataLookupStatus.AuthenticationFailure => "authentication_failed",
        MetadataLookupStatus.ConfirmedNotFound => "not_found",
        MetadataLookupStatus.InvalidRequest => "invalid_request",
        _ => "provider_error"
    };

    private static string? GetString(JsonElement element, string propertyName) =>
        element.TryGetProperty(propertyName, out var property) && property.ValueKind == JsonValueKind.String
            ? property.GetString()
            : null;

    private static string? GetOptionalString(JsonElement element, string propertyName)
    {
        var value = GetString(element, propertyName)?.Trim();
        return string.IsNullOrEmpty(value) || string.Equals(value, "N/A", StringComparison.OrdinalIgnoreCase)
            ? null
            : value;
    }

    private static string[] SplitList(string? value) =>
        string.IsNullOrWhiteSpace(value) || string.Equals(value.Trim(), "N/A", StringComparison.OrdinalIgnoreCase)
            ? []
            : value.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);

    private static int? ParseYear(string? value) =>
        !string.IsNullOrWhiteSpace(value)
        && value.Length >= 4
        && int.TryParse(value.AsSpan(0, 4), NumberStyles.None, CultureInfo.InvariantCulture, out var year)
            ? year
            : null;

    private static decimal? ParseDecimal(string? value) =>
        !string.IsNullOrWhiteSpace(value)
        && !string.Equals(value, "N/A", StringComparison.OrdinalIgnoreCase)
        && decimal.TryParse(value, NumberStyles.Number, CultureInfo.InvariantCulture, out var number)
            ? number
            : null;

    private static long? ParseLong(string? value) =>
        !string.IsNullOrWhiteSpace(value)
        && !string.Equals(value, "N/A", StringComparison.OrdinalIgnoreCase)
        && long.TryParse(value.Replace(",", string.Empty, StringComparison.Ordinal), NumberStyles.None, CultureInfo.InvariantCulture, out var number)
            ? number
            : null;
}