using MediaDock.Infrastructure.Persistence;
using MediaDock.Worker.Locking;
using Microsoft.EntityFrameworkCore;

namespace MediaDock.IntegrationTests;

[Trait("Category", "Worker")]
public sealed class WorkerConcurrencyTests
{
    [Fact]
    public async Task PostgreSqlAdvisoryLockPreventsConcurrentScansAndAllowsTheNextRun()
    {
        await using var postgres = PostgreSqlTestContainerBuilder.Create("mediadock_worker_test").Build();
        await postgres.StartAsync();

        var options = new DbContextOptionsBuilder<MediaDockDbContext>()
            .UseNpgsql(postgres.GetConnectionString())
            .Options;
        await using var firstContext = new MediaDockDbContext(options);
        await using var secondContext = new MediaDockDbContext(options);
        var firstScanLock = new PostgresAdvisoryScanLock(firstContext);
        var secondScanLock = new PostgresAdvisoryScanLock(secondContext);

        var firstLease = await firstScanLock.TryAcquireAsync()
            ?? throw new InvalidOperationException("The first scan should acquire the advisory lock.");
        await using (firstLease)
        {
            Assert.Null(await secondScanLock.TryAcquireAsync());
        }

        await using var nextLease = await secondScanLock.TryAcquireAsync();
        Assert.NotNull(nextLease);
    }
}