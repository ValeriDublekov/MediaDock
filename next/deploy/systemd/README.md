# Host Schedule

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

The deployment unit and Worker share
`/var/lib/mediadock-deploy/mediadock-next-operation.lock`; the persistent lock survives
reboots, and a Worker run is skipped while deployment holds it. Immediately
before stopping the API, deployment writes `/var/lib/mediadock-deploy/deploy-failed`
with the target SHA, last-good SHA, and exact validated dump path. A failed
migration leaves this marker in place; later deployments and Worker runs refuse
to proceed until an operator restores and verifies the previous state.

Install the files and host-only bind configuration, but keep the timer disabled
until the clean-main gate and unit validation have passed:

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