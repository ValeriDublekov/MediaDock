#!/usr/bin/env bash
set -Eeuo pipefail

app_root=/opt/docker/projects/mediadock-next
app_dir="$app_root/next"
staging_root=/var/lib/mediadock
backup_dir=/opt/docker/backups/mediadock-next
operation_lock=/run/lock/mediadock-next-operation.lock
state_file=/var/lib/mediadock/deploy-state
log_file=/var/log/mediadock-next-deploy.log
github_url=https://github.com/ValeriDublekov/MediaDock.git
branch=main

: "${APP_BIND_ADDRESS:?Set APP_BIND_ADDRESS in /etc/default/mediadock-next-deploy}"
: "${APP_PORT:?Set APP_PORT in /etc/default/mediadock-next-deploy}"

if [[ "$EUID" -ne 0 ]]; then
    printf 'This deployment must run as root.\n' >&2
    exit 1
fi

for command_name in curl docker flock git install runuser; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "$command_name" >&2
        exit 1
    fi
done

install -d -o mediadock -g mediadock -m 750 "$staging_root"
if [[ ! -e "$operation_lock" ]]; then
    install -o root -g mediadock -m 0660 /dev/null "$operation_lock"
fi
if [[ ! -r "$operation_lock" || ! -w "$operation_lock" ]]; then
    printf 'The shared operation lock is not accessible: %s\n' "$operation_lock" >&2
    exit 1
fi

exec 8>"$operation_lock"
if ! flock -n 8; then
    printf 'Another MediaDock operation is already running; deployment skipped.\n'
    exit 0
fi

previous_sha=''
target_sha=''
staging_dir=''
gate_log=''

cleanup() {
    status=$?
    if [[ -n "$staging_dir" && -d "$staging_dir" ]]; then
        runuser -u mediadock -- git -C "$app_root" worktree remove --force "$staging_dir" >/dev/null 2>&1 || true
    fi
    if (( status != 0 )); then
        printf '%s deployment failed; production was not automatically rolled back. old_sha=%s target_sha=%s\n' \
            "$(date --iso-8601=seconds)" "$previous_sha" "$target_sha" | tee -a "$log_file" >&2
        if [[ -n "$gate_log" ]]; then
            tail -n 80 "$gate_log" >&2 || true
        fi
    fi
    exit "$status"
}
trap cleanup EXIT

if [[ -n "$(git -C "$app_root" status --porcelain --untracked-files=all -- .)" ]]; then
    printf 'The production checkout contains uncommitted changes.\n' >&2
    exit 1
fi

origin_url="$(runuser -u mediadock -- git -C "$app_root" remote get-url origin)"
if [[ "$origin_url" != "$github_url" ]]; then
    printf 'The production checkout origin is not the approved GitHub repository.\n' >&2
    exit 1
fi

old_api_image="$(docker inspect --format '{{.Config.Image}}' mediadock-next-api-1 2>/dev/null || true)"
if [[ -f "$state_file" ]]; then
    previous_sha="$(awk -F= '$1 == "deployed_sha" { print $2; exit }' "$state_file")"
fi
if [[ -z "$previous_sha" && "$old_api_image" =~ :([[:xdigit:]]{12,40})$ ]]; then
    previous_sha="${BASH_REMATCH[1]}"
fi
if [[ -z "$previous_sha" ]]; then
    previous_sha="$(runuser -u mediadock -- git -C "$app_root" rev-parse HEAD)"
fi
runuser -u mediadock -- git -C "$app_root" fetch --prune origin "$branch"
target_sha="$(runuser -u mediadock -- git -C "$app_root" rev-parse "origin/$branch")"
if [[ "$target_sha" == "$previous_sha" ]]; then
    printf '%s deployment skipped; GitHub main is already deployed at %s\n' \
        "$(date --iso-8601=seconds)" "$old_sha" | tee -a "$log_file"
    exit 0
fi

target_tag="${target_sha:0:12}"
staging_dir="$staging_root/staging-$target_tag"
if [[ -e "$staging_dir" ]]; then
    printf 'Staging path already exists: %s\n' "$staging_dir" >&2
    exit 1
fi

runuser -u mediadock -- git -C "$app_root" worktree add --detach "$staging_dir" "$target_sha"
if [[ -e "$staging_dir/next/.env" ]]; then
    printf 'The staging checkout contains a production environment file.\n' >&2
    exit 1
fi
if [[ -n "$(runuser -u mediadock -- git -C "$staging_dir" status --porcelain --untracked-files=all -- .)" ]]; then
    printf 'The staging checkout is not clean.\n' >&2
    exit 1
fi

gate_log="/var/log/mediadock-next-gate-$target_tag.log"
install -o mediadock -g mediadock -m 0600 /dev/null "$gate_log"
if ! runuser -u mediadock -- env HOME=/var/lib/mediadock DEPLOY_COMMIT="$target_sha" \
    bash "$staging_dir/next/deploy/test.sh" > "$gate_log" 2>&1; then
    printf 'The clean GitHub staging gate failed for %s.\n' "$target_sha" >&2
    exit 1
fi
chown root:root "$gate_log"
chmod 600 "$gate_log"

runuser -u mediadock -- git -C "$app_root" merge --ff-only "$target_sha"
if [[ -e "$app_dir/.env" && "$(stat -c '%U:%G %a' "$app_dir/.env")" != mediadock:mediadock\ 600 ]]; then
    printf 'The production environment file ownership or mode is unsafe.\n' >&2
    exit 1
fi

if [[ -n "$old_api_image" ]]; then
    docker image tag "$old_api_image" "mediadock-next-api:$previous_sha"
fi

api_image="mediadock-next-api:$target_sha"
worker_image="mediadock-next-worker:$target_sha"
compose_args=(--project-name mediadock-next --env-file "$app_dir/.env" --file "$app_dir/compose.yaml")
env API_IMAGE="$api_image" WORKER_IMAGE="$worker_image" \
    docker compose "${compose_args[@]}" build api worker

systemctl start mediadock-next-backup.service
if [[ "$(systemctl show mediadock-next-backup.service --property=Result --value)" != success ]]; then
    printf 'The pre-migration database backup failed.\n' >&2
    exit 1
fi

latest_dump="$(find "$backup_dir" -maxdepth 1 -type f -name 'daily-*.dump' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)"
if [[ -z "$latest_dump" ]]; then
    printf 'No daily database dump was found before migration.\n' >&2
    exit 1
fi
docker run --rm --mount "type=bind,source=$latest_dump,target=/backup.dump,readonly" \
    postgres:17-alpine pg_restore -l /backup.dump > /dev/null

env API_IMAGE="$api_image" WORKER_IMAGE="$worker_image" \
    docker compose "${compose_args[@]}" stop api
env API_IMAGE="$api_image" WORKER_IMAGE="$worker_image" \
    docker compose "${compose_args[@]}" --profile tools run --rm migrate
env API_IMAGE="$api_image" WORKER_IMAGE="$worker_image" \
    docker compose "${compose_args[@]}" up -d --no-build api

health_url="http://$APP_BIND_ADDRESS:$APP_PORT/health/ready"
curl --fail --silent --show-error --retry 30 --retry-all-errors --retry-delay 2 --max-time 10 \
    "$health_url" -o /dev/null
resolved_api="$(env API_IMAGE="$api_image" WORKER_IMAGE="$worker_image" docker compose "${compose_args[@]}" port api 8080)"
if [[ "$resolved_api" != "$APP_BIND_ADDRESS:$APP_PORT" ]]; then
    printf 'The deployed API bind is unexpected: %s\n' "$resolved_api" >&2
    exit 1
fi

install -d -o root -g root -m 700 "$(dirname "$state_file")"
state_tmp="$(mktemp "${state_file}.XXXXXX")"
printf 'deployed_sha=%s\napi_image=%s\nworker_image=%s\nprevious_sha=%s\nupdated_at=%s\n' \
    "$target_sha" "$api_image" "$worker_image" "$previous_sha" "$(date --iso-8601=seconds)" > "$state_tmp"
install -o root -g root -m 0600 "$state_tmp" "$state_file"
rm -f -- "$state_tmp"

printf '%s deployment succeeded; deployed_sha=%s previous_sha=%s api_image=%s\n' \
    "$(date --iso-8601=seconds)" "$target_sha" "$previous_sha" "$api_image" | tee -a "$log_file"