using MediaDock.Api.Middleware;
using Microsoft.AspNetCore.Http.HttpResults;

namespace MediaDock.Api.Sources;

internal static class SourceSettingsEndpoints
{
    private const string LanTrustedWriteDescription =
        "LAN-trusted MVP write endpoint. Requests are unauthenticated; do not expose this API beyond a trusted LAN.";

    public static WebApplication MapSourceSettingsEndpoints(this WebApplication app)
    {
        app.MapGet("/api/sources", async Task<Ok<IReadOnlyList<SourceResponse>>> (
            ISourceSettingsApiService service,
            CancellationToken cancellationToken) =>
        {
            var sources = await service.GetSourcesAsync(cancellationToken);
            return TypedResults.Ok(sources);
        })
            .WithName("GetSources")
            .WithSummary("List configured feed sources.")
            .WithDescription("Returns sources ordered by name and ID.")
            .Produces<IReadOnlyList<SourceResponse>>(StatusCodes.Status200OK);

        app.MapGet("/api/sources/{id:long}", async Task<Ok<SourceResponse>> (
            long id,
            ISourceSettingsApiService service,
            CancellationToken cancellationToken) =>
        {
            var source = await service.GetSourceAsync(id, cancellationToken);
            return TypedResults.Ok(source);
        })
            .WithName("GetSourceById")
            .WithSummary("Get one configured feed source.")
            .WithDescription("Returns one source configuration.")
            .Produces<SourceResponse>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status404NotFound);

        app.MapPost("/api/sources", async Task<Created<SourceResponse>> (
            CreateSourceRequest request,
            ISourceSettingsApiService service,
            CancellationToken cancellationToken) =>
        {
            var source = await service.CreateSourceAsync(request, cancellationToken);
            return TypedResults.Created($"/api/sources/{source.Id}", source);
        })
            .WithName("CreateSource")
            .WithSummary("Add a feed source.")
            .WithDescription(LanTrustedWriteDescription)
            .Produces<SourceResponse>(StatusCodes.Status201Created)
            .ProducesProblem(StatusCodes.Status400BadRequest)
            .ProducesProblem(StatusCodes.Status409Conflict);

        app.MapPut("/api/sources/{id:long}", async Task<Ok<SourceResponse>> (
            long id,
            UpdateSourceRequest request,
            ISourceSettingsApiService service,
            CancellationToken cancellationToken) =>
        {
            var source = await service.UpdateSourceAsync(id, request, cancellationToken);
            return TypedResults.Ok(source);
        })
            .WithName("UpdateSource")
            .WithSummary("Replace a feed source's configuration.")
            .WithDescription(LanTrustedWriteDescription)
            .Produces<SourceResponse>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status400BadRequest)
            .ProducesProblem(StatusCodes.Status404NotFound)
            .ProducesProblem(StatusCodes.Status409Conflict);

        app.MapGet("/api/settings", async Task<Ok<SettingsResponse>> (
            ISourceSettingsApiService service,
            CancellationToken cancellationToken) =>
        {
            var settings = await service.GetSettingsAsync(cancellationToken);
            return TypedResults.Ok(settings);
        })
            .WithName("GetSettings")
            .WithSummary("Get application matching settings.")
            .WithDescription("Returns saved settings or their defaults when no settings row exists.")
            .Produces<SettingsResponse>(StatusCodes.Status200OK);

        app.MapPut("/api/settings", async Task<Ok<SettingsResponse>> (
            UpdateSettingsRequest request,
            ISourceSettingsApiService service,
            CancellationToken cancellationToken) =>
        {
            var settings = await service.UpdateSettingsAsync(request, cancellationToken);
            return TypedResults.Ok(settings);
        })
            .WithName("UpdateSettings")
            .WithSummary("Replace application matching settings.")
            .WithDescription(LanTrustedWriteDescription)
            .Produces<SettingsResponse>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status400BadRequest);

        app.MapGet("/api/settings/providers/omdb", async Task<Ok<ProviderSettingsResponse>> (
            ISourceSettingsApiService service,
            CancellationToken cancellationToken) =>
        {
            var settings = await service.GetProviderSettingsAsync(cancellationToken);
            return TypedResults.Ok(settings);
        })
            .WithName("GetOmdbSettings")
            .WithSummary("Get OMDb settings without exposing the API key.")
            .Produces<ProviderSettingsResponse>(StatusCodes.Status200OK);

        app.MapPut("/api/settings/providers/omdb", async Task<Ok<ProviderSettingsResponse>> (
            UpdateProviderSettingsRequest request,
            ISourceSettingsApiService service,
            CancellationToken cancellationToken) =>
        {
            var settings = await service.UpdateProviderSettingsAsync(request, cancellationToken);
            return TypedResults.Ok(settings);
        })
            .WithName("UpdateOmdbSettings")
            .WithSummary("Update OMDb settings and the write-only API key.")
            .WithDescription(LanTrustedWriteDescription)
            .Produces<ProviderSettingsResponse>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status400BadRequest);

        return app;
    }
}