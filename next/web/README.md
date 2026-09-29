# MediaDock Next Web

The React and TypeScript client for the standalone app under `next/`. Start with the [AI documentation index](../docs/ai/README.md); see [architecture](../docs/ai/ARCHITECTURE.md), [testing](../docs/ai/TESTING.md), and the [local runbook](../README.md) for the full-stack setup.

## Local Development

The web client requires Node.js and npm. API-backed development also requires the .NET 10 SDK and local PostgreSQL; use the database and migration setup in the [local runbook](../README.md). From `next/web`:

```powershell
npm ci
npm run dev -- --host 127.0.0.1
```

Vite serves the development UI at `http://127.0.0.1:5173/` by default. The client sends requests to the same-origin `/api` path; [Vite configuration](vite.config.ts) proxies `/api` to `http://localhost:5280`. This target is configured in Vite, not through a `VITE_API_BASE_URL` setting.

After PostgreSQL is running and migrations are applied, start the API from the repository root with its HTTP development profile:

```powershell
dotnet run --project next/server/src/MediaDock.Api/MediaDock.Api.csproj --launch-profile http
```

That profile listens on `http://localhost:5280` and uses the local development connection string. The Compose runbook serves its bundled UI at `http://127.0.0.1:8080/`; use the Vite server above when working with the frontend dev server and hot reload. The UI does not require the Worker, live RSS feeds, or an OMDb key.

## Frontend Checks

Run these from `next/web`; the scripts are defined in [package.json](package.json):

```powershell
npm run lint
npm run test
npm run build
npm run preview
```

`npm run test` runs Vitest in jsdom and uses mocked API responses. Run `npm run build` before `npm run preview`. See the [testing guide](../docs/ai/TESTING.md) for .NET unit and PostgreSQL integration test commands and dependencies.
