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
`/var/lib/mediadock/deploy-state` and root-only gate/deploy logs under
`/var/log`.

The deployment unit and Worker share
`/run/lock/mediadock-next-operation.lock`; a Worker run is skipped while a
deployment holds the lock. The deployment script does not automatically roll
back after a migration or health failure. It leaves the API stopped or on the
failed version and records the previous image SHA so an operator can choose a
validated restore point.

Install the files and host-only bind configuration, but keep the timer disabled
until the clean-main gate and unit validation have passed:

```sh
sudo install -o root -g root -m 0750 next/deploy/deploy.sh /usr/local/sbin/mediadock-next-deploy
sudo install -o root -g root -m 0750 next/deploy/worker-run.sh /usr/local/sbin/mediadock-next-worker
sudo install -o root -g root -m 0644 next/deploy/systemd/mediadock-next-deploy.service /etc/systemd/system/mediadock-next-deploy.service
sudo install -o root -g root -m 0644 next/deploy/systemd/mediadock-next-deploy.timer /etc/systemd/system/mediadock-next-deploy.timer
sudo install -o root -g root -m 0600 next/deploy/systemd/mediadock-next-deploy.env.example /etc/default/mediadock-next-deploy
sudo install -o root -g mediadock -m 0660 /dev/null /run/lock/mediadock-next-operation.lock
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

For a failed migration or health check, first disable the timer and preserve
the logs. Stop the API, choose the pre-migration `daily-*.dump` that was logged
for that deployment, restore it into the production database with
`pg_restore`, then start the preserved `mediadock-next-api:<previous_sha>` image
and verify readiness. Do not start an older API against a database whose
migration state has not been restored. Review the database and API state before
re-enabling the timer.

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

After installing the app and reviewing the host account and paths, an operator
can install and enable the units with:

```sh
sudo install -o root -g root -m 0644 next/deploy/systemd/mediadock-worker.service /etc/systemd/system/mediadock-worker.service
sudo install -o root -g root -m 0644 next/deploy/systemd/mediadock-worker.timer /etc/systemd/system/mediadock-worker.timer
sudo systemctl daemon-reload
sudo systemctl enable --now mediadock-worker.timer
```

Verify both schedules with:

```sh
systemctl list-timers mediadock-next-backup.timer homeserver-restic-backup.timer mediadock-worker.timer
```

To run an intentional manual scan from the Compose directory, use
`docker compose run --rm worker --trigger manual`. The systemd service passes
`--trigger schedule`. Both paths run RSS first, then optional Oscar enrichment
within the same database lock. Configure the OMDb key and confirmed shared
daily quota in the web UI before running the Worker; it reads those values and
the Oscar limits from PostgreSQL on each invocation. Existing environment
variables for these values are no longer used. Oscar enrichment is enabled
when both its per-run film limit and daily HTTP cap are positive. The shared
total and Oscar count are persisted by UTC day in PostgreSQL; fallback
requests and retries each consume a slot, while cache hits do not. The Oscar
maximum is not reserved from RSS usage. Check the timer with
`systemctl list-timers mediadock-worker.timer` and service output with
`journalctl -u mediadock-worker.service`.