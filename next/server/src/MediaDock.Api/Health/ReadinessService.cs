using MediaDock.Infrastructure.Persistence;

namespace MediaDock.Api.Health;

internal interface IReadinessService
{
    Task<bool> IsReadyAsync(CancellationToken cancellationToken);
}

internal sealed class ReadinessService(MediaDockDbContext dbContext) : IReadinessService
{
    public Task<bool> IsReadyAsync(CancellationToken cancellationToken) =>
        dbContext.Database.CanConnectAsync(cancellationToken);
}