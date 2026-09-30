using MediaDock.Infrastructure.Persistence.Entities;
using Microsoft.EntityFrameworkCore;

namespace MediaDock.Infrastructure.Persistence;

public sealed class MediaDockDbContext : DbContext
{
    public MediaDockDbContext(DbContextOptions<MediaDockDbContext> options)
        : base(options)
    {
    }

    public DbSet<Title> Titles => Set<Title>();
    public DbSet<Source> Sources => Set<Source>();
    public DbSet<Occurrence> Occurrences => Set<Occurrence>();
    public DbSet<ScanRun> ScanRuns => Set<ScanRun>();
    public DbSet<ParseLog> ParseLogs => Set<ParseLog>();
    public DbSet<AppSetting> Settings => Set<AppSetting>();
    public DbSet<MetadataCacheEntry> MetadataCache => Set<MetadataCacheEntry>();
    public DbSet<OmdbDailyUsage> OmdbDailyUsage => Set<OmdbDailyUsage>();
    public DbSet<OscarFilm> OscarFilms => Set<OscarFilm>();
    public DbSet<OscarNomination> OscarNominations => Set<OscarNomination>();
    public DbSet<OscarEnrichmentRun> OscarEnrichmentRuns => Set<OscarEnrichmentRun>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);
        modelBuilder.ApplyConfigurationsFromAssembly(typeof(MediaDockDbContext).Assembly);
    }
}