#!/usr/bin/env bash
set -Eeuo pipefail

state_dir=/var/lib/mediadock-deploy
lock_file="$state_dir/mediadock-next-operation.lock"
app_dir=/opt/docker/projects/mediadock-next/next
state_file="$state_dir/deploy-state"
failure_marker="$state_dir/deploy-failed"
trigger="${1:-schedule}"

if (( $# > 1 )) || [[ "$trigger" != schedule && "$trigger" != manual ]]; then
    printf 'Usage: %s [schedule|manual]\n' "$0" >&2
    exit 2
fi

if [[ -e "$failure_marker" ]]; then
    printf 'A deployment failure requires manual recovery; Worker scan refused.\n' >&2
    exit 1
fi

if [[ ! -r "$state_file" ]]; then
    printf 'No successful deployment state is available for the Worker.\n' >&2
    exit 1
fi
if [[ "$(stat -c '%U:%G %a' "$state_file")" != root:mediadock\ 640 ]]; then
    printf 'The deployment state has unsafe ownership or permissions.\n' >&2
    exit 1
fi

worker_image="$(awk -F= '$1 == "worker_image" { print $2; exit }' "$state_file")"
if [[ ! "$worker_image" =~ ^mediadock-next-worker:[[:xdigit:]]{40}$ ]] || ! /usr/bin/docker image inspect "$worker_image" >/dev/null 2>&1; then
    printf 'The deployed Worker image tag is missing or invalid.\n' >&2
    exit 1
fi
export WORKER_IMAGE="$worker_image"

umask 0007
exec 9>"$lock_file"
lock_identity="$(stat -c '%U:%G:%a' "$lock_file")"
if [[ "$lock_identity" != root:mediadock:660 ]]; then
    printf 'The shared operation lock has unsafe ownership or permissions.\n' >&2
    exit 1
fi
if ! flock -n 9; then
    printf 'Another MediaDock operation is already running; Worker skipped.\n'
    exit 0
fi

exec /usr/bin/docker compose \
    --project-name mediadock-next \
    --file "$app_dir/compose.yaml" \
    --profile worker run --rm worker --trigger "$trigger"