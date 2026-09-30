#!/usr/bin/env bash
set -Eeuo pipefail

lock_file=/run/lock/mediadock-next-operation.lock
app_dir=/opt/docker/projects/mediadock-next/next

exec 9>"$lock_file"
if ! flock -n 9; then
    printf 'Another MediaDock operation is already running; Worker skipped.\n'
    exit 0
fi

exec /usr/bin/docker compose \
    --project-name mediadock-next \
    --file "$app_dir/compose.yaml" \
    --profile worker run --rm worker --trigger schedule