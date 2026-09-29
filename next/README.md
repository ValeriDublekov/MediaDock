# MediaDock Next

[AI documentation index](docs/ai/README.md)

Standalone local MVP. The app is unauthenticated and must remain bound to loopback; it has no runtime dependency on the existing root app.

## Prerequisites

- .NET 10 SDK
- Node.js and npm
- Docker Compose

## Ubuntu Staging Test Gate

Run from the root of `next/` on the Ubuntu staging host, using a clean checkout of a trusted `main` commit:

```bash
DEPLOY_COMMIT="$(git rev-parse HEAD)" bash ./deploy/test.sh
```

The script checks that the requested commit matches `HEAD` and that the `next/` worktree is clean. It derives the app root from its own location, so the same command works after `next/` is split into a standalone repository. Web lint, tests, and build run in a Node container; .NET unit tests run without the Docker socket, and only the Testcontainers integration-test container receives it. That socket grants root-equivalent host access. Temporary PostgreSQL host-port bindings are limited to `127.0.0.1`. The gate uses validation-only Compose values, does not load the production `.env` or mount production volumes, and includes API/Worker image builds. Keep these checks server-side; the existing GitHub Actions workflow remains unchanged.

## Local Docker setup

Create the ignored environment file once, then replace the sample database password with a local-only value. Set `OMDB_API_KEY` only if you intentionally run an RSS Worker scan; Oscar CSV imports do not call OMDb.

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

### Import Oscar dataset

Start PostgreSQL and apply the latest schema migration before importing. The Worker can import the compact CSV without an OMDb key. It imports films after 1980 from Best Picture, Directing, Original Screenplay, Adapted Screenplay, and Cinematography only:

```powershell
docker compose -f next/compose.yaml up -d db
docker compose -f next/compose.yaml --profile tools run --rm migrate
& .\next\scripts\prepare-oscar-csv.ps1 -InputPath "$HOME\Downloads\full_data.csv" -OutputPath "$HOME\Downloads\oscar_films_after_1980_compact.csv" -Force
$csvPath = (Resolve-Path "$HOME\Downloads\oscar_films_after_1980_compact.csv").Path
docker compose -f next/compose.yaml --profile worker run --build --rm --volume "${csvPath}:/import/oscar.csv:ro" worker --import-oscar /import/oscar.csv --year-after 1980
```

Import is idempotent, uses the Worker database lock, stores CSV title/year/IMDb ID and nomination data immediately, and does not create torrent occurrences. Existing OMDb metadata is left intact.

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