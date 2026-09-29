using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Mvc;

namespace MediaDock.Api.Middleware;

internal sealed class ApiExceptionHandler(ILogger<ApiExceptionHandler> logger) : IExceptionHandler
{
    public async ValueTask<bool> TryHandleAsync(
        HttpContext httpContext,
        Exception exception,
        CancellationToken cancellationToken)
    {
        ProblemDetails? problemDetails = exception switch
        {
            ApiValidationException validationException => new ValidationProblemDetails(validationException.Errors)
            {
                Status = StatusCodes.Status400BadRequest,
                Title = "One or more validation errors occurred.",
                Instance = httpContext.Request.Path
            },
            ApiNotFoundException notFoundException => new ProblemDetails
            {
                Status = StatusCodes.Status404NotFound,
                Title = "Not Found",
                Detail = notFoundException.Message,
                Instance = httpContext.Request.Path
            },
            ApiConflictException conflictException => new ProblemDetails
            {
                Status = StatusCodes.Status409Conflict,
                Title = "Conflict",
                Detail = conflictException.Message,
                Instance = httpContext.Request.Path
            },
            _ => null
        };

        if (problemDetails is null)
        {
            return false;
        }

        logger.LogWarning(exception, "Handled API request error with status {StatusCode}.", problemDetails.Status);
        httpContext.Response.StatusCode = problemDetails.Status ?? StatusCodes.Status500InternalServerError;
        httpContext.Response.ContentType = "application/problem+json";
        await httpContext.Response.WriteAsJsonAsync(
            problemDetails,
            contentType: "application/problem+json",
            options: null,
            cancellationToken: cancellationToken);
        return true;
    }
}

internal sealed class ApiValidationException(IReadOnlyDictionary<string, string[]> errors) : Exception
{
    public IDictionary<string, string[]> Errors { get; } = new Dictionary<string, string[]>(errors);
}

internal sealed class ApiNotFoundException(string message) : Exception(message);

internal sealed class ApiConflictException(string message) : Exception(message);