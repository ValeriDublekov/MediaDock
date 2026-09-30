using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;

namespace MediaDock.IntegrationTests;

public sealed class PersistenceTests
{
    [Fact]
    [Trait("Category", "Persistence")]
    public async Task MigrationCreatesSchemaAndOccurrenceIdentityIsUnique()
    {
        await using var postgres = PostgreSqlTestContainerBuilder.Create("mediadock_test").Build();
        await postgres.StartAsync();

        var options = new DbContextOptionsBuilder<MediaDockDbContext>()
            .UseNpgsql(postgres.GetConnectionString())
            .Options;

        await using var db = new MediaDockDbContext(options);
        await db.Database.MigrateAsync();

        var appliedMigrations = await db.Database.GetAppliedMigrationsAsync();
        Assert.Single(appliedMigrations);

        await db.Database.OpenConnectionAsync();
        await using (var command = db.Database.GetDbConnection().CreateCommand())
        {
            command.CommandText = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'";
            await using var reader = await command.ExecuteReaderAsync();
            var tables = new HashSet<string>(StringComparer.Ordinal);
            while (await reader.ReadAsync())
            {
                tables.Add(reader.GetString(0));
            }

            Assert.All(
                new[]
                {
                    "titles", "sources", "occurrences", "scan_runs", "parse_logs", "settings", "metadata_cache",
                    "oscar_films", "oscar_nominations", "oscar_enrichment_runs", "omdb_daily_usage"
                },
                tableName => Assert.Contains(tableName, tables));
        }

        var observedAt = new DateTimeOffset(2026, 9, 28, 0, 0, 0, TimeSpan.Zero);
        var source = new Source
        {
            StableKey = "movies-main",
            Name = "Movies",
            FeedType = "movie",
            Url = "https://feed.example/movies"
        };
        var title = new Title
        {
            TitleText = "Example Film",
            NormalizedTitle = "example film",
            MediaType = "movie",
            SourceType = "movie",
            ContentKind = "standard",
            FirstSeenAt = observedAt,
            LastSeenAt = observedAt,
            UpdatedAt = observedAt
        };
        db.AddRange(source, title);
        await db.SaveChangesAsync();

        var itemKey = SourceItemKey.From(" guid-123 ", "https://feed.example/topic/1");
        db.Occurrences.Add(new Occurrence
        {
            TitleId = title.Id,
            SourceId = source.Id,
            SourceItemKey = itemKey,
            FeedEntryId = "guid-123",
            TorrentUrl = "https://feed.example/topic/1",
            RawTitle = "Example.Film.2026",
            SourceFeedName = source.Name,
            FeedType = source.FeedType,
            ObservedAt = observedAt,
            FirstSeenAt = observedAt,
            LastSeenAt = observedAt
        });
        await db.SaveChangesAsync();

        Assert.Equal(itemKey, SourceItemKey.From("guid-123", "https://feed.example/topic/changed"));
    db.ChangeTracker.Clear();
        db.Occurrences.Add(new Occurrence
        {
            TitleId = title.Id,
            SourceId = source.Id,
            SourceItemKey = SourceItemKey.From("guid-123", "https://feed.example/topic/changed"),
            FeedEntryId = "guid-123",
            TorrentUrl = "https://feed.example/topic/changed",
            RawTitle = "Example.Film.2026",
            SourceFeedName = source.Name,
            FeedType = source.FeedType,
            ObservedAt = observedAt.AddHours(1),
            FirstSeenAt = observedAt,
            LastSeenAt = observedAt.AddHours(1)
        });

        await Assert.ThrowsAsync<DbUpdateException>(() => db.SaveChangesAsync());
        db.ChangeTracker.Clear();
        Assert.Equal(1, await db.Occurrences.CountAsync());
    }

    [Fact]
    [Trait("Category", "Persistence")]
    public async Task DatabaseEnforcesIdentityTimestampSingletonAndStatusConstraints()
    {
        await using var postgres = PostgreSqlTestContainerBuilder.Create("mediadock_model_constraints_test").Build();
        await postgres.StartAsync();

        var options = new DbContextOptionsBuilder<MediaDockDbContext>()
            .UseNpgsql(postgres.GetConnectionString())
            .Options;
        await using var db = new MediaDockDbContext(options);
        await db.Database.MigrateAsync();

        var now = new DateTimeOffset(2026, 9, 30, 0, 0, 0, TimeSpan.Zero);
        var title = CreateTitle("Canonical", "canonical", "tt12345678", now);
        db.Titles.Add(title);
        await db.SaveChangesAsync();

        await AssertRejectedAsync(db, CreateTitle("Duplicate ID", "duplicate id", "tt12345678", now));

        db.Titles.AddRange(
            CreateTitle("Same Film", "same film", "tt20000001", now),
            CreateTitle("Same Film", "same film", "tt20000002", now));
        await db.SaveChangesAsync();
        Assert.Equal(3, await db.Titles.CountAsync());

        await AssertRejectedAsync(db, CreateTitle("Partial Range", "partial range", null, now, now, null));
        await AssertRejectedAsync(
            db,
            CreateTitle("Reversed Range", "reversed range", null, now, now.AddHours(1), now));

        var source = new Source
        {
            StableKey = "constraint-test",
            Name = "Constraint Test",
            FeedType = "movie",
            Url = "https://feed.example/movies"
        };
        db.Sources.Add(source);
        await db.SaveChangesAsync();
        await AssertRejectedAsync(db, new Occurrence
        {
            TitleId = title.Id,
            SourceId = source.Id,
            SourceItemKey = "reversed-occurrence",
            TorrentUrl = "https://feed.example/topic/1",
            RawTitle = "Canonical (2026)",
            SourceFeedName = source.Name,
            FirstSeenAt = now.AddHours(1),
            LastSeenAt = now
        });

        db.Settings.Add(new AppSetting { Id = 1, UpdatedAt = now });
        await db.SaveChangesAsync();
        await AssertRejectedAsync(db, new AppSetting { Id = 2, UpdatedAt = now });

        db.OscarFilms.Add(new OscarFilm
        {
            TitleId = title.Id,
            StableKey = "invalid-status",
            FilmTitle = title.TitleText,
            NormalizedTitle = title.NormalizedTitle,
            FilmYear = 2026,
            EnrichmentStatus = "unknown",
            ImportedAt = now,
            UpdatedAt = now
        });
        await Assert.ThrowsAsync<DbUpdateException>(() => db.SaveChangesAsync());
        db.ChangeTracker.Clear();

        db.OscarFilms.Add(new OscarFilm
        {
            TitleId = title.Id,
            StableKey = "negative-attempts",
            FilmTitle = title.TitleText,
            NormalizedTitle = title.NormalizedTitle,
            FilmYear = 2026,
            EnrichmentStatus = "pending",
            EnrichmentAttemptCount = -1,
            ImportedAt = now,
            UpdatedAt = now
        });
        await Assert.ThrowsAsync<DbUpdateException>(() => db.SaveChangesAsync());
        db.ChangeTracker.Clear();

        await AssertRejectedAsync(db, new ScanRun
        {
            StartedAt = now,
            FinishedAt = now,
            Status = "running",
            Trigger = "manual"
        });
        await AssertRejectedAsync(db, new ScanRun
        {
            StartedAt = now,
            Status = "succeeded",
            Trigger = "manual"
        });
        await AssertRejectedAsync(db, new OscarEnrichmentRun
        {
            StartedAt = now,
            FinishedAt = now,
            Status = "running",
            Trigger = "manual"
        });
        await AssertRejectedAsync(db, new OscarEnrichmentRun
        {
            StartedAt = now,
            Status = "succeeded",
            Trigger = "manual"
        });
    }

    private static Title CreateTitle(
        string title,
        string normalizedTitle,
        string? imdbId,
        DateTimeOffset updatedAt,
        DateTimeOffset? firstSeenAt = null,
        DateTimeOffset? lastSeenAt = null) => new()
    {
        TitleText = title,
        NormalizedTitle = normalizedTitle,
        Year = 2026,
        MediaType = "movie",
        ImdbId = imdbId,
        FirstSeenAt = firstSeenAt,
        LastSeenAt = lastSeenAt,
        UpdatedAt = updatedAt
    };

    private static async Task AssertRejectedAsync(MediaDockDbContext db, object entity)
    {
        db.Add(entity);
        await Assert.ThrowsAsync<DbUpdateException>(() => db.SaveChangesAsync());
        db.ChangeTracker.Clear();
    }
}