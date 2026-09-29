using Microsoft.AspNetCore.Http.HttpResults;
using Microsoft.AspNetCore.Mvc;

namespace MediaDock.Api.Health;

internal static class HealthEndpoints
{
    public static WebApplication MapHealthEndpoints(this WebApplication app)
    {
        app.MapGet("/health/live", () => TypedResults.Ok(new HealthResponse("ok")))
            .WithName("HealthLive")
            .WithSummary("Check whether the API process is alive.")
            .WithDescription("Returns success when the API process can handle requests.")
            .Produces<HealthResponse>(StatusCodes.Status200OK);

        app.MapGet("/health/ready", async Task<Results<Ok<HealthResponse>, ProblemHttpResult>> (
            IReadinessService readinessService,
            CancellationToken cancellationToken) =>
        {
            if (await readinessService.IsReadyAsync(cancellationToken))
            {
                return TypedResults.Ok(new HealthResponse("ready"));
            }

            return TypedResults.Problem(new ProblemDetails
            {
                Status = StatusCodes.Status503ServiceUnavailable,
                Title = "Service Unavailable",
                Detail = "The database is not available.",
                Instance = "/health/ready"
            });
        })
            .WithName("HealthReady")
            .WithSummary("Check whether the API can reach PostgreSQL.")
            .WithDescription("Returns a problem response while the database is unavailable.")
            .Produces<HealthResponse>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status503ServiceUnavailable);

        return app;
    }
}