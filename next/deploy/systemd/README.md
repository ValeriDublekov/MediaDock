# Host Schedule

## LAN API Firewall

The optional `mediadock-next-firewall.service` reads `/etc/default/mediadock-next-firewall`. Create that root-owned host file with `APP_BIND_ADDRESS`, `APP_PORT`, and `TRUSTED_LAN_CIDR` before enabling the unit; use a specific IPv4 bind and the intended trusted subnet. Keep the real host address and subnet out of Git. The unit limits filtering to the configured API destination and must not be treated as authentication.

These host-side systemd units are for a single Ubuntu host. They expect the
application and Compose `worker` service to be installed at
`/opt/mediadock/next`; the Compose service is completed with the local stack in
Step 9. Configure its `.env` there before enabling the timer. The `mediadock`
OS account must be able to access the Docker socket; membership in the `docker`
group grants root-equivalent host access.

The timer runs daily at 03:17 in `Europe/Sofia`. `Persistent=true` requests one
catch-up activation when the host or timer was down across one or more scheduled
times. systemd coalesces the missed daily activations into at most one immediate
run; it does not replay each missed day. The next regular activation remains
the following calendar event. PostgreSQL advisory locking also prevents a
manual one-shot scan from overlapping the scheduled run.

After installing the app and reviewing the host account and paths, an operator
can install and enable the units with:

```sh
sudo install -o root -g root -m 0644 next/deploy/systemd/mediadock-worker.service /etc/systemd/system/mediadock-worker.service
sudo install -o root -g root -m 0644 next/deploy/systemd/mediadock-worker.timer /etc/systemd/system/mediadock-worker.timer
sudo systemctl daemon-reload
sudo systemctl enable --now mediadock-worker.timer
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