using MediaDock.Application.Metadata;
using MediaDock.Application.OscarAwards;

namespace MediaDock.UnitTests;

public sealed class OscarEnrichmentServiceTests
{
    [Fact]
    public async Task RunAsyncSavesEachOutcomeAndCountsFallbackHttpAttempts()
    {
        var now = new DateTimeOffset(2026, 9, 29, 12, 0, 0, TimeSpan.Zero);
        var repository = new FakeOscarEnrichmentRepository(
        [
            new OscarEnrichmentCandidate(1, "Newest Film", 2025, null, 0),
            new OscarEnrichmentCandidate(2, "Older Film", 2024, null, 2),
            new OscarEnrichmentCandidate(3, "Unmatched Film", 2023, null, 0)
        ]);
        var client = new StubOmdbClient(
        [
            new MetadataLookupResult(MetadataLookupStatus.Found, CreateMetadata(), HttpAttempts: 2),
            new MetadataLookupResult(MetadataLookupStatus.ConfirmedNotFound, HttpAttempts: 2),
            new MetadataLookupResult(MetadataLookupStatus.TransportFailure, HttpAttempts: 1, ErrorCode: "timeout")
        ]);
        var service = CreateService(repository, client, now);

        var summary = await service.RunAsync(3);

        Assert.Equal(3, summary.EligibleFilms);
        Assert.Equal(3, summary.AttemptedFilms);
        Assert.Equal(1, summary.EnrichedFilms);
        Assert.Equal(1, summary.NotFoundFilms);
        Assert.Equal(1, summary.TemporaryErrors);
        Assert.Equal(5, summary.HttpAttempts);
        Assert.False(summary.StoppedForQuota);
        Assert.Equal(3, repository.SavedOutcomes.Count);
        Assert.Equal(OscarEnrichmentStatuses.Enriched, repository.SavedOutcomes[0].Update.Status);
        Assert.Equal("tt12345678", repository.SavedOutcomes[0].Update.Metadata?.ImdbId);
        Assert.Equal(OscarEnrichmentStatuses.NotFound, repository.SavedOutcomes[1].Update.Status);
        Assert.Equal(OscarEnrichmentStatuses.TemporaryError, repository.SavedOutcomes[2].Update.Status);
        Assert.Equal(1, repository.SavedOutcomes[2].Update.AttemptCount);
        Assert.Equal(now.AddHours(1), repository.SavedOutcomes[2].Update.NextAttemptAt);
    }

    [Fact]
    public async Task RunAsyncStopsAtQuotaAndDefersCandidateUntilNextUtcDay()
    {
        var now = new DateTimeOffset(2026, 9, 29, 23, 30, 0, TimeSpan.FromHours(3));
        var repository = new FakeOscarEnrichmentRepository(
        [
            new OscarEnrichmentCandidate(1, "Newest Film", 2025, null, 0),
            new OscarEnrichmentCandidate(2, "Next Film", 2024, null, 0)
        ]);
        var client = new StubOmdbClient(
        [
            new MetadataLookupResult(MetadataLookupStatus.QuotaExceeded, HttpAttempts: 1, ErrorCode: "quota_exceeded"),
            new MetadataLookupResult(MetadataLookupStatus.Found, CreateMetadata(), HttpAttempts: 1)
        ]);
        var service = CreateService(repository, client, now);

        var summary = await service.RunAsync(2);

        Assert.Equal(2, summary.EligibleFilms);
        Assert.Equal(1, summary.AttemptedFilms);
        Assert.Equal(1, summary.TemporaryErrors);
        Assert.Equal(1, summary.HttpAttempts);
        Assert.True(summary.StoppedForQuota);
        Assert.Single(repository.SavedOutcomes);
        Assert.Equal(OscarEnrichmentStatuses.TemporaryError, repository.SavedOutcomes[0].Update.Status);
        Assert.Equal(
            new DateTimeOffset(2026, 9, 30, 0, 0, 0, TimeSpan.Zero),
            repository.SavedOutcomes[0].Update.NextAttemptAt);
        Assert.Equal(1, client.Calls);
    }

    [Fact]
    public async Task RunAsyncLeavesCandidateUntouchedWhenRequestBudgetRefusesReservation()
    {
        var now = new DateTimeOffset(2026, 9, 29, 12, 0, 0, TimeSpan.Zero);
        var repository = new FakeOscarEnrichmentRepository(
        [
            new OscarEnrichmentCandidate(1, "Newest Film", 2025, null, 0),
            new OscarEnrichmentCandidate(2, "Next Film", 2024, null, 0)
        ]);
        var client = new StubOmdbClient(
        [
            new MetadataLookupResult(
                MetadataLookupStatus.RequestBudgetExhausted,
                HttpAttempts: 0,
                ErrorCode: "daily_budget_exhausted")
        ]);
        var service = CreateService(repository, client, now);

        var summary = await service.RunAsync(2);

        Assert.Equal(2, summary.EligibleFilms);
        Assert.Equal(0, summary.AttemptedFilms);
        Assert.Equal(0, summary.TemporaryErrors);
        Assert.Equal(0, summary.HttpAttempts);
        Assert.True(summary.StoppedForQuota);
        Assert.Empty(repository.SavedOutcomes);
        Assert.Equal(1, client.Calls);
    }

    private static OscarEnrichmentService CreateService(
        FakeOscarEnrichmentRepository repository,
        StubOmdbClient client,
        DateTimeOffset now)
    {
        var resolver = new MetadataResolver(client, new EmptyMetadataCacheStore());
        return new OscarEnrichmentService(repository, resolver, new FrozenTimeProvider(now));
    }

    private static MetadataDetails CreateMetadata() =>
        new(
            "Newest Film",
            2025,
            "tt12345678",
            "movie",
            "movie",
            "standard",
            null,
            8.2m,
            1200,
            84m,
            ["Drama"],
            ["US"],
            "Director",
            "Plot",
            null,
            "120 min",
            null,
            null);

    private sealed class FakeOscarEnrichmentRepository(
        IReadOnlyList<OscarEnrichmentCandidate> candidates) : IOscarEnrichmentRepository
    {
        public List<(long FilmId, OscarEnrichmentUpdate Update)> SavedOutcomes { get; } = [];

        public Task<IReadOnlyList<OscarEnrichmentCandidate>> GetEligibleCandidatesAsync(
            DateTimeOffset now,
            int limit,
            CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<OscarEnrichmentCandidate>>(candidates.Take(limit).ToArray());

        public Task SaveOutcomeAsync(
            long filmId,
            OscarEnrichmentUpdate update,
            CancellationToken cancellationToken = default)
        {
            SavedOutcomes.Add((filmId, update));
            return Task.CompletedTask;
        }
    }

    private sealed class StubOmdbClient(IReadOnlyList<MetadataLookupResult> results) : IOmdbClient
    {
        private readonly Queue<MetadataLookupResult> _results = new(results);

        public int Calls { get; private set; }

        public Task<MetadataLookupResult> LookupAsync(
            string title,
            int? year,
            string sourceType,
            CancellationToken cancellationToken = default,
            OmdbRequestPurpose requestPurpose = OmdbRequestPurpose.RssIngestion)
        {
            Calls++;
            return Task.FromResult(_results.Dequeue());
        }
    }

    private sealed class EmptyMetadataCacheStore : IMetadataCacheStore
    {
        public Task<MetadataCacheValue?> GetAsync(
            string cacheKey,
            CancellationToken cancellationToken = default) =>
            Task.FromResult<MetadataCacheValue?>(null);

        public Task StoreAsync(
            string cacheKey,
            MetadataCacheValue value,
            CancellationToken cancellationToken = default) => Task.CompletedTask;
    }

    private sealed class FrozenTimeProvider(DateTimeOffset now) : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => now;
    }
}