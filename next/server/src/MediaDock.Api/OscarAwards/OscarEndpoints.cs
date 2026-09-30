using MediaDock.Api.Common;
using Microsoft.AspNetCore.Http.HttpResults;

namespace MediaDock.Api.OscarAwards;

internal static class OscarEndpoints
{
    public static WebApplication MapOscarEndpoints(this WebApplication app)
    {
        app.MapGet("/api/oscars", async Task<Ok<PageResponse<OscarFilmResponse>>> (
            [AsParameters] OscarCatalogQuery query,
            IOscarApiService oscarService,
            CancellationToken cancellationToken) =>
        {
            var result = await oscarService.GetOscarFilmsAsync(query, cancellationToken);
            return TypedResults.Ok(result);
        })
            .WithName("GetOscarFilms")
            .WithSummary("Search and filter Oscar films.")
            .WithDescription("Returns a stable page of Oscar films, newest film year first.")
            .Produces<PageResponse<OscarFilmResponse>>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status400BadRequest);

        app.MapGet("/api/oscars/{id:long}", async Task<Ok<OscarFilmResponse>> (
            long id,
            IOscarApiService oscarService,
            CancellationToken cancellationToken) =>
        {
            var result = await oscarService.GetOscarFilmAsync(id, cancellationToken);
            return TypedResults.Ok(result);
        })
            .WithName("GetOscarFilmById")
            .WithSummary("Get Oscar nominations and metadata for one film.")
            .Produces<OscarFilmResponse>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status404NotFound);

        return app;
    }
}