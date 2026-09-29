using MediaDock.Api.Catalog;
using MediaDock.Api.Health;
using MediaDock.Api.Middleware;
using MediaDock.Api.Operations;
using MediaDock.Api.Sources;
using MediaDock.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddOpenApi();
builder.Services.AddValidation();
builder.Services.AddProblemDetails();
builder.Services.AddExceptionHandler<ApiExceptionHandler>();
builder.Services.AddDbContext<MediaDockDbContext>(options =>
	options.UseNpgsql(builder.Configuration.GetConnectionString("MediaDock")
		?? throw new InvalidOperationException("ConnectionStrings:MediaDock must be configured.")));
builder.Services.AddScoped<ICatalogApiService, CatalogApiService>();
builder.Services.AddScoped<ISourceSettingsApiService, SourceSettingsApiService>();
builder.Services.AddScoped<IOperationalHistoryApiService, OperationalHistoryApiService>();
builder.Services.AddScoped<IReadinessService, ReadinessService>();

var app = builder.Build();

app.UseExceptionHandler();
app.UseStatusCodePages();

if (app.Environment.IsDevelopment())
{
	app.MapOpenApi();
}

app.MapHealthEndpoints();
app.MapCatalogEndpoints();
app.MapSourceSettingsEndpoints();
app.MapOperationalHistoryEndpoints();

app.Run();

/// <summary>Entry point exposed for API integration tests.</summary>
public partial class Program;
