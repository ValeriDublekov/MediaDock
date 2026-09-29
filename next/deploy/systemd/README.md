# Host Schedule

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
`--trigger schedule`. Both paths use the same ingestion use case and database
lock. Check the timer with `systemctl list-timers mediadock-worker.timer` and
service output with `journalctl -u mediadock-worker.service`.