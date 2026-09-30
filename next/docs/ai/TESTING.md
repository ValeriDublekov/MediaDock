# Development and Test Strategy

This guide covers only the standalone app under `next/`. See the [AI documentation index](README.md), [architecture](ARCHITECTURE.md), and [local runbook](../../README.md).

## Prerequisites

- .NET 10 SDK for the server solution and its `net10.0` projects.
- Node.js and npm for the React/Vite project. The committed [package lock](../../web/package-lock.json) is used by `npm ci`.
- A running Docker Engine for PostgreSQL integration tests. The integration project uses Testcontainers to start disposable `postgres:17-alpine` containers; no pre-existing database or Compose stack is required. Docker must be able to use that image, pulling it if it is not already available locally.

The .NET unit tests and web tests do not require PostgreSQL, Docker, RSS sources, or OMDb credentials.

## Restore and Build

Run server commands from the repository root. The [solution](../../server/MediaDock.sln) includes the API, Application, Infrastructure, Worker, and both test projects.

```powershell
dotnet restore next/server/MediaDock.sln
dotnet build next/server/MediaDock.sln --no-restore
```

Run web commands from `next/web`:

```powershell
npm ci
npm run lint
npm run test
npm run build
```

The [web package scripts](../../web/package.json) define `lint` as Oxlint, `test` as Vitest with jsdom, and `build` as TypeScript project build followed by Vite build. The web tests use mocked API calls, so they need no running API or database; see the [API client tests](../../web/src/api/client.test.ts), [catalog view tests](../../web/src/features/catalog/CatalogView.test.tsx), and [configuration view test](../../web/src/features/sources/SourceSettingsView.test.tsx).

## .NET Unit Tests

Run from the repository root after solution restore. The [unit-test project](../../server/tests/MediaDock.UnitTests/MediaDock.UnitTests.csproj) has focused xUnit categories:

| Category | Coverage and test data |
| --- | --- |
| `Parsing` | Title parsing edge cases with inline sample titles in [RutrackerTitleParserTests](../../server/tests/MediaDock.UnitTests/RutrackerTitleParserTests.cs). |
| `RssTransport` | RSS/Atom parsing and URL, DNS, redirect, and size limits using inline XML, `FakeHttpHandler`, and `FakeDnsResolver` in [RssFeedTransportTests](../../server/tests/MediaDock.UnitTests/RssFeedTransportTests.cs). |
| `Matching` | Type, year, exclusion, and broadcast-range decisions using inline values and xUnit data in [MatchPolicyTests](../../server/tests/MediaDock.UnitTests/MatchPolicyTests.cs). |

[`OscarEnrichmentServiceTests`](../../server/tests/MediaDock.UnitTests/OscarEnrichmentServiceTests.cs) verifies completed/partial/quota-stopped/failed run outcomes, retry state, and HTTP attempt counts with stubbed metadata lookups.

```powershell
dotnet test next/server/tests/MediaDock.UnitTests/MediaDock.UnitTests.csproj --no-restore
dotnet test next/server/tests/MediaDock.UnitTests/MediaDock.UnitTests.csproj --no-restore --filter "Category=Parsing"
dotnet test next/server/tests/MediaDock.UnitTests/MediaDock.UnitTests.csproj --no-restore --filter "Category=RssTransport"
dotnet test next/server/tests/MediaDock.UnitTests/MediaDock.UnitTests.csproj --no-restore --filter "Category=Matching"
```

## PostgreSQL Integration Tests

Run from the repository root after solution restore. These tests require Docker because they start their own PostgreSQL 17 containers; they do not use the Compose database. The [integration-test project](../../server/tests/MediaDock.IntegrationTests/MediaDock.IntegrationTests.csproj) has these xUnit categories:

| Category | Coverage and test data |
| --- | --- |
| `Persistence` | Applies migrations and checks schema/occurrence uniqueness in [PersistenceTests](../../server/tests/MediaDock.IntegrationTests/PersistenceTests.cs); Oscar tests also verify import/enrichment persistence and the separate run-audit lifecycle in [OscarDatasetImporterTests](../../server/tests/MediaDock.IntegrationTests/OscarDatasetImporterTests.cs) and [OscarEnrichmentRepositoryTests](../../server/tests/MediaDock.IntegrationTests/OscarEnrichmentRepositoryTests.cs). |
| `Ingestion` | Checks idempotency, metadata caching, and partial failures against PostgreSQL. [IngestionTests](../../server/tests/MediaDock.IntegrationTests/IngestionTests.cs) supplies inline RSS/XML and OMDb/JSON responses through `MockProviderHandler` and a synthetic API key; it does not call either service. |
| `Worker` | Checks PostgreSQL advisory-lock coordination with separate contexts in [WorkerConcurrencyTests](../../server/tests/MediaDock.IntegrationTests/WorkerConcurrencyTests.cs). |
| `Api` | Exercises the in-process API with `WebApplicationFactory`, a disposable PostgreSQL database, and inline seeded rows; provider settings coverage verifies database persistence, key redaction, and invalid limit combinations in [CatalogApiTests](../../server/tests/MediaDock.IntegrationTests/CatalogApiTests.cs). |

```powershell
dotnet test next/server/tests/MediaDock.IntegrationTests/MediaDock.IntegrationTests.csproj --no-restore
dotnet test next/server/tests/MediaDock.IntegrationTests/MediaDock.IntegrationTests.csproj --no-restore --filter "Category=Persistence"
dotnet test next/server/tests/MediaDock.IntegrationTests/MediaDock.IntegrationTests.csproj --no-restore --filter "Category=Ingestion"
dotnet test next/server/tests/MediaDock.IntegrationTests/MediaDock.IntegrationTests.csproj --no-restore --filter "Category=Worker"
dotnet test next/server/tests/MediaDock.IntegrationTests/MediaDock.IntegrationTests.csproj --no-restore --filter "Category=Api"
```

Both .NET test projects also contain an untagged `UnitTest1.Test1` placeholder; it does not represent feature coverage.

## External Services

Do not test ingestion by running a Worker scan against live RSS feeds or OMDb. RSS transport tests inject fake HTTP and DNS handlers, and ingestion integration tests intercept both providers with local fixtures. A manual Worker run is an operational scan, not a test; keep verification within the isolated tests described above.

Oscar automated tests use inline CSV data, PostgreSQL Testcontainers, and stubbed OMDb responses. Final operator acceptance still requires an externally obtained Oscar dataset and the API key's confirmed daily quota; neither dataset files nor live credentials belong in the repository or routine test suite.