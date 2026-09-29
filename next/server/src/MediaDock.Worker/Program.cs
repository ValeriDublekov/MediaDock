using MediaDock.Application.Ingestion;
using MediaDock.Application.Metadata;
using MediaDock.Infrastructure.Ingestion;
using MediaDock.Infrastructure.Metadata;
using MediaDock.Infrastructure.Persistence;
using MediaDock.Infrastructure.Rss;
using MediaDock.Worker.Locking;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

return await WorkerCommand.RunAsync(args);

internal static class WorkerCommand
{
    private const int ScanAlreadyRunningExitCode = 75;
    private const int CancelledExitCode = 130;

    public static async Task<int> RunAsync(string[] args)
    {
        if (!TryParseTrigger(args, out var trigger))
        {
            Console.Error.WriteLine("Usage: MediaDock.Worker [--trigger manual|schedule]");
            return 2;
        }

        var builder = Host.CreateApplicationBuilder(Array.Empty<string>());
        var connectionString = builder.Configuration.GetConnectionString("MediaDock");
        if (string.IsNullOrWhiteSpace(connectionString))
        {
            Console.Error.WriteLine("ConnectionStrings:MediaDock must be configured.");
            return 2;
        }

        var apiKey = builder.Configuration["OMDB_API_KEY"];
        if (string.IsNullOrWhiteSpace(apiKey))
        {
            Console.Error.WriteLine("OMDB_API_KEY must be configured.");
            return 2;
        }

        var dnsResolver = new SystemRssDnsResolver();
        using var rssHttpClient = RssFeedHttpClientFactory.Create(dnsResolver);
        using var omdbHttpClient = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };

        builder.Services.AddDbContext<MediaDockDbContext>(options => options.UseNpgsql(connectionString));
        builder.Services.AddScoped<PostgresAdvisoryScanLock>();
        builder.Services.AddScoped<IRssIngestionRepository, PostgresRssIngestionRepository>();
        builder.Services.AddScoped<IMetadataCacheStore, PostgresMetadataCacheStore>();
        builder.Services.AddScoped<MetadataResolver>();
        builder.Services.AddScoped<RssIngestionService>();
        builder.Services.AddSingleton<IRssDnsResolver>(dnsResolver);
        builder.Services.AddSingleton(new RssFeedTransport(rssHttpClient, dnsResolver));
        builder.Services.AddScoped<IRssFeedTransport, RssFeedTransportAdapter>();
        builder.Services.AddSingleton<IOmdbClient>(new OmdbClient(omdbHttpClient, apiKey));

        using var host = builder.Build();
        var applicationLifetime = host.Services.GetRequiredService<IHostApplicationLifetime>();
        var hostStarted = false;
        try
        {
            await host.StartAsync();
            hostStarted = true;

            await using var scope = host.Services.CreateAsyncScope();
            var scanLock = scope.ServiceProvider.GetRequiredService<PostgresAdvisoryScanLock>();
            await using var lockLease = await scanLock.TryAcquireAsync(applicationLifetime.ApplicationStopping);
            if (lockLease is null)
            {
                Console.Error.WriteLine("A scan is already running; this invocation was skipped.");
                return ScanAlreadyRunningExitCode;
            }

            var result = await scope.ServiceProvider
                .GetRequiredService<RssIngestionService>()
                .RunAsync(trigger, applicationLifetime.ApplicationStopping);

            Console.WriteLine(
                $"RSS scan {result.RunId} {result.Summary.Status}: "
                + $"{result.Summary.FeedsProcessed} feeds, {result.Summary.ErrorCount} errors.");
            return result.Summary.Status == "succeeded" ? 0 : 1;
        }
        catch (OperationCanceledException) when (applicationLifetime.ApplicationStopping.IsCancellationRequested)
        {
            Console.Error.WriteLine("RSS scan cancelled.");
            return CancelledExitCode;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"RSS scan failed ({exception.GetType().Name}).");
            return 1;
        }
        finally
        {
            if (hostStarted)
            {
                await host.StopAsync();
            }
        }
    }

    private static bool TryParseTrigger(string[] args, out string trigger)
    {
        if (args.Length == 0)
        {
            trigger = "manual";
            return true;
        }

        if (args.Length == 2 && args[0] == "--trigger" && (args[1] is "manual" or "schedule"))
        {
            trigger = args[1];
            return true;
        }

        trigger = string.Empty;
        return false;
    }
}