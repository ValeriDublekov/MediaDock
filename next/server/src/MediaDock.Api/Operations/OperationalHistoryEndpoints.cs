using MediaDock.Api.Catalog;
using MediaDock.Api.Common;
using Microsoft.AspNetCore.Http.HttpResults;

namespace MediaDock.Api.Operations;

internal static class OperationalHistoryEndpoints
{
    public static WebApplication MapOperationalHistoryEndpoints(this WebApplication app)
    {
        app.MapGet("/api/parse-logs", async Task<Ok<PageResponse<ParseLogResponse>>> (
            [AsParameters] ParseLogQuery query,
            IOperationalHistoryApiService service,
            CancellationToken cancellationToken) =>
        {
            var result = await service.GetParseLogsAsync(query, cancellationToken);
            return TypedResults.Ok(result);
        })
            .WithName("GetParseLogs")
            .WithSummary("Search paginated parse-log history.")
            .WithDescription("Returns a stable page of recent parser and ingestion decisions.")
            .Produces<PageResponse<ParseLogResponse>>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status400BadRequest);

        app.MapGet("/api/scan-runs", async Task<Ok<PageResponse<ScanRunResponse>>> (
            [AsParameters] ScanRunQuery query,
            IOperationalHistoryApiService service,
            CancellationToken cancellationToken) =>
        {
            var result = await service.GetScanRunsAsync(query, cancellationToken);
            return TypedResults.Ok(result);
        })
            .WithName("GetScanRuns")
            .WithSummary("List paginated scan history.")
            .WithDescription("Returns a stable page of recent scan summaries; this endpoint does not start scans.")
            .Produces<PageResponse<ScanRunResponse>>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status400BadRequest);

        return app;
    }
}