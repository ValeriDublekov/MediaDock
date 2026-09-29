using MediaDock.Application.Ingestion;
using MediaDock.Application.Metadata;
using MediaDock.Infrastructure.Ingestion;
using MediaDock.Infrastructure.Metadata;
using MediaDock.Infrastructure.OscarAwards;
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
        if (!TryParseArguments(args, out var trigger, out var oscarCsvPath, out var yearAfter))
        {
            Console.Error.WriteLine(
                "Usage: MediaDock.Worker [--trigger manual|schedule] "
                + "| --import-oscar <csv-path> [--year-after <year>]");
            return 2;
        }

        var builder = Host.CreateApplicationBuilder(Array.Empty<string>());
        var connectionString = builder.Configuration.GetConnectionString("MediaDock");
        if (string.IsNullOrWhiteSpace(connectionString))
        {
            Console.Error.WriteLine("ConnectionStrings:MediaDock must be configured.");
            return 2;
        }

        builder.Services.AddDbContext<MediaDockDbContext>(options => options.UseNpgsql(connectionString));
        builder.Services.AddScoped<PostgresAdvisoryScanLock>();
        HttpClient? rssHttpClient = null;
        HttpClient? omdbHttpClient = null;
        if (trigger is null)
        {
            builder.Services.AddScoped<OscarDatasetImporter>();
        }
        else
        {
            var apiKey = builder.Configuration["OMDB_API_KEY"];
            if (string.IsNullOrWhiteSpace(apiKey))
            {
                Console.Error.WriteLine("OMDB_API_KEY must be configured.");
                return 2;
            }

            var dnsResolver = new SystemRssDnsResolver();
            rssHttpClient = RssFeedHttpClientFactory.Create(dnsResolver);
            omdbHttpClient = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
            builder.Services.AddScoped<IRssIngestionRepository, PostgresRssIngestionRepository>();
            builder.Services.AddScoped<IMetadataCacheStore, PostgresMetadataCacheStore>();
            builder.Services.AddScoped<MetadataResolver>();
            builder.Services.AddScoped<RssIngestionService>();
            builder.Services.AddSingleton<IRssDnsResolver>(dnsResolver);
            builder.Services.AddSingleton(new RssFeedTransport(rssHttpClient, dnsResolver));
            builder.Services.AddScoped<IRssFeedTransport, RssFeedTransportAdapter>();
            builder.Services.AddSingleton<IOmdbClient>(new OmdbClient(omdbHttpClient, apiKey));
        }

        using var rssHttpClientLifetime = rssHttpClient;
        using var omdbHttpClientLifetime = omdbHttpClient;
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

            if (oscarCsvPath is not null)
            {
                var summary = await scope.ServiceProvider
                    .GetRequiredService<OscarDatasetImporter>()
                    .ImportAsync(oscarCsvPath, yearAfter, applicationLifetime.ApplicationStopping);
                Console.WriteLine(
                    $"Oscar import completed: {summary.OscarFilmsCreated} films, "
                    + $"{summary.NominationsCreated} nominations added, "
                    + $"{summary.NominationsUpdated} nominations updated, "
                    + $"{summary.RowsSkippedByCategory} rows outside the selected categories skipped.");
                return 0;
            }

            var result = await scope.ServiceProvider
                .GetRequiredService<RssIngestionService>()
                .RunAsync(trigger!, applicationLifetime.ApplicationStopping);

            Console.WriteLine(
                $"RSS scan {result.RunId} {result.Summary.Status}: "
                + $"{result.Summary.FeedsProcessed} feeds, {result.Summary.ErrorCount} errors.");
            return result.Summary.Status == "succeeded" ? 0 : 1;
        }
        catch (OperationCanceledException) when (applicationLifetime.ApplicationStopping.IsCancellationRequested)
        {
            Console.Error.WriteLine(oscarCsvPath is null ? "RSS scan cancelled." : "Oscar import cancelled.");
            return CancelledExitCode;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(
                $"{(oscarCsvPath is null ? "RSS scan" : "Oscar import")} failed ({exception.GetType().Name}).");
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

    private static bool TryParseArguments(
        string[] args,
        out string? trigger,
        out string? oscarCsvPath,
        out int yearAfter)
    {
        trigger = null;
        oscarCsvPath = null;
        yearAfter = 1980;

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

        if (args.Length == 2 && args[0] == "--import-oscar" && !string.IsNullOrWhiteSpace(args[1]))
        {
            oscarCsvPath = args[1];
            return true;
        }

        if (args.Length == 4
            && args[0] == "--import-oscar"
            && !string.IsNullOrWhiteSpace(args[1])
            && args[2] == "--year-after"
            && int.TryParse(args[3], out yearAfter)
            && yearAfter is >= 0 and < 9999)
        {
            oscarCsvPath = args[1];
            return true;
        }

        return false;
    }
}