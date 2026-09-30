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
        Assert.Equal(4, appliedMigrations.Count());

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
                    "oscar_films", "oscar_nominations", "omdb_daily_usage"
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
}