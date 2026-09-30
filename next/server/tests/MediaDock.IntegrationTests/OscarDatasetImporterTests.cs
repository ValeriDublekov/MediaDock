using System.Text;
using MediaDock.Infrastructure.OscarAwards;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;

namespace MediaDock.IntegrationTests;

[Trait("Category", "Persistence")]
public sealed class OscarDatasetImporterTests
{
    [Fact]
    public async Task ImportAcceptsOriginalTabSeparatedKaggleDataset()
    {
        await using var postgres = PostgreSqlTestContainerBuilder.Create("mediadock_oscar_tsv_test").Build();
        await postgres.StartAsync();

        var options = new DbContextOptionsBuilder<MediaDockDbContext>()
            .UseNpgsql(postgres.GetConnectionString())
            .Options;
        await using var db = new MediaDockDbContext(options);
        await db.Database.MigrateAsync();

        var headers = string.Join('\t',
            "Ceremony", "Year", "Class", "CanonicalCategory", "Category", "Film", "FilmId",
            "Name", "Nominees", "NomineeIds", "Winner", "Detail");
        var row = string.Join('\t',
            "98", "2025", "Title", "BEST PICTURE", "BEST PICTURE", "Tab Film", " TT12345678 ",
            "Producers", "Producer A|Producer B", "nm0000001|nm0000002", "True", "");
        var tsvPath = Path.Combine(Path.GetTempPath(), $"mediadock-oscar-{Guid.NewGuid():N}.tsv");
        await File.WriteAllTextAsync(tsvPath, $"{headers}{Environment.NewLine}{row}{Environment.NewLine}");

        try
        {
            var summary = await new OscarDatasetImporter(db).ImportAsync(tsvPath);

            Assert.Equal(1, summary.RowsRead);
            Assert.Equal(1, summary.OscarFilmsCreated);
            Assert.Equal(1, summary.NominationsCreated);
            var nomination = await db.OscarNominations.SingleAsync();
            Assert.Equal("Tab Film", nomination.OscarFilm.Title.TitleText);
            Assert.True(nomination.IsWinner);
        }
        finally
        {
            File.Delete(tsvPath);
        }
    }

    [Fact]
    public async Task ImportMatchesTitleKeyedOscarFilmWhenUpdatedDatasetAddsImdbId()
    {
        await using var postgres = PostgreSqlTestContainerBuilder.Create("mediadock_oscar_identity_test").Build();
        await postgres.StartAsync();

        var options = new DbContextOptionsBuilder<MediaDockDbContext>()
            .UseNpgsql(postgres.GetConnectionString())
            .Options;
        await using var db = new MediaDockDbContext(options);
        await db.Database.MigrateAsync();

        const string initialCsv = """
            Ceremony,Year,Class,CanonicalCategory,Category,Film,FilmId,Name,Nominees,NomineeIds,Detail,Winner
            98,2025,Title,BEST PICTURE,BEST PICTURE,Stable Film,,Producers,Producers,,,True
            """;
        const string updatedCsv = """
            Ceremony,Year,Class,CanonicalCategory,Category,Film,FilmId,Name,Nominees,NomineeIds,Detail,Winner
            98,2025,Title,BEST PICTURE,BEST PICTURE,Stable Film,tt12345678,Producers,Producers,,,True
            """;
        var csvPath = Path.Combine(Path.GetTempPath(), $"mediadock-oscar-{Guid.NewGuid():N}.csv");

        try
        {
            var importer = new OscarDatasetImporter(db);
            await File.WriteAllTextAsync(csvPath, initialCsv);
            var initialImport = await importer.ImportAsync(csvPath);
            var originalFilmId = (await db.OscarFilms.SingleAsync()).Id;

            await File.WriteAllTextAsync(csvPath, updatedCsv);
            var updatedImport = await importer.ImportAsync(csvPath);

            Assert.Equal(1, initialImport.OscarFilmsCreated);
            Assert.Equal(0, updatedImport.OscarFilmsCreated);
            Assert.Equal(0, updatedImport.NominationsCreated);
            Assert.Equal(0, updatedImport.NominationsUpdated);
            Assert.Equal(1, await db.OscarFilms.CountAsync());
            Assert.Equal(1, await db.OscarNominations.CountAsync());

            var film = await db.OscarFilms.Include(item => item.Title).SingleAsync();
            Assert.Equal(originalFilmId, film.Id);
            Assert.Equal("tt12345678", film.ImdbId);
            Assert.Equal("tt12345678", film.Title.ImdbId);
            Assert.Equal(film.Id, (await db.OscarNominations.SingleAsync()).OscarFilmId);
        }
        finally
        {
            File.Delete(csvPath);
        }
    }

    [Fact]
    public async Task ImportIsCategoryScopedIdempotentAndPreservesOmdbMetadata()
    {
        await using var postgres = PostgreSqlTestContainerBuilder.Create("mediadock_oscar_import_test").Build();
        await postgres.StartAsync();

        var options = new DbContextOptionsBuilder<MediaDockDbContext>()
            .UseNpgsql(postgres.GetConnectionString())
            .Options;
        await using var db = new MediaDockDbContext(options);
        await db.Database.MigrateAsync();

        var now = new DateTimeOffset(2026, 9, 29, 0, 0, 0, TimeSpan.Zero);
        db.Titles.Add(new Title
        {
            TitleText = "Existing Film, Extended",
            NormalizedTitle = "existing film, extended",
            Year = 2025,
            MediaType = "movie",
            SourceType = "movie",
            ContentKind = "standard",
            ImdbId = "tt12300742",
            ImdbRating = 8.4m,
            ImdbVotes = 42000,
            Director = "Existing OMDb director",
            Plot = "Keep this OMDb plot.",
            FirstSeenAt = now.AddDays(-3),
            LastSeenAt = now.AddDays(-2),
            UpdatedAt = now.AddDays(-1)
        });
        await db.SaveChangesAsync();

        const string csv = """
            Ceremony,Year,Class,CanonicalCategory,Category,Film,FilmId,Name,Nominees,NomineeIds,Detail,Winner
            98,2025,Title,BEST PICTURE,BEST PICTURE,"Existing Film, Extended",tt12300742,Producers,Producers,,,True
            98,2025,Feature Film,CINEMATOGRAPHY,CINEMATOGRAPHY,"Existing Film, Extended",tt12300742,Director of Photography,Alex Person,nm0000001,,
            98,2025,Writing,WRITING (Original Screenplay),WRITING (Original Screenplay),"Existing Film, Extended",tt12300742,Writer,Writer Person,nm0000002,,
            98,2025,Writing,WRITING (Adapted Screenplay),WRITING (Adapted Screenplay),"Existing Film, Extended",tt12300742,Writer,Other Writer,nm0000003,,True
            98,2025,Feature Film,DIRECTING,DIRECTING,New Film,tt9999999,Director,New Director,nm0000004,,True
            98,2025,Music,MUSIC (Original Song),MUSIC (Original Song),"Existing Film, Extended",tt12300742,Composer,Composer Person,nm0000005,Sample song,True
            55,1980,Title,BEST PICTURE,BEST PICTURE,Older Film,tt8888888,Producers,Producers,,,True
            """;
        var csvPath = Path.Combine(Path.GetTempPath(), $"mediadock-oscar-{Guid.NewGuid():N}.csv");
        await File.WriteAllTextAsync(csvPath, csv, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));

        try
        {
            var importer = new OscarDatasetImporter(db);
            var firstImport = await importer.ImportAsync(csvPath);

            Assert.Equal(7, firstImport.RowsRead);
            Assert.Equal(1, firstImport.RowsSkippedByYear);
            Assert.Equal(1, firstImport.RowsSkippedByCategory);
            Assert.Equal(0, firstImport.RowsSkippedWithoutFilm);
            Assert.Equal(1, firstImport.TitlesCreated);
            Assert.Equal(2, firstImport.OscarFilmsCreated);
            Assert.Equal(5, firstImport.NominationsCreated);
            Assert.Equal(0, firstImport.NominationsUpdated);
            Assert.Equal(2, await db.OscarFilms.CountAsync());
            Assert.Equal(5, await db.OscarNominations.CountAsync());
            Assert.Empty(await db.Occurrences.ToListAsync());

            var existingTitle = await db.Titles.SingleAsync(title => title.ImdbId == "tt12300742");
            Assert.Equal(8.4m, existingTitle.ImdbRating);
            Assert.Equal("Existing OMDb director", existingTitle.Director);
            Assert.Equal("Keep this OMDb plot.", existingTitle.Plot);

            var placeholder = await db.Titles.SingleAsync(title => title.ImdbId == "tt9999999");
            Assert.Equal("New Film", placeholder.TitleText);
            Assert.Equal(2025, placeholder.Year);
            Assert.Null(placeholder.ImdbRating);
            Assert.Null(placeholder.FirstSeenAt);
            Assert.Null(placeholder.LastSeenAt);

            var importedFilm = await db.OscarFilms.SingleAsync(film => film.ImdbId == "tt9999999");
            importedFilm.EnrichmentStatus = "enriched";
            importedFilm.EnrichmentAttemptCount = 1;
            placeholder.ImdbRating = 7.6m;
            placeholder.Plot = "Added later by OMDb.";
            await db.SaveChangesAsync();

            var secondImport = await importer.ImportAsync(csvPath);

            Assert.Equal(0, secondImport.TitlesCreated);
            Assert.Equal(0, secondImport.OscarFilmsCreated);
            Assert.Equal(0, secondImport.NominationsCreated);
            Assert.Equal(0, secondImport.NominationsUpdated);
            Assert.Equal(2, await db.Titles.CountAsync());
            Assert.Equal(2, await db.OscarFilms.CountAsync());
            Assert.Equal(5, await db.OscarNominations.CountAsync());

            var preservedTitle = await db.Titles.SingleAsync(title => title.ImdbId == "tt9999999");
            Assert.Equal(7.6m, preservedTitle.ImdbRating);
            Assert.Equal("Added later by OMDb.", preservedTitle.Plot);
            var preservedFilm = await db.OscarFilms.SingleAsync(film => film.ImdbId == "tt9999999");
            Assert.Equal("enriched", preservedFilm.EnrichmentStatus);
            Assert.Equal(1, preservedFilm.EnrichmentAttemptCount);
        }
        finally
        {
            File.Delete(csvPath);
        }
    }

    [Fact]
    public async Task ImportDoesNotMergeSameTitleAndYearWithDifferentImdbIds()
    {
        await using var postgres = PostgreSqlTestContainerBuilder.Create("mediadock_oscar_identity_conflict_test").Build();
        await postgres.StartAsync();

        var options = new DbContextOptionsBuilder<MediaDockDbContext>()
            .UseNpgsql(postgres.GetConnectionString())
            .Options;
        await using var db = new MediaDockDbContext(options);
        await db.Database.MigrateAsync();

        var now = new DateTimeOffset(2026, 9, 30, 0, 0, 0, TimeSpan.Zero);
        var existingTitle = new Title
        {
            TitleText = "Shared Film",
            NormalizedTitle = "shared film",
            Year = 2025,
            MediaType = "movie",
            ImdbId = "tt11111111",
            UpdatedAt = now
        };
        db.Titles.Add(existingTitle);
        await db.SaveChangesAsync();

        const string csv = """
            Ceremony,Year,Class,CanonicalCategory,Category,Film,FilmId,Name,Nominees,NomineeIds,Detail,Winner
            98,2025,Title,BEST PICTURE,BEST PICTURE,Shared Film,TT22222222,Producers,Producers,,,True
            """;
        var csvPath = Path.Combine(Path.GetTempPath(), $"mediadock-oscar-{Guid.NewGuid():N}.csv");

        try
        {
            await File.WriteAllTextAsync(csvPath, csv);
            var summary = await new OscarDatasetImporter(db).ImportAsync(csvPath);

            Assert.Equal(1, summary.TitlesCreated);
            Assert.Equal(2, await db.Titles.CountAsync());
            var importedFilm = await db.OscarFilms.Include(film => film.Title).SingleAsync();
            Assert.Equal("tt22222222", importedFilm.ImdbId);
            Assert.NotEqual(existingTitle.Id, importedFilm.TitleId);
            Assert.Equal("tt11111111", (await db.Titles.SingleAsync(title => title.Id == existingTitle.Id)).ImdbId);
        }
        finally
        {
            File.Delete(csvPath);
        }
    }
}