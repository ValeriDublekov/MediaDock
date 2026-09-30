using System.Net;
using MediaDock.Application.Metadata;
using MediaDock.Infrastructure.Metadata;

namespace MediaDock.UnitTests;

public sealed class OmdbClientBudgetTests
{
    [Fact]
    public async Task LookupDoesNotSendFallbackWhenBudgetIsExhausted()
    {
        var budget = new SequentialRequestBudget(true, false);
        var handler = new NotFoundHandler();
        using var httpClient = new HttpClient(handler);
        var client = new OmdbClient(
            httpClient,
            "test-key",
            requestBudget: budget,
            dailyRequestLimit: 1,
            oscarDailyRequestLimit: 1);

        var result = await client.LookupAsync(
            "Example Film",
            1984,
            "movie",
            requestPurpose: OmdbRequestPurpose.OscarEnrichment);

        Assert.Equal(MetadataLookupStatus.RequestBudgetExhausted, result.Status);
        Assert.Equal("daily_budget_exhausted", result.ErrorCode);
        Assert.Equal(1, result.HttpAttempts);
        Assert.Equal(1, handler.RequestCount);
        Assert.Equal(2, budget.ReservationCount);
        Assert.All(budget.RequestPurposes, purpose => Assert.Equal(OmdbRequestPurpose.OscarEnrichment, purpose));
    }

    [Fact]
    public async Task LookupPersistsProviderQuotaExhaustionForTheReservedUtcDay()
    {
        var budget = new SequentialRequestBudget(true);
        var handler = new QuotaExceededHandler();
        using var httpClient = new HttpClient(handler);
        var client = new OmdbClient(
            httpClient,
            "test-key",
            requestBudget: budget,
            dailyRequestLimit: 10,
            oscarDailyRequestLimit: 5);

        var result = await client.LookupAsync("Example Series", null, "series");

        Assert.Equal(MetadataLookupStatus.QuotaExceeded, result.Status);
        Assert.Equal(1, result.HttpAttempts);
        Assert.Equal(1, handler.RequestCount);
        Assert.Equal(budget.ReservedDays.Single(), budget.ProviderQuotaExceededDate);
    }

    private sealed class SequentialRequestBudget(params bool[] reservations) : IOmdbRequestBudget
    {
        private readonly Queue<bool> _reservations = new(reservations);

        public int ReservationCount => RequestPurposes.Count;
        public List<OmdbRequestPurpose> RequestPurposes { get; } = [];
        public List<DateOnly> ReservedDays { get; } = [];
        public DateOnly? ProviderQuotaExceededDate { get; private set; }

        public Task<bool> TryReserveAsync(
            DateOnly utcDate,
            OmdbRequestPurpose requestPurpose,
            int dailyRequestLimit,
            int oscarDailyRequestLimit,
            CancellationToken cancellationToken = default)
        {
            RequestPurposes.Add(requestPurpose);
            ReservedDays.Add(utcDate);
            return Task.FromResult(_reservations.Dequeue());
        }

        public Task MarkProviderQuotaExceededAsync(
            DateOnly utcDate,
            CancellationToken cancellationToken = default)
        {
            ProviderQuotaExceededDate = utcDate;
            return Task.CompletedTask;
        }
    }

    private sealed class NotFoundHandler : HttpMessageHandler
    {
        public int RequestCount { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            RequestCount++;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("""{"Response":"False","Error":"Movie not found!"}""")
            });
        }
    }

    private sealed class QuotaExceededHandler : HttpMessageHandler
    {
        public int RequestCount { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            RequestCount++;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("""{"Response":"False","Error":"Request limit reached!"}""")
            });
        }
    }
}