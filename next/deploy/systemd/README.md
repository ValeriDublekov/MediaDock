# Host Schedule

## Current Production Deployment (2026-09-30)

The production checkout is `/opt/docker/projects/mediadock-next/next` and
remains deployed at GitHub `main` commit
`753bfe03ddaf2e08f25436a24a0c7bfea467dbf7`. Current GitHub `main` is
`08fbef59a22d56ba8f06ed732c6a948aebba3c70`; its staging gate failed twice in
integration tests (16 failed, 2 passed of 18), so no promotion or migration
occurred. The root-managed gate marker prevents repeated tests for that SHA.
The UI is available to trusted LAN clients at
`http://<server-LAN-IPv4>:8081/`; the actual host address is stored only in
server configuration. The app has no login. PostgreSQL remains bound to
`127.0.0.1:5432`.

- `mediadock-next-deploy.timer` checks for a new GitHub `main` commit every five
	minutes, starting five minutes after boot and then five minutes after each
	check finishes.
- `mediadock-next-backup.timer` is enabled for 03:00 UTC; the existing Restic timer starts at about 03:30 UTC with up to 15 minutes of random delay.
- Step 6 dump/restore/Restic verification passed. The Step 7 dump `daily-20260930T082555Z.dump` is root-only and passed `pg_restore -l`, but inclusion in a later Restic snapshot is not yet confirmed.
- The Worker service is installed, but `mediadock-worker.timer` is not installed or enabled and no scan has run. Step 8 operator approval remains pending.
- LAN readiness/UI/catalog checks returned HTTP 200. Router port-forward and non-LAN denial checks remain unverified.

The installation instructions below describe how to provision or operate the units; this status block records the verified production state.

## LAN API Firewall

The optional `mediadock-next-firewall.service` reads `/etc/default/mediadock-next-firewall`. Create that root-owned host file with `APP_BIND_ADDRESS`, `APP_PORT`, and `TRUSTED_LAN_CIDR` before enabling the unit; use a specific IPv4 bind and the intended trusted subnet. Keep the real host address and subnet out of Git. The unit limits filtering to the configured API destination and must not be treated as authentication.

These host-side systemd units are for a single Ubuntu host. The production
Compose project is installed at `/opt/docker/projects/mediadock-next/next` and
uses its ignored `.env` file. The `mediadock` OS account must be able to access
the Docker socket for the Worker unit; membership in the `docker` group grants
root-equivalent host access.

## Database dump

Install the root-only PostgreSQL dump script and its timer before the existing
Restic timer. The dump runs at 03:00 UTC, writes custom-format archives under
`/opt/docker/backups/mediadock-next`, validates each archive with `pg_restore -l`,
and keeps the newest 14 daily dumps. The existing Restic backup already covers
`/opt/docker`; it starts at 03:30 UTC with its configured randomized delay. Both
jobs use `/run/lock/homeserver-restic.lock` so they do not overlap.

```sh
sudo install -o root -g root -m 0750 next/deploy/backup.sh /usr/local/sbin/mediadock-next-backup
sudo install -o root -g root -m 0644 next/deploy/systemd/mediadock-next-backup.service /etc/systemd/system/mediadock-next-backup.service
sudo install -o root -g root -m 0644 next/deploy/systemd/mediadock-next-backup.timer /etc/systemd/system/mediadock-next-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now mediadock-next-backup.timer
```

Run one dump manually before accepting the schedule:

```sh
sudo systemctl start mediadock-next-backup.service
sudo systemctl status --no-pager mediadock-next-backup.service
```

The dump contains the database-stored OMDb key. Keep the backup directory
root-only and never print the archive or the production `.env`.

## One-Time Baseline Reset (Per Environment)

The schema now has one baseline migration, `20260930122500_InitialRelationalSchema`, replacing the previous six-migration chain. An existing database whose `__EFMigrationsHistory` contains the old migration IDs cannot apply this baseline in place: EF will consider it pending and its table creation will collide with the existing schema. This is an explicit data/schema reset, not a normal deployment migration. The deployment script does not delete the Compose `postgres_data` volume.

Perform this procedure separately for each environment, only after its owner approves the data disposition:

1. Confirm that no required data will be lost or that required data has a reviewed export/import path. Record the target environment and approval; do not infer approval from a successful build or deployment gate.
2. Create a final custom-format PostgreSQL dump with the root-only backup service. Validate it with `pg_restore -l` and verify restoreability in an isolated database. The dump contains the plaintext OMDb key and must remain root-only.
3. Disable that environment's deployment and Worker timers, stop any active deploy/Worker/API writers, and keep the API stopped for the schema operation.
4. Use the separately approved database-administration procedure for that environment to provision an empty database or fresh volume. Retain the old volume and verified dump until application checks pass. Do not use `docker compose down -v` as routine cleanup and do not add volume deletion to `deploy.sh`.
5. Start PostgreSQL from the release containing the new baseline and run the existing one-shot migration profile from the Compose project directory:

	```sh
	cd /opt/docker/projects/mediadock-next/next
	docker compose --project-name mediadock-next --project-directory "$PWD" --env-file "$PWD/.env" --file "$PWD/compose.yaml" --profile tools run --rm migrate
	```

6. Verify that `__EFMigrationsHistory` contains `20260930122500_InitialRelationalSchema`, then start the API and check `/health/ready`, `/api/catalog`, and `/api/oscars`. Confirm the empty catalog responses and that provider settings use singleton `id = 1` before enabling any Worker run.
7. Keep the verified dump and old volume until the API checks and an explicitly approved Worker smoke run succeed. Re-enable only the schedules approved for that environment.

Never point the one-shot migration profile at the old schema as a substitute for this procedure. Persistent production reset was not performed by this code change and still requires separate environment-specific approval.

## Automated deployment

The deployment unit fetches only the exact public GitHub repository
`https://github.com/ValeriDublekov/MediaDock.git` and only its `main` branch.
It creates a clean worktree without `.env`, runs `next/deploy/test.sh`, builds
images tagged with the full commit SHA, creates and validates a database dump
before the migration command, and checks `/health/ready` plus the configured
API bind after startup. It records the deployed SHA in
`/var/lib/mediadock-deploy`; that directory is root-owned and group-readable by
the Worker service account, while its state files remain root-managed. Gate and
deployment logs under `/var/log` are root-only.

After a new version passes the staging gate, database backup, migration, and
readiness check, the deploy script can send a success email over SMTP. A run
with no new commit sends no email. Configure the non-secret settings in
`/etc/default/mediadock-next-deploy`:

```ini
DEPLOY_NOTIFY_TO=recipient@example.net
DEPLOY_NOTIFY_FROM=mediadock@example.net
DEPLOY_SMTP_URL=smtps://smtp.provider.example:465
DEPLOY_SMTP_NETRC_FILE=/etc/mediadock-next-deploy.smtp.netrc
```

The sender must be accepted by the relay. Create the credential file with
`sudo install -o root -g root -m 0600 /dev/null /etc/mediadock-next-deploy.smtp.netrc`,
then edit it with `sudoedit`. Its `machine` value must match the SMTP URL host:

```text
machine smtp.provider.example
login smtp-account
password smtp-app-password
```

Keep real credentials out of Git. The deploy script requires the netrc file to
be a regular root-owned file with mode `600`, and requires TLS for SMTP. If
configuration is missing or sending fails, the successful deployment remains
successful; the outcome is recorded in the root-only deployment log. Email
delivery is best-effort and is not retried automatically.

If the clean staging gate fails, the failing commit SHA is recorded in
`/var/lib/mediadock-deploy/gate-failed`; later five-minute polls skip that SHA
instead of repeating the full test suite. A newer `main` commit is tested
normally. To retry the same commit after fixing a transient host issue, clear
the marker and start the service explicitly:

```sh
sudo rm -f /var/lib/mediadock-deploy/gate-failed
sudo systemctl start mediadock-next-deploy.service
```

The deployment unit and Worker share
`/var/lib/mediadock-deploy/mediadock-next-operation.lock`; the persistent lock survives
reboots, and a Worker run is skipped while deployment holds it. Immediately
before stopping the API, deployment writes `/var/lib/mediadock-deploy/deploy-failed`
with the target SHA, last-good SHA, and exact validated dump path. A failed
migration leaves this marker in place; later deployments and Worker runs refuse
to proceed until an operator restores and verifies the previous state.

For a new host, install the files and host-only bind configuration, but keep
the timer disabled until the clean-main gate and unit validation have passed:

```sh
sudo install -o root -g root -m 0750 next/deploy/deploy.sh /usr/local/sbin/mediadock-next-deploy
sudo install -o root -g root -m 0755 next/deploy/worker-run.sh /usr/local/sbin/mediadock-next-worker
sudo install -o root -g root -m 0644 next/deploy/systemd/mediadock-next-deploy.service /etc/systemd/system/mediadock-next-deploy.service
sudo install -o root -g root -m 0644 next/deploy/systemd/mediadock-next-deploy.timer /etc/systemd/system/mediadock-next-deploy.timer
sudo install -o root -g root -m 0600 next/deploy/systemd/mediadock-next-deploy.env.example /etc/default/mediadock-next-deploy
sudo install -d -o root -g mediadock -m 0750 /var/lib/mediadock-deploy
sudo install -d -o root -g root -m 0700 /var/lib/mediadock-deploy/docker
sudo install -o root -g mediadock -m 0660 /dev/null /var/lib/mediadock-deploy/mediadock-next-operation.lock
sudo systemctl daemon-reload
sudo systemctl is-enabled mediadock-next-deploy.timer || true
```

Replace the placeholder in `/etc/default/mediadock-next-deploy` locally, then
run the service once and inspect its result before enabling the timer:

```sh
sudo systemctl start mediadock-next-deploy.service
sudo systemctl show mediadock-next-deploy.service --property=Result --value
sudo systemctl status --no-pager mediadock-next-deploy.service
```

For a failed migration or health check, disable deployment and Worker schedules,
preserve the logs, and do not start an older API until the pre-migration schema
has been restored. The deployment log records the dump path; the last successful
`deploy-state` remains unchanged until recovery. The failure marker records the
exact dump path and last-good API SHA. Inspect those values before running the
following recovery commands from Bash:

```sh
sudo systemctl disable --now mediadock-next-deploy.timer
sudo systemctl disable --now mediadock-worker.timer 2>/dev/null || true
sudo systemctl stop mediadock-worker.service 2>/dev/null || true
sudo cat /var/lib/mediadock-deploy/deploy-failed
app_dir=/opt/docker/projects/mediadock-next/next
dump=$(sudo awk -F= '$1 == "pre_migration_dump" { print $2; exit }' /var/lib/mediadock-deploy/deploy-failed)
previous_sha=$(sudo awk -F= '$1 == "previous_sha" { print $2; exit }' /var/lib/mediadock-deploy/deploy-failed)
compose=(docker compose --project-name mediadock-next --project-directory "$app_dir" --env-file "$app_dir/.env" --file "$app_dir/compose.yaml")
sudo "${compose[@]}" stop api
sudo docker cp "$dump" mediadock-next-db-1:/tmp/mediadock-rollback.dump
sudo docker exec -u 0 mediadock-next-db-1 chmod 0644 /tmp/mediadock-rollback.dump
sudo "${compose[@]}" exec -T db sh -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB" && pg_restore --exit-on-error -U "$POSTGRES_USER" -d "$POSTGRES_DB" /tmp/mediadock-rollback.dump'
sudo docker exec -u 0 mediadock-next-db-1 rm -f /tmp/mediadock-rollback.dump
sudo env API_IMAGE="mediadock-next-api:$previous_sha" WORKER_IMAGE="mediadock-next-worker:$previous_sha" "${compose[@]}" up -d --no-build api
api_address=$(sudo awk -F= '$1 == "APP_BIND_ADDRESS" { print $2; exit }' /etc/default/mediadock-next-deploy)
api_port=$(sudo awk -F= '$1 == "APP_PORT" { print $2; exit }' /etc/default/mediadock-next-deploy)
curl --fail --silent --show-error "http://$api_address:$api_port/health/ready"
sudo rm -f /var/lib/mediadock-deploy/deploy-failed
```

Confirm the marker values and restore result before removing the marker. Keep
the dump root-only; it contains the database-stored OMDb key. Review database
and API state before re-enabling either schedule.

Only after the manual deployment and rollback materials are reviewed may the
timer be enabled:

```sh
sudo systemctl enable --now mediadock-next-deploy.timer
```

The Worker timer runs at 07:00 and 18:00 in `Europe/Sofia`. `Persistent=true`
requests one catch-up activation when the host or timer was down across one or
more scheduled times. systemd coalesces the missed activations into at most one
immediate run; it does not replay each missed day. PostgreSQL advisory locking
also prevents a manual one-shot scan from overlapping the scheduled run.

After a successful deployment and only after the operator has configured the
OMDb key and confirmed quota, enabled desired feeds, and approved scheduled
scans, install the Worker wrapper and service. Do not install or enable its
timer before those Step 8 conditions are met:

```sh
sudo install -o root -g root -m 0755 next/deploy/worker-run.sh /usr/local/sbin/mediadock-next-worker
sudo install -o root -g root -m 0644 next/deploy/systemd/mediadock-worker.service /etc/systemd/system/mediadock-worker.service
sudo systemctl daemon-reload
```

Only after that acceptance, install and enable the schedule:

```sh
sudo install -o root -g root -m 0644 next/deploy/systemd/mediadock-worker.timer /etc/systemd/system/mediadock-worker.timer
sudo systemctl daemon-reload
sudo systemctl enable --now mediadock-worker.timer
```

Verify both schedules with:

```sh
systemctl list-timers mediadock-next-backup.timer homeserver-restic-backup.timer mediadock-worker.timer
```

To run an intentional production manual scan after Step 8 approval, use the
same wrapper so it shares the deployment lock:

```sh
sudo runuser -u mediadock -g docker -- /usr/local/sbin/mediadock-next-worker manual
```

The systemd service uses the wrapper's default `schedule` trigger. Both paths
run RSS first, then optional Oscar enrichment within the same database lock.
Configure the OMDb key and confirmed shared
daily quota in the web UI before running the Worker; it reads those values and
the Oscar limits from PostgreSQL on each invocation. Existing environment
variables for these values are no longer used. Oscar enrichment is enabled
when both its per-run film limit and daily HTTP cap are positive. The shared
total and Oscar count are persisted by UTC day in PostgreSQL; fallback
requests and retries each consume a slot, while cache hits do not. The Oscar
maximum is not reserved from RSS usage. Check the timer with
`systemctl list-timers mediadock-worker.timer` and service output with
`journalctl -u mediadock-worker.service`.