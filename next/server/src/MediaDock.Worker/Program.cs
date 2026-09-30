using MediaDock.Application.Ingestion;
using MediaDock.Application.Metadata;
using MediaDock.Application.OscarAwards;
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
        var maximumOscarFilmsPerRun = 0;
        var dailyOmdbRequestLimit = 0;
        var maximumOscarRequestsPerDay = 0;
        if (trigger is not null)
        {
            var configuredLimit = builder.Configuration["OSCAR_ENRICHMENT_MAX_FILMS_PER_RUN"];
            if (!string.IsNullOrWhiteSpace(configuredLimit)
                && (!int.TryParse(configuredLimit, out maximumOscarFilmsPerRun) || maximumOscarFilmsPerRun < 0))
            {
                Console.Error.WriteLine("OSCAR_ENRICHMENT_MAX_FILMS_PER_RUN must be a non-negative integer.");
                return 2;
            }

            var configuredDailyLimit = builder.Configuration["OMDB_DAILY_REQUEST_LIMIT"];
            if (!int.TryParse(configuredDailyLimit, out dailyOmdbRequestLimit) || dailyOmdbRequestLimit <= 0)
            {
                Console.Error.WriteLine(
                    "OMDB_DAILY_REQUEST_LIMIT must be a positive integer matching the API key's daily quota.");
                return 2;
            }

            var configuredOscarLimit = builder.Configuration["OSCAR_ENRICHMENT_MAX_REQUESTS_PER_DAY"];
            if (!string.IsNullOrWhiteSpace(configuredOscarLimit)
                && (!int.TryParse(configuredOscarLimit, out maximumOscarRequestsPerDay)
                    || maximumOscarRequestsPerDay < 0))
            {
                Console.Error.WriteLine("OSCAR_ENRICHMENT_MAX_REQUESTS_PER_DAY must be a non-negative integer.");
                return 2;
            }

            if (maximumOscarFilmsPerRun > 0 && maximumOscarRequestsPerDay == 0)
            {
                Console.Error.WriteLine(
                    "OSCAR_ENRICHMENT_MAX_REQUESTS_PER_DAY must be positive when Oscar enrichment is enabled.");
                return 2;
            }
        }

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
            var configuredOmdbHttpClient = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
            omdbHttpClient = configuredOmdbHttpClient;
            builder.Services.AddScoped<IRssIngestionRepository, PostgresRssIngestionRepository>();
            builder.Services.AddScoped<IMetadataCacheStore, PostgresMetadataCacheStore>();
            builder.Services.AddScoped<IOmdbRequestBudget, PostgresOmdbRequestBudget>();
            builder.Services.AddScoped<MetadataResolver>();
            builder.Services.AddScoped<IOscarEnrichmentRepository, PostgresOscarEnrichmentRepository>();
            builder.Services.AddScoped<OscarEnrichmentService>();
            builder.Services.AddScoped<RssIngestionService>();
            builder.Services.AddSingleton<IRssDnsResolver>(dnsResolver);
            builder.Services.AddSingleton(new RssFeedTransport(rssHttpClient, dnsResolver));
            builder.Services.AddScoped<IRssFeedTransport, RssFeedTransportAdapter>();
            builder.Services.AddScoped<IOmdbClient>(serviceProvider => new OmdbClient(
                configuredOmdbHttpClient,
                apiKey,
                requestBudget: serviceProvider.GetRequiredService<IOmdbRequestBudget>(),
                dailyRequestLimit: dailyOmdbRequestLimit,
                oscarDailyRequestLimit: maximumOscarRequestsPerDay));
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
                + $"{result.Summary.FeedsProcessed} feeds, {result.Summary.ErrorCount} errors, "
                + $"{result.Summary.OmdbRequests} OMDb HTTP attempts.");

            OscarEnrichmentSummary? oscarSummary = null;
            if (maximumOscarFilmsPerRun == 0)
            {
                Console.WriteLine("Oscar enrichment skipped: OSCAR_ENRICHMENT_MAX_FILMS_PER_RUN is 0.");
            }
            else
            {
                oscarSummary = await scope.ServiceProvider
                    .GetRequiredService<OscarEnrichmentService>()
                    .RunAsync(maximumOscarFilmsPerRun, applicationLifetime.ApplicationStopping);
                var enrichmentStatus = oscarSummary.StoppedForQuota ? "stopped at quota" : "completed";
                Console.WriteLine(
                    $"Oscar enrichment {enrichmentStatus}: {oscarSummary.AttemptedFilms}/"
                    + $"{oscarSummary.EligibleFilms} candidates, {oscarSummary.EnrichedFilms} enriched, "
                    + $"{oscarSummary.NotFoundFilms} not found, {oscarSummary.TemporaryErrors} temporary errors, "
                    + $"{oscarSummary.CacheHits} cache hits, {oscarSummary.HttpAttempts} OMDb HTTP attempts.");
            }

            return result.Summary.Status == "succeeded"
                && (oscarSummary is null || oscarSummary.TemporaryErrors == 0)
                    ? 0
                    : 1;
        }
        catch (OperationCanceledException) when (applicationLifetime.ApplicationStopping.IsCancellationRequested)
        {
            Console.Error.WriteLine(oscarCsvPath is null ? "Worker cancelled." : "Oscar import cancelled.");
            return CancelledExitCode;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(
                $"{(oscarCsvPath is null ? "Worker" : "Oscar import")} failed ({exception.GetType().Name}).");
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