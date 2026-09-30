# MediaDock Next

[AI documentation index](docs/ai/README.md)

Standalone local MVP. The app is unauthenticated and defaults to loopback. Any LAN deployment must bind to a specific trusted interface and enforce a matching host firewall allowlist; it has no runtime dependency on the existing root app.

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

Create the ignored environment file once, then replace the sample database password with a local-only value. Before a Worker scan, set `OMDB_API_KEY` and `OMDB_DAILY_REQUEST_LIMIT` to the actual daily quota for that key; the Worker refuses to start without a positive limit. Oscar CSV imports do not call OMDb. To enable Oscar enrichment, set both `OSCAR_ENRICHMENT_MAX_FILMS_PER_RUN` and `OSCAR_ENRICHMENT_MAX_REQUESTS_PER_DAY` to positive values.

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

The UI is at `http://127.0.0.1:8080/`; readiness is `http://127.0.0.1:8080/health/ready`, and the catalog API is `http://127.0.0.1:8080/api/catalog`. `APP_BIND_ADDRESS` defaults to `127.0.0.1`. For a LAN deployment, bind to that host's specific trusted IPv4 address and use a matching `DOCKER-USER` allowlist with a deny rule for other sources. Keep those host-specific values in a root-owned host configuration file, not in Git. Do not use a wildcard bind or expose the API through a proxy. PostgreSQL's host port remains bound to `127.0.0.1` and defaults to `5432` (override with `POSTGRES_PORT`). The existing `postgres_data` volume is retained across container stops and recreation.

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

The Worker is one-shot and excluded from the default stack. It scans configured RSS sources first, then enriches eligible Oscar films when `OSCAR_ENRICHMENT_MAX_FILMS_PER_RUN` is positive. Apply the latest schema migration first, set the actual key quota and Oscar limits in `.env`, and review source settings before explicitly running it:

```powershell
docker compose -f next/compose.yaml --profile worker run --rm worker --trigger manual
```

The systemd schedule uses the same `worker` service with the `schedule` trigger. `OMDB_DAILY_REQUEST_LIMIT` is the required shared cap for all RSS and Oscar HTTP attempts in a UTC day. `OSCAR_ENRICHMENT_MAX_REQUESTS_PER_DAY` adds an Oscar-only maximum; it is not a reserved allotment, so RSS may consume the shared cap before Oscar runs. `OSCAR_ENRICHMENT_MAX_FILMS_PER_RUN` remains a separate candidate cap, and both Oscar limits must be positive to enable Oscar enrichment.

PostgreSQL stores the shared total, Oscar count, and provider-quota stop flag by UTC date in `omdb_daily_usage`; it never stores the API key. Every non-cache HTTP attempt reserves a slot before sending, including fallback lookups and retries. Cache hits use no slot. A process failure between reservation and sending can conservatively leave a slot unused. A provider quota response blocks all further HTTP reservations for that UTC day, including after a Worker restart; reaching a configured cap stops the current task. Unprocessed Oscar candidates remain eligible. Worker output reports RSS and Oscar attempt counts separately.

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