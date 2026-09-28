# MediaDock Next

Standalone local MVP scaffold. It does not depend on or modify the existing app.

## Prerequisites

- .NET 10 SDK
- Node.js and npm
- Docker Compose

## Local setup

From the repository root, copy the example environment file and start PostgreSQL:

```powershell
Copy-Item next/.env.example next/.env
docker compose -f next/compose.yaml up -d --wait
```

Run the API and web client in separate terminals:

```powershell
dotnet run --project next/server/src/MediaDock.Api/MediaDock.Api.csproj --launch-profile http
```

```powershell
npm --prefix next/web run dev
```

The API liveness endpoint is `http://localhost:5280/health/live`; the Vite dev
server forwards `/api/*` requests to it. PostgreSQL is published on loopback
only, with local development credentials from `.env.example`.

Stop PostgreSQL without deleting its data with:

```powershell
docker compose -f next/compose.yaml down
```