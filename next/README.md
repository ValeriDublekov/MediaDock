# MediaDock Next

[AI documentation index](docs/ai/README.md)

Standalone local MVP. The app is unauthenticated and must remain bound to loopback; it has no runtime dependency on the existing root app.

## Prerequisites

- .NET 10 SDK
- Node.js and npm
- Docker Compose

## Local Docker setup

Create the ignored environment file once, then replace the sample database password with a local-only value. Set `OMDB_API_KEY` only if you intentionally run a Worker scan; the placeholder is empty.

```powershell
if (-not (Test-Path next/.env)) { Copy-Item next/.env.example next/.env }
```

From the repository root, validate the Compose configuration, start PostgreSQL, apply pending EF Core migrations, then start the API and static React app:

```powershell
docker compose -f next/compose.yaml config
docker compose -f next/compose.yaml up --build -d db
docker compose -f next/compose.yaml run --rm migrate
docker compose -f next/compose.yaml up --build -d api
```

The UI is at `http://127.0.0.1:8080/`; readiness is `http://127.0.0.1:8080/health/ready`, and the catalog API is `http://127.0.0.1:8080/api/catalog`. PostgreSQL's host port is also bound to loopback and defaults to `5432` (override with `POSTGRES_PORT`). The existing `postgres_data` volume is retained across container stops and recreation.

Schema changes are checked in as EF Core migrations under `server/src/MediaDock.Infrastructure/Persistence/Migrations/`. The API does not migrate on startup; run the one-shot `migrate` service after adding a migration and before starting the API.

## Health and logs

```powershell
docker compose -f next/compose.yaml ps
docker compose -f next/compose.yaml logs --tail=100 api db
Invoke-WebRequest http://127.0.0.1:8080/health/ready
Invoke-RestMethod http://127.0.0.1:8080/api/catalog
Invoke-WebRequest http://127.0.0.1:8080/
```

## Worker

The Worker is one-shot and excluded from the default stack. Running it performs a real scan using configured RSS sources and OMDb, so set a valid `OMDB_API_KEY` in the ignored environment file and review source settings before explicitly running it:

```powershell
docker compose -f next/compose.yaml --profile worker run --rm worker --trigger manual
```

The systemd schedule uses the same `worker` service with the `schedule` trigger.

## Database backup and restore

Create a plain SQL backup inside the container, then copy it to the host:

```powershell
docker compose -f next/compose.yaml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > /tmp/mediadock.sql'
docker compose -f next/compose.yaml cp db:/tmp/mediadock.sql .\mediadock.sql
```

Restore into an empty database so existing data is not overwritten:

```powershell
docker compose -f next/compose.yaml cp .\mediadock.sql db:/tmp/mediadock.sql
docker compose -f next/compose.yaml exec -T db sh -c 'createdb -U "$POSTGRES_USER" mediadock_restore'
docker compose -f next/compose.yaml exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" mediadock_restore < /tmp/mediadock.sql'
```

## Stop

Stop the local services without deleting the database volume:

```powershell
docker compose -f next/compose.yaml stop
```