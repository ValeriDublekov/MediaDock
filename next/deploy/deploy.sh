#!/usr/bin/env bash
set -Eeuo pipefail

app_root=/opt/docker/projects/mediadock-next
app_dir="$app_root/next"
staging_root=/var/lib/mediadock
state_dir=/var/lib/mediadock-deploy
backup_dir=/opt/docker/backups/mediadock-next
operation_lock="$state_dir/mediadock-next-operation.lock"
state_file="$state_dir/deploy-state"
failure_marker="$state_dir/deploy-failed"
log_file=/var/log/mediadock-next-deploy.log
firewall_config=/etc/default/mediadock-next-firewall
github_url=https://github.com/ValeriDublekov/MediaDock.git
branch=main

: "${APP_BIND_ADDRESS:?Set APP_BIND_ADDRESS in /etc/default/mediadock-next-deploy}"
: "${APP_PORT:?Set APP_PORT in /etc/default/mediadock-next-deploy}"

if [[ ! "$APP_BIND_ADDRESS" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ || "$APP_BIND_ADDRESS" == 0.0.0.0 || "$APP_BIND_ADDRESS" == 127.* ]]; then
    printf 'APP_BIND_ADDRESS must be a specific non-loopback IPv4 address.\n' >&2
    exit 1
fi
if ! ip -o -4 addr show | grep -Fq " inet $APP_BIND_ADDRESS/"; then
    printf 'APP_BIND_ADDRESS is not assigned to a local host interface.\n' >&2
    exit 1
fi
if [[ ! "$APP_PORT" =~ ^[0-9]{1,5}$ ]] || (( 10#$APP_PORT < 1 || 10#$APP_PORT > 65535 )); then
    printf 'APP_PORT must be a valid TCP port.\n' >&2
    exit 1
fi
if [[ ! -r "$firewall_config" ]]; then
    printf 'The active MediaDock firewall config is missing or unreadable.\n' >&2
    exit 1
fi
firewall_address="$(awk -F= '$1 == "APP_BIND_ADDRESS" { print $2; exit }' "$firewall_config")"
firewall_port="$(awk -F= '$1 == "APP_PORT" { print $2; exit }' "$firewall_config")"
if [[ "$firewall_address" != "$APP_BIND_ADDRESS" || "$firewall_port" != "$APP_PORT" ]]; then
    printf 'Deploy bind settings do not match the active API firewall config.\n' >&2
    exit 1
fi

if [[ "$EUID" -ne 0 ]]; then
    printf 'This deployment must run as root.\n' >&2
    exit 1
fi

for command_name in curl docker flock git install ip runuser systemctl; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "$command_name" >&2
        exit 1
    fi
done
if ! systemctl is-enabled --quiet mediadock-next-firewall.service || ! systemctl is-active --quiet mediadock-next-firewall.service; then
    printf 'The MediaDock API firewall unit must be enabled and active before deployment.\n' >&2
    exit 1
fi

if [[ ! -e "$log_file" ]]; then
    install -o root -g root -m 0600 /dev/null "$log_file"
fi
if [[ "$(stat -c '%U:%G %a' "$log_file")" != root:root\ 600 ]]; then
    printf 'The deployment log has unsafe ownership or permissions.\n' >&2
    exit 1
fi

if [[ ! -d "$staging_root" || -L "$staging_root" || "$(stat -c '%U:%G %a' "$staging_root")" != mediadock:mediadock\ 700 ]]; then
    printf 'The private mediadock staging directory is missing or has unsafe ownership.\n' >&2
    exit 1
fi
if [[ ! -d "$state_dir" || -L "$state_dir" || "$(stat -c '%U:%G %a' "$state_dir")" != root:mediadock\ 750 ]]; then
    printf 'The deployment state directory is missing or has unsafe ownership.\n' >&2
    exit 1
fi
if [[ ! -f "$app_dir/.env" || "$(stat -c '%U:%G %a' "$app_dir/.env")" != mediadock:mediadock\ 600 ]]; then
    printf 'The production environment file is missing or has unsafe ownership.\n' >&2
    exit 1
fi
if [[ ! -e "$operation_lock" ]]; then
    install -o root -g mediadock -m 0660 /dev/null "$operation_lock"
fi
lock_identity="$(stat -c '%U:%G:%a' "$operation_lock")"
if [[ "$lock_identity" != root:mediadock:660 || ! -r "$operation_lock" || ! -w "$operation_lock" ]]; then
    printf 'The shared operation lock is not accessible: %s\n' "$operation_lock" >&2
    exit 1
fi

exec 8>"$operation_lock"
if ! flock -n 8; then
    printf 'Another MediaDock operation is already running; deployment skipped.\n'
    exit 0
fi
if [[ -e "$failure_marker" ]]; then
    printf 'A prior deployment failed after the database backup; manual recovery is required.\n' >&2
    exit 1
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

if [[ -n "$(runuser -u mediadock -- git -C "$app_root" status --porcelain --untracked-files=all -- .)" ]]; then
    printf 'The production checkout contains uncommitted changes.\n' >&2
    exit 1
fi

origin_url="$(runuser -u mediadock -- git -C "$app_root" remote get-url origin)"
if [[ "$origin_url" != "$github_url" ]]; then
    printf 'The production checkout origin is not the approved GitHub repository.\n' >&2
    exit 1
fi

old_api_image="$(docker inspect --format '{{.Config.Image}}' mediadock-next-api-1 2>/dev/null || true)"
if [[ -z "$old_api_image" || ! "$old_api_image" =~ :([[:xdigit:]]{12,40})$ ]]; then
    printf 'The running API image is missing a commit-SHA tag.\n' >&2
    exit 1
fi
current_api_sha="${BASH_REMATCH[1]}"
if ! current_api_sha="$(runuser -u mediadock -- git -C "$app_root" rev-parse --verify "${current_api_sha}^{commit}" 2>/dev/null)"; then
    printf 'The running API image SHA is not present in the GitHub checkout.\n' >&2
    exit 1
fi
docker image tag "$old_api_image" "mediadock-next-api:$current_api_sha"
if [[ -f "$state_file" ]]; then
    if [[ "$(stat -c '%U:%G %a' "$state_file")" != root:mediadock\ 640 ]]; then
        printf 'The last successful deployment state has unsafe ownership or permissions.\n' >&2
        exit 1
    fi
    previous_sha="$(awk -F= '$1 == "deployed_sha" { print $2; exit }' "$state_file")"
else
    previous_sha="$current_api_sha"
fi
if [[ ! "$previous_sha" =~ ^[[:xdigit:]]{40}$ ]]; then
    printf 'The last successful deployment SHA is missing or invalid.\n' >&2
    exit 1
fi
if [[ ! -f "$state_file" ]]; then
    current_worker_image="mediadock-next-worker:${current_api_sha:0:12}"
    if ! docker image inspect "$current_worker_image" >/dev/null 2>&1; then
        printf 'The Worker image matching the running API SHA is unavailable.\n' >&2
        exit 1
    fi
    docker image tag "$current_worker_image" "mediadock-next-worker:$current_api_sha"
    state_tmp="$(mktemp "${state_file}.XXXXXX")"
    printf 'deployed_sha=%s\napi_image=mediadock-next-api:%s\nworker_image=mediadock-next-worker:%s\nprevious_sha=%s\nupdated_at=%s\npre_migration_dump=\n' "$current_api_sha" "$current_api_sha" "$current_api_sha" "$current_api_sha" "$(date --iso-8601=seconds)" > "$state_tmp"
    install -o root -g mediadock -m 0640 "$state_tmp" "$state_file"
    rm -f -- "$state_tmp"
fi
runuser -u mediadock -- git -C "$app_root" fetch --prune origin "$branch"
target_sha="$(runuser -u mediadock -- git -C "$app_root" rev-parse "origin/$branch")"
if [[ "$target_sha" == "$previous_sha" ]]; then
    printf '%s deployment skipped; GitHub main is already deployed at %s\n' \
        "$(date --iso-8601=seconds)" "$previous_sha" | tee -a "$log_file"
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
install -o root -g root -m 0600 /dev/null "$gate_log"
if ! runuser -u mediadock -g docker -- env -u DOCKER_CONFIG HOME=/var/lib/mediadock DEPLOY_COMMIT="$target_sha" \
    bash "$staging_dir/next/deploy/test.sh" > "$gate_log" 2>&1; then
    printf 'The clean GitHub staging gate failed for %s.\n' "$target_sha" >&2
    exit 1
fi
runuser -u mediadock -- git -C "$app_root" merge --ff-only "$target_sha"

api_image="mediadock-next-api:$target_sha"
worker_image="mediadock-next-worker:$target_sha"
compose_args=(--project-name mediadock-next --env-file "$app_dir/.env" --file "$app_dir/compose.yaml")
resolved_db="$(docker compose "${compose_args[@]}" port db 5432)"
if [[ ! "$resolved_db" =~ ^127\.0\.0\.1:[0-9]+$ ]]; then
    printf 'The PostgreSQL host bind is not loopback-only: %s\n' "$resolved_db" >&2
    exit 1
fi
env API_IMAGE="$api_image" WORKER_IMAGE="$worker_image" \
    docker compose "${compose_args[@]}" build api worker

backup_started_at="$(date +%s)"
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
dump_mtime="$(stat -c '%Y' "$latest_dump")"
if (( dump_mtime < backup_started_at )); then
    printf 'The database dump was not freshly created for this deployment.\n' >&2
    exit 1
fi
docker run --rm --mount "type=bind,source=$latest_dump,target=/backup.dump,readonly" \
    postgres:17-alpine pg_restore -l /backup.dump > /dev/null
printf '%s pre-migration dump=%s target_sha=%s\n' \
    "$(date --iso-8601=seconds)" "$latest_dump" "$target_sha" | tee -a "$log_file"
marker_tmp="$(mktemp "${failure_marker}.XXXXXX")"
printf 'target_sha=%s\nprevious_sha=%s\npre_migration_dump=%s\ncreated_at=%s\n' \
    "$target_sha" "$previous_sha" "$latest_dump" "$(date --iso-8601=seconds)" > "$marker_tmp"
install -o root -g mediadock -m 0640 "$marker_tmp" "$failure_marker"
rm -f -- "$marker_tmp"

env API_IMAGE="$api_image" WORKER_IMAGE="$worker_image" \
    docker compose "${compose_args[@]}" stop api
env API_IMAGE="$api_image" WORKER_IMAGE="$worker_image" \
    docker compose "${compose_args[@]}" --profile tools run --rm migrate
env API_IMAGE="$api_image" WORKER_IMAGE="$worker_image" \
    docker compose "${compose_args[@]}" up -d --no-build api
systemctl restart mediadock-next-firewall.service

health_url="http://$APP_BIND_ADDRESS:$APP_PORT/health/ready"
curl --fail --silent --show-error --retry 30 --retry-all-errors --retry-delay 2 --max-time 10 \
    "$health_url" -o /dev/null
resolved_api="$(env API_IMAGE="$api_image" WORKER_IMAGE="$worker_image" docker compose "${compose_args[@]}" port api 8080)"
if [[ "$resolved_api" != "$APP_BIND_ADDRESS:$APP_PORT" ]]; then
    printf 'The deployed API bind is unexpected: %s\n' "$resolved_api" >&2
    exit 1
fi

if [[ "$(stat -c '%U:%G %a' "$state_dir")" != root:mediadock\ 750 ]]; then
    printf 'The deployment state directory has unsafe ownership or permissions.\n' >&2
    exit 1
fi
state_tmp="$(mktemp "${state_file}.XXXXXX")"
printf 'deployed_sha=%s\napi_image=%s\nworker_image=%s\nprevious_sha=%s\nupdated_at=%s\n' \
    "$target_sha" "$api_image" "$worker_image" "$previous_sha" "$(date --iso-8601=seconds)" > "$state_tmp"
printf 'pre_migration_dump=%s\n' "$latest_dump" >> "$state_tmp"
install -o root -g mediadock -m 0640 "$state_tmp" "$state_file"
rm -f -- "$state_tmp"
rm -f -- "$failure_marker"

printf '%s deployment succeeded; deployed_sha=%s previous_sha=%s api_image=%s\n' \
    "$(date --iso-8601=seconds)" "$target_sha" "$previous_sha" "$api_image" | tee -a "$log_file"