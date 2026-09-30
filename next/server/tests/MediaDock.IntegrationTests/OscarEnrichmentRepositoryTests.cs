using MediaDock.Application.Metadata;
using MediaDock.Application.OscarAwards;
using MediaDock.Infrastructure.Metadata;
using MediaDock.Infrastructure.OscarAwards;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;

namespace MediaDock.IntegrationTests;

[Trait("Category", "Persistence")]
public sealed class OscarEnrichmentRepositoryTests
{
    [Fact]
    public async Task RequestBudgetAtomicallyAppliesSharedAndOscarDailyLimits()
    {
        await using var postgres = PostgreSqlTestContainerBuilder.Create("mediadock_omdb_budget_test").Build();
        await postgres.StartAsync();

        var options = new DbContextOptionsBuilder<MediaDockDbContext>()
            .UseNpgsql(postgres.GetConnectionString())
            .Options;
        await using (var db = new MediaDockDbContext(options))
        {
            await db.Database.MigrateAsync();
        }

        var dayOne = new DateOnly(2026, 9, 29);
        var concurrentReservations = await Task.WhenAll(Enumerable.Range(0, 24).Select(async index =>
        {
            await using var db = new MediaDockDbContext(options);
            var purpose = index % 2 == 0
                ? OmdbRequestPurpose.OscarEnrichment
                : OmdbRequestPurpose.RssIngestion;
            return await new PostgresOmdbRequestBudget(db)
                .TryReserveAsync(dayOne, purpose, 6, 2);
        }));

        Assert.Equal(6, concurrentReservations.Count(reserved => reserved));
        await using (var db = new MediaDockDbContext(options))
        {
            var usage = await db.OmdbDailyUsage.SingleAsync(row => row.UtcDate == dayOne);
            Assert.Equal(6, usage.TotalRequests);
            Assert.InRange(usage.OscarRequests, 0, 2);
        }

        var dayTwo = dayOne.AddDays(1);
        var oscarReservations = await Task.WhenAll(Enumerable.Range(0, 8).Select(async _ =>
        {
            await using var db = new MediaDockDbContext(options);
            return await new PostgresOmdbRequestBudget(db)
                .TryReserveAsync(dayTwo, OmdbRequestPurpose.OscarEnrichment, 20, 3);
        }));

        Assert.Equal(3, oscarReservations.Count(reserved => reserved));
        await using var resultDb = new MediaDockDbContext(options);
        var oscarUsage = await resultDb.OmdbDailyUsage.SingleAsync(row => row.UtcDate == dayTwo);
        Assert.Equal(3, oscarUsage.TotalRequests);
        Assert.Equal(3, oscarUsage.OscarRequests);

        var dayThree = dayTwo.AddDays(1);
        var budget = new PostgresOmdbRequestBudget(resultDb);
        Assert.True(await budget.TryReserveAsync(dayThree, OmdbRequestPurpose.RssIngestion, 10, 5));
        await budget.MarkProviderQuotaExceededAsync(dayThree);
        Assert.False(await budget.TryReserveAsync(dayThree, OmdbRequestPurpose.OscarEnrichment, 10, 5));
        var quotaUsage = await resultDb.OmdbDailyUsage.SingleAsync(row => row.UtcDate == dayThree);
        Assert.Equal(1, quotaUsage.TotalRequests);
        Assert.Equal(0, quotaUsage.OscarRequests);
        Assert.True(quotaUsage.ProviderQuotaExceeded);
    }

    [Fact]
    public async Task GetEligibleCandidatesOrdersNewestFirstAndExcludesTerminalOrNotDueFilms()
    {
        await using var postgres = PostgreSqlTestContainerBuilder.Create("mediadock_oscar_enrichment_queue_test").Build();
        await postgres.StartAsync();

        var options = new DbContextOptionsBuilder<MediaDockDbContext>()
            .UseNpgsql(postgres.GetConnectionString())
            .Options;
        await using var db = new MediaDockDbContext(options);
        await db.Database.MigrateAsync();

        var now = new DateTimeOffset(2026, 9, 29, 12, 0, 0, TimeSpan.Zero);
        var films = new[]
        {
            CreateFilm("film-c", "Film C", 2025, "pending", now),
            CreateFilm("film-z", "Film Z", 2026, "pending", now),
            CreateFilm("film-a", "Film A", 2025, "pending", now),
            CreateFilm("film-b", "Film B", 2025, "temporary_error", now, now.AddMinutes(-1)),
            CreateFilm("film-future", "Future Retry", 2027, "temporary_error", now, now.AddHours(1)),
            CreateFilm("film-not-found", "Not Found", 2028, "not_found", now),
            CreateFilm("film-enriched", "Enriched", 2029, "enriched", now)
        };
        db.OscarFilms.AddRange(films);
        await db.SaveChangesAsync();

        var candidates = await new PostgresOscarEnrichmentRepository(db)
            .GetEligibleCandidatesAsync(now, 3);

        Assert.Equal(["Film Z", "Film A", "Film B"], candidates.Select(candidate => candidate.FilmTitle));
    }

    [Fact]
    public async Task EnrichmentRunRepositoryPersistsProgressAndCompletionSeparately()
    {
        await using var postgres = PostgreSqlTestContainerBuilder.Create("mediadock_oscar_enrichment_run_test").Build();
        await postgres.StartAsync();

        var options = new DbContextOptionsBuilder<MediaDockDbContext>()
            .UseNpgsql(postgres.GetConnectionString())
            .Options;
        await using var db = new MediaDockDbContext(options);
        await db.Database.MigrateAsync();

        var startedAt = new DateTimeOffset(2026, 9, 30, 3, 17, 0, TimeSpan.Zero);
        var finishedAt = startedAt.AddMinutes(4);
        var progress = new OscarEnrichmentRunProgress(7, 3, 1, 1, 1, 2, 5);
        var repository = new PostgresOscarEnrichmentRunRepository(db);
        var runId = await repository.StartAsync("schedule", startedAt);

        await repository.SaveProgressAsync(runId, progress);
        await repository.FinishAsync(
            runId,
            OscarEnrichmentRunStatuses.Partial,
            finishedAt,
            progress,
            "TimeoutException");

        var run = await db.OscarEnrichmentRuns.AsNoTracking().SingleAsync(candidate => candidate.Id == runId);
        Assert.Equal(startedAt, run.StartedAt);
        Assert.Equal(finishedAt, run.FinishedAt);
        Assert.Equal(OscarEnrichmentRunStatuses.Partial, run.Status);
        Assert.Equal("schedule", run.Trigger);
        Assert.Equal(7, run.EligibleFilms);
        Assert.Equal(3, run.ProcessedFilms);
        Assert.Equal(1, run.NotFoundFilms);
        Assert.Equal(1, run.TemporaryErrors);
        Assert.Equal(5, run.HttpAttempts);
        Assert.Equal("TimeoutException", run.ErrorCode);
        Assert.Empty(await db.ScanRuns.ToListAsync());
    }

    [Fact]
    public async Task SaveOutcomeUpdatesTitleMetadataWithoutCreatingOccurrenceOrChangingLastSeenAt()
    {
        await using var postgres = PostgreSqlTestContainerBuilder.Create("mediadock_oscar_enrichment_save_test").Build();
        await postgres.StartAsync();

        var options = new DbContextOptionsBuilder<MediaDockDbContext>()
            .UseNpgsql(postgres.GetConnectionString())
            .Options;
        await using var db = new MediaDockDbContext(options);
        await db.Database.MigrateAsync();

        var importedAt = new DateTimeOffset(2026, 9, 1, 0, 0, 0, TimeSpan.Zero);
        var lastSeenAt = importedAt.AddHours(1);
        var film = CreateFilm("film-metadata", "CSV Film", 2025, "pending", importedAt);
        film.Title.LastSeenAt = lastSeenAt;
        db.OscarFilms.Add(film);
        await db.SaveChangesAsync();

        var attemptedAt = importedAt.AddDays(2);
        var metadata = new MetadataDetails(
            "OMDb Film",
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
            "1 win",
            "$1,000,000");

        await new PostgresOscarEnrichmentRepository(db).SaveOutcomeAsync(
            film.Id,
            new OscarEnrichmentUpdate("enriched", 1, attemptedAt, null, null, metadata));

        var savedFilm = await db.OscarFilms.AsNoTracking()
            .Include(candidate => candidate.Title)
            .SingleAsync(candidate => candidate.Id == film.Id);
        Assert.Equal("enriched", savedFilm.EnrichmentStatus);
        Assert.Equal(1, savedFilm.EnrichmentAttemptCount);
        Assert.Equal(attemptedAt, savedFilm.LastEnrichmentAttemptAt);
        Assert.Equal("tt12345678", savedFilm.ImdbId);
        Assert.Equal("OMDb Film", savedFilm.Title.TitleText);
        Assert.Equal(8.2m, savedFilm.Title.ImdbRating);
        Assert.Equal("Director", savedFilm.Title.Director);
        Assert.Equal(lastSeenAt, savedFilm.Title.LastSeenAt);
        Assert.Equal(attemptedAt, savedFilm.Title.UpdatedAt);
        Assert.Empty(await db.Occurrences.ToListAsync());
    }

    [Fact]
    public async Task SaveOutcomeRejectsMetadataWithConflictingImdbIdentity()
    {
        await using var postgres = PostgreSqlTestContainerBuilder.Create("mediadock_oscar_enrichment_identity_test").Build();
        await postgres.StartAsync();

        var options = new DbContextOptionsBuilder<MediaDockDbContext>()
            .UseNpgsql(postgres.GetConnectionString())
            .Options;
        await using var db = new MediaDockDbContext(options);
        await db.Database.MigrateAsync();

        var importedAt = new DateTimeOffset(2026, 9, 1, 0, 0, 0, TimeSpan.Zero);
        var film = CreateFilm("film-identity", "Identity Film", 2025, "pending", importedAt);
        film.ImdbId = "tt11111111";
        film.Title.ImdbId = "tt11111111";
        db.OscarFilms.Add(film);
        await db.SaveChangesAsync();

        var attemptedAt = importedAt.AddDays(1);
        var conflictingMetadata = new MetadataDetails(
            "Other Film",
            2025,
            "tt22222222",
            "movie",
            "movie",
            "standard",
            null,
            9.1m,
            5000,
            90m,
            ["Drama"],
            ["US"],
            "Other Director",
            "Other plot",
            null,
            "100 min",
            null,
            null);

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            new PostgresOscarEnrichmentRepository(db).SaveOutcomeAsync(
                film.Id,
                new OscarEnrichmentUpdate("enriched", 1, attemptedAt, null, null, conflictingMetadata)));

        db.ChangeTracker.Clear();
        var unchangedFilm = await db.OscarFilms.AsNoTracking()
            .Include(candidate => candidate.Title)
            .SingleAsync(candidate => candidate.Id == film.Id);
        Assert.Equal("pending", unchangedFilm.EnrichmentStatus);
        Assert.Equal("tt11111111", unchangedFilm.ImdbId);
        Assert.Equal("tt11111111", unchangedFilm.Title.ImdbId);
        Assert.Equal("Identity Film", unchangedFilm.Title.TitleText);
        Assert.Null(unchangedFilm.Title.ImdbRating);
    }

    private static OscarFilm CreateFilm(
        string stableKey,
        string titleText,
        int year,
        string status,
        DateTimeOffset now,
        DateTimeOffset? nextAttemptAt = null)
    {
        var normalizedTitle = titleText.ToLowerInvariant();
        return new OscarFilm
        {
            StableKey = stableKey,
            FilmTitle = titleText,
            NormalizedTitle = normalizedTitle,
            FilmYear = year,
            EnrichmentStatus = status,
            NextEnrichmentAttemptAt = nextAttemptAt,
            ImportedAt = now,
            UpdatedAt = now,
            Title = new Title
            {
                TitleText = titleText,
                NormalizedTitle = normalizedTitle,
                Year = year,
                MediaType = "movie",
                SourceType = "movie",
                ContentKind = "standard",
                FirstSeenAt = now,
                LastSeenAt = now,
                UpdatedAt = now
            }
        };
    }
}