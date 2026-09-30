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

Create the ignored environment file once, then replace the sample database password with a local-only value. OMDb credentials and runtime request limits are configured in the web UI after applying migrations and starting the API. Oscar CSV imports do not call OMDb.

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

The Worker is one-shot and excluded from the default stack. It loads the OMDb key and request limits from the database at the start of each run, after acquiring the advisory lock. Apply the latest schema migration, open the Configuration screen, enter the key and the confirmed shared daily quota, and review source settings before explicitly running it. Existing `.env` values for these settings are no longer read; transfer them once through the UI after upgrading. Oscar enrichment is enabled when its per-run film limit is positive:

```powershell
docker compose -f next/compose.yaml --profile worker run --rm worker --trigger manual
```

The systemd schedule uses the same `worker` service with the `schedule` trigger. Configuration settings are read from PostgreSQL on each run, so UI changes apply without editing `.env` or restarting the timer. The shared daily HTTP limit covers RSS and Oscar attempts. The Oscar daily HTTP limit is an additional cap, not a reserved allotment, so RSS may consume the shared cap before Oscar runs. Oscar enrichment requires both a positive per-run film limit and a positive Oscar daily HTTP limit.

PostgreSQL stores the shared total, Oscar count, and provider-quota stop flag by UTC date in `omdb_daily_usage`; it never stores the API key. Every non-cache HTTP attempt reserves a slot before sending, including fallback lookups and retries. Cache hits use no slot. A process failure between reservation and sending can conservatively leave a slot unused. A provider quota response blocks all further HTTP reservations for that UTC day, including after a Worker restart; reaching a configured cap stops the current task. Unprocessed Oscar candidates remain eligible. Worker output reports RSS and Oscar attempt counts separately.

Each enabled Oscar enrichment writes a separate `oscar_enrichment_runs` record; it does not reuse RSS `scan_runs` or `parse_logs`. The record captures the trigger, start/finish timestamps, status, eligible and processed candidates, outcomes, cache hits, actual OMDb HTTP attempts, and a safe error code. Progress is checkpointed after each lookup and saved outcome. An unfinished `running` record can indicate an interrupted process; its counts show the last saved checkpoint. Inspect recent runs and daily budget state with:

```powershell
docker compose -f next/compose.yaml exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB" -c "SELECT id, trigger, started_at, finished_at, status, eligible_films, processed_films, http_attempts, not_found_films, temporary_errors, error_code FROM oscar_enrichment_runs ORDER BY started_at DESC LIMIT 20;"'
docker compose -f next/compose.yaml exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB" -c "SELECT utc_date, total_requests, oscar_requests, provider_quota_exceeded FROM omdb_daily_usage ORDER BY utc_date DESC LIMIT 7;"'
```

A `quota_stopped` run means either a configured local cap was reached or OMDb reported quota exhaustion. `provider_quota_exceeded` distinguishes the provider response from a local cap. For a provider stop, verify the key's quota with OMDb and correct the shared limit in Configuration only to a confirmed value; do not retry within the same UTC day. The provider stop flag blocks further HTTP attempts until the next UTC day, and unprocessed candidates remain queued. A film receiving the provider quota response is deferred until the next UTC day.

### Import Oscar dataset

The source is Kaggle's [The Oscar Award dataset](https://www.kaggle.com/datasets/unanimad/the-oscar-award); its page identifies the dataset as CC0. Download the source file yourself and keep it outside the repository. Record the source URL, retrieval date and dataset version (if published), SHA-256, and `--year-after` value in the operator's import notes; the importer does not store a dataset-version manifest. For example:

```powershell
$sourcePath = "$HOME\Downloads\full_data.csv"
Get-FileHash -Path $sourcePath -Algorithm SHA256
```

Start PostgreSQL and apply the latest schema migration before importing. The Worker can import the compact CSV without an OMDb key. It imports films after 1980 from Best Picture, Directing, Original Screenplay, Adapted Screenplay, and Cinematography only:

```powershell
docker compose -f next/compose.yaml up -d db
docker compose -f next/compose.yaml --profile tools run --rm migrate
& .\next\scripts\prepare-oscar-csv.ps1 -InputPath "$HOME\Downloads\full_data.csv" -OutputPath "$HOME\Downloads\oscar_films_after_1980_compact.csv" -Force
$csvPath = (Resolve-Path "$HOME\Downloads\oscar_films_after_1980_compact.csv").Path
docker compose -f next/compose.yaml --profile worker run --build --rm --volume "${csvPath}:/import/oscar.csv:ro" worker --import-oscar /import/oscar.csv --year-after 1980
```

Import is idempotent, uses the Worker database lock, stores CSV title/year/IMDb ID and nomination data immediately, and does not create torrent occurrences. Existing OMDb metadata is left intact.
Re-import the same or a refreshed dataset with the same command; matching films and nominations are upserted and existing OMDb fields are preserved. Re-import is additive: nominations absent from a later file are not deleted automatically. Worker output reports rows read, created/updated records, and rows skipped by year, category, or missing film data.

## Database backup and restore

The `settings` table stores the OMDb key as plain text. A SQL backup therefore contains the provider credential; protect backup files and their storage with the same care as `.env`, and rotate the key if a backup is exposed.

For the Ubuntu deployment, install `next/deploy/backup.sh` with `next/deploy/systemd/mediadock-next-backup.service` and `next/deploy/systemd/mediadock-next-backup.timer`. It creates a root-only custom-format dump at 03:00 UTC under `/opt/docker/backups/mediadock-next`, validates it with `pg_restore -l`, and keeps the newest 14 daily dumps. The existing Restic job backs up `/opt/docker` afterward. Do not enable this host timer until the production `.env` and Compose paths have been reviewed.

The optional deployment service is documented in `next/deploy/systemd/README.md`.
It fetches only GitHub `main`, runs the clean staging gate, creates a
pre-migration dump, uses versioned images, and checks readiness after startup.
Keep its timer disabled until the manual deployment and rollback procedure have
been reviewed.

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