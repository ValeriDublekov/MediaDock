# Project Context

## Runtime boundary

`next/` is the standalone, unauthenticated local MVP. It must remain bound to loopback and has no runtime dependency on the existing root app; see the [local runbook](../../README.md). This guide documents only the new app. The root app, Python backend, Firebase/Firestore, Google Auth, and GitHub Pages applications are separate; do not treat them as runtime components or contracts of `next/`.

## Stack

- API and Worker: .NET 10 (`net10.0` in the [API project](../../server/src/MediaDock.Api/MediaDock.Api.csproj) and [Worker project](../../server/src/MediaDock.Worker/MediaDock.Worker.csproj)).
- Web UI: React, TypeScript, and Vite ([web package](../../web/package.json)).
- Database: PostgreSQL 17 in [Compose](../../compose.yaml), using the Npgsql EF Core provider in the [Infrastructure project](../../server/src/MediaDock.Infrastructure/MediaDock.Infrastructure.csproj).

## Main directories

- [API](../../server/src/MediaDock.Api/MediaDock.Api.csproj), [Application](../../server/src/MediaDock.Application/MediaDock.Application.csproj), [Infrastructure](../../server/src/MediaDock.Infrastructure/MediaDock.Infrastructure.csproj), and [Worker](../../server/src/MediaDock.Worker/MediaDock.Worker.csproj) are the server projects.
- [Unit tests](../../server/tests/MediaDock.UnitTests/MediaDock.UnitTests.csproj) and [integration tests](../../server/tests/MediaDock.IntegrationTests/MediaDock.IntegrationTests.csproj) are under `next/server/tests/`.
- [Web source](../../web/src/main.tsx) is under `next/web/src/`.
- [Compose configuration](../../compose.yaml) defines the local services; schema migrations are under `next/server/src/MediaDock.Infrastructure/Persistence/Migrations/` as noted in the [runbook](../../README.md).

## Local entrypoint

Start with the [local runbook](../../README.md), which documents prerequisites and the Docker Compose workflow. The [Compose file](../../compose.yaml) runs PostgreSQL and the API, with the Worker available as an explicit one-shot service. The UI is served at `http://127.0.0.1:8080/` when the documented stack is running. Keep operational commands in the runbook rather than duplicating them here.