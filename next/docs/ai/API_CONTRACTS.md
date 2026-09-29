# HTTP API Contracts

This document describes only the API in `next/server`. The root Vite app, Python backend, Firebase/Firestore app, and other legacy applications are separate runtimes. Routes are registered in [Program.cs](../../server/src/MediaDock.Api/Program.cs); see [Architecture](ARCHITECTURE.md) for the cross-layer request flow.

## Routes

| Method and route | Request | Success | Other documented outcomes |
| --- | --- | --- | --- |
| `GET /health/live` | None | `200 HealthResponse` (`Status = "ok"`) | Does not query PostgreSQL. |
| `GET /health/ready` | None | `200 HealthResponse` (`Status = "ready"`) when PostgreSQL is reachable | `503 ProblemDetails` when `CanConnectAsync` is false. |
| `GET /api/catalog` | [CatalogQuery](../../server/src/MediaDock.Api/Catalog/CatalogContracts.cs) | `200 PageResponse<CatalogTitleResponse>` | `400 ValidationProblemDetails` for invalid query values. |
| `GET /api/titles/{id:long}` | Route `id` | `200 TitleDetailsResponse` | `404 ProblemDetails` when the title does not exist. |
| `GET /api/titles/{id:long}/occurrences` | Route `id`, [OccurrencesQuery](../../server/src/MediaDock.Api/Catalog/CatalogContracts.cs) | `200 PageResponse<OccurrenceResponse>` | `400 ValidationProblemDetails`; `404 ProblemDetails` when the title does not exist. |
| `GET /api/sources` | None | `200 IReadOnlyList<SourceResponse>`, ordered by `Name` then `Id` | None declared. |
| `GET /api/sources/{id:long}` | Route `id` | `200 SourceResponse` | `404 ProblemDetails` when the source does not exist. |
| `POST /api/sources` | [CreateSourceRequest](../../server/src/MediaDock.Api/Sources/SourceSettingsContracts.cs) | `201 SourceResponse`, with `Location: /api/sources/{id}` | `400 ValidationProblemDetails`; `409 ProblemDetails` for an existing stable key. |
| `PUT /api/sources/{id:long}` | Route `id`, [UpdateSourceRequest](../../server/src/MediaDock.Api/Sources/SourceSettingsContracts.cs) | `200 SourceResponse` | `400 ValidationProblemDetails`; `404 ProblemDetails`; `409 ProblemDetails` for an existing stable key. |
| `GET /api/settings` | None | `200 SettingsResponse` | None declared. |
| `PUT /api/settings` | [UpdateSettingsRequest](../../server/src/MediaDock.Api/Sources/SourceSettingsContracts.cs) | `200 SettingsResponse` | `400 ValidationProblemDetails`. |
| `GET /api/parse-logs` | [ParseLogQuery](../../server/src/MediaDock.Api/Operations/OperationsContracts.cs) | `200 PageResponse<ParseLogResponse>` | `400 ValidationProblemDetails` for invalid query values. |
| `GET /api/scan-runs` | [ScanRunQuery](../../server/src/MediaDock.Api/Operations/OperationsContracts.cs) | `200 PageResponse<ScanRunResponse>` | `400 ValidationProblemDetails` for invalid query values. This lists history; it does not start a scan. |
| `GET /openapi/v1.json` | None | OpenAPI document in Development only | `MapOpenApi` is registered only in Development. |

The endpoint mappings and response metadata are in [CatalogEndpoints.cs](../../server/src/MediaDock.Api/Catalog/CatalogEndpoints.cs), [SourceSettingsEndpoints.cs](../../server/src/MediaDock.Api/Sources/SourceSettingsEndpoints.cs), [OperationalHistoryEndpoints.cs](../../server/src/MediaDock.Api/Operations/OperationalHistoryEndpoints.cs), and [HealthEndpoints.cs](../../server/src/MediaDock.Api/Health/HealthEndpoints.cs). The integration coverage is in [CatalogApiTests.cs](../../server/tests/MediaDock.IntegrationTests/CatalogApiTests.cs).

## Queries And Validation

All paged query DTOs accept optional `Page` in `1..1,000,000` and `PageSize` in `1..100`; omitted values are `1` and `25`. Invalid annotated values produce a 400 validation problem. Pages use offset pagination; a page past the end returns an empty `Items` list rather than being clamped.

| Query DTO | Additional fields and behavior |
| --- | --- |
| `CatalogQuery` | `Search` (max 200 characters) is trimmed and matched with PostgreSQL `ILIKE` against title and normalized title. `MediaType` is `movie`, `series`, `documentary`, or `short`; `SourceType` is `movie` or `series`; `ContentKind` is `standard`, `documentary`, or `short`. `YearFrom` and `YearTo` each range from 1800 through 2200 and are inclusive; `YearFrom` greater than `YearTo` is a validation error. `Genre` and `Country` are trimmed exact array-membership filters (max 100 characters each). `SourceId` must be at least 1 and matches titles having an occurrence from that source. Supplied filters are combined. |
| `OccurrencesQuery` | Only the common `Page` and `PageSize` fields. |
| `ParseLogQuery` | `SourceId` must be at least 1; `ParsedSuccessfully` and `Ignored` are optional booleans; `RetryState` is `retryable`, `terminal`, or `resolved`; `Search` (max 200 characters) is trimmed and matched with `ILIKE` against raw title, feed name, or parsed title. Supplied filters are combined. |
| `ScanRunQuery` | `Status` is `running`, `succeeded`, `partial`, or `failed`; `Trigger` is `schedule`, `manual`, or `local`. Supplied filters are combined. |

Catalog titles sort by `LastSeenAt` descending, then `Id` descending; occurrences use the same ordering. Parse logs sort by `ProcessedAt` descending, then `Id` descending; scan runs sort by `StartedAt` descending, then `Id` descending. `PageResponse<T>` contains `Items`, `Page`, `PageSize`, `TotalCount`, and `TotalPages`; `TotalPages` is zero for an empty result and otherwise the ceiling of `TotalCount / PageSize`.

## Request DTOs

| DTO | Fields and validation |
| --- | --- |
| `CreateSourceRequest` | `StableKey` is required, max 100, and matches `^[a-z0-9][a-z0-9._-]{0,99}$`; `Name` is required, max 200; `FeedType` is required and is `movie` or `series`; `Url` is required, `[Url]`, max 2048; `IsEnabled` defaults to `true`. In addition to `[Url]`, the service accepts only whitespace-free absolute HTTPS URLs without user-info on `feed.rutracker.cc`. Text inputs are trimmed before persistence. |
| `UpdateSourceRequest` | Same `StableKey`, `Name`, `FeedType`, and `Url` validation as create; `IsEnabled` is a `bool` with no initializer (an omitted JSON value therefore defaults to `false`). The request replaces the source configuration. |
| `UpdateSettingsRequest` | `ExcludedGenres` and `ExcludedCountries` are required arrays of at most 100 values. Each value must be nonblank and at most 100 characters; values are trimmed, de-duplicated case-insensitively, and sorted case-insensitively. `MinMovieRating` and `MinSeriesRating` are each `0..10`; `MinImdbVotes` is `0..1,000,000,000`. |

## Response DTOs

Nullable response fields are marked `?`; collection fields are returned as lists/arrays.

| DTO | Fields |
| --- | --- |
| `HealthResponse` | `Status` |
| `PageResponse<T>` | `Items`, `Page`, `PageSize`, `TotalCount`, `TotalPages` |
| `CatalogTitleResponse` | `Id`, `Title`, `Year?`, `MediaType`, `SourceType?`, `ContentKind?`, `ImdbRating?`, `PosterUrl?`, `Genres`, `Countries`, `LastSeenAt`, `OccurrenceCount` |
| `TitleDetailsResponse` | `Id`, `Title`, `Year?`, `MediaType`, `SourceType?`, `ContentKind?`, `BroadcastRangeStartYear?`, `BroadcastRangeEndYear?`, `BroadcastRangeRaw?`, `ImdbId?`, `ImdbRating?`, `ImdbVotes?`, `Metascore?`, `Genres`, `Countries`, `Director?`, `Plot?`, `PosterUrl?`, `Runtime?`, `Awards?`, `BoxOffice?`, `FirstSeenAt`, `LastSeenAt`, `UpdatedAt`, `OccurrenceCount` |
| `OccurrenceResponse` | `Id`, `TitleId`, `SourceId`, `SourceName`, `SourceItemKey`, `FeedEntryId?`, `TorrentUrl`, `RawTitle`, `SourceFeedName`, `FeedType?`, `SourcePublishedAt?`, `ObservedAt?`, `Quality?`, `RipType?`, `FirstSeenAt`, `LastSeenAt` |
| `SourceResponse` | `Id`, `StableKey`, `Name`, `FeedType`, `Url`, `IsEnabled` |
| `SettingsResponse` | `ExcludedGenres`, `ExcludedCountries`, `MinMovieRating`, `MinSeriesRating`, `MinImdbVotes`, `UpdatedAt?` |
| `ParseLogResponse` | `Id`, `SourceId?`, `SourceName?`, `SourceItemKey?`, `RawTitle`, `FeedName`, `ParsedSuccessfully`, `ParsedTitle?`, `ParsedYear?`, `OmdbStatus`, `Ignored`, `IgnoreReason?`, `ErrorMessage?`, `Decision?`, `ProcessedAt`, `RetryState`, `AttemptCount`, `LastAttemptAt?`, `FeedType?`, `SourcePublishedAt?`, `ObservedAt?`, `EventKind?` |
| `ScanRunResponse` | `Id`, `StartedAt`, `FinishedAt?`, `Status`, `Trigger`, `FeedsProcessed`, `EntriesSeen`, `TitlesCreated`, `OccurrencesCreated`, `CacheHits`, `OmdbRequests`, `IgnoredEntries`, `ErrorCount`, `ErrorSummary` |

When no settings row exists, `GET /api/settings` returns empty exclusion arrays, zero thresholds, and `UpdatedAt = null`.

## Error And Access Semantics

[ApiExceptionHandler.cs](../../server/src/MediaDock.Api/Middleware/ApiExceptionHandler.cs) maps `ApiValidationException` to 400 `ValidationProblemDetails`, `ApiNotFoundException` to 404 `ProblemDetails`, and `ApiConflictException` to 409 `ProblemDetails`, all with `application/problem+json`. Unrecognized exceptions are not mapped by this handler; this document does not promise their response shape. Readiness failure is a separate 503 `ProblemDetails` response.

`Program.cs` does not register authentication or authorization middleware. The source write endpoints explicitly describe requests as unauthenticated and LAN-trusted; do not infer an authentication contract from these routes.