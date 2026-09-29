using System.Data.Common;
using MediaDock.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;

namespace MediaDock.Worker.Locking;

public sealed class PostgresAdvisoryScanLock(MediaDockDbContext dbContext)
{
    private const long AdvisoryLockKey = 0x4D65646961446F63L;

    public async Task<IAsyncDisposable?> TryAcquireAsync(CancellationToken cancellationToken = default)
    {
        var database = dbContext.Database;
        await database.OpenConnectionAsync(cancellationToken);

        try
        {
            var acquired = await ExecuteLockCommandAsync(
                database.GetDbConnection(),
                "SELECT pg_try_advisory_lock(@key)",
                cancellationToken);
            if (!acquired)
            {
                await database.CloseConnectionAsync();
                return null;
            }

            return new AdvisoryLockLease(database);
        }
        catch
        {
            await database.CloseConnectionAsync();
            throw;
        }
    }

    private static async Task<bool> ExecuteLockCommandAsync(
        DbConnection connection,
        string commandText,
        CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = commandText;
        var keyParameter = command.CreateParameter();
        keyParameter.ParameterName = "key";
        keyParameter.Value = AdvisoryLockKey;
        command.Parameters.Add(keyParameter);
        return await command.ExecuteScalarAsync(cancellationToken) is true;
    }

    private sealed class AdvisoryLockLease(DatabaseFacade database) : IAsyncDisposable
    {
        private DatabaseFacade? _database = database;

        public async ValueTask DisposeAsync()
        {
            var openDatabase = Interlocked.Exchange(ref _database, null);
            if (openDatabase is null)
            {
                return;
            }

            try
            {
                var unlocked = await ExecuteLockCommandAsync(
                    openDatabase.GetDbConnection(),
                    "SELECT pg_advisory_unlock(@key)",
                    CancellationToken.None);
                if (!unlocked)
                {
                    throw new InvalidOperationException("The PostgreSQL scan advisory lock was not held.");
                }
            }
            finally
            {
                await openDatabase.CloseConnectionAsync();
            }
        }
    }
}