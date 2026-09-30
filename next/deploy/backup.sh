#!/usr/bin/env bash
set -Eeuo pipefail

app_root=/opt/docker/projects/mediadock-next/next
compose_file="$app_root/compose.yaml"
env_file="$app_root/.env"
backup_dir=/opt/docker/backups/mediadock-next
postgres_image=postgres:17-alpine
lock_file=/run/lock/homeserver-restic.lock
retention_count=14

if [[ "$EUID" -ne 0 ]]; then
    printf 'This backup must run as root.\n' >&2
    exit 1
fi

for command_name in docker flock install mktemp; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "$command_name" >&2
        exit 1
    fi
done

if [[ ! -r "$env_file" ]]; then
    printf 'Production environment file is missing or unreadable.\n' >&2
    exit 1
fi

install -d -o root -g root -m 700 "$backup_dir"
exec 9>"$lock_file"
if ! flock -w 300 9; then
    printf 'Could not acquire the shared Restic backup lock.\n' >&2
    exit 1
fi

compose_args=(--project-name mediadock-next --env-file "$env_file" --file "$compose_file")
db_container="$(docker compose "${compose_args[@]}" ps -q db)"
if [[ -z "$db_container" ]]; then
    printf 'The MediaDock PostgreSQL container is not running.\n' >&2
    exit 1
fi

db_health="$(docker inspect --format '{{.State.Health.Status}}' "$db_container")"
if [[ "$db_health" != healthy ]]; then
    printf 'The MediaDock PostgreSQL container is not healthy: %s\n' "$db_health" >&2
    exit 1
fi

temporary_dump="$(mktemp "$backup_dir/.daily-XXXXXX.dump")"
cleanup() {
    if [[ -n "$temporary_dump" ]]; then
        rm -f -- "$temporary_dump"
    fi
}
trap cleanup EXIT
chmod 600 "$temporary_dump"

docker compose "${compose_args[@]}" exec -T db \
    sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
    > "$temporary_dump"

docker run --rm \
    --mount "type=bind,source=$temporary_dump,target=/backup.dump,readonly" \
    "$postgres_image" pg_restore -l /backup.dump > /dev/null

dump_path="$backup_dir/daily-$(date -u +%Y%m%dT%H%M%SZ).dump"
mv -- "$temporary_dump" "$dump_path"
temporary_dump=''
chown root:root "$dump_path"
chmod 600 "$dump_path"

mapfile -t old_dumps < <(
    find "$backup_dir" -maxdepth 1 -type f -name 'daily-*.dump' -printf '%T@ %p\n' |
        sort -nr |
        awk -v keep="$retention_count" 'NR > keep { sub(/^[^ ]+ /, ""); print }'
)
for old_dump in "${old_dumps[@]}"; do
    rm -f -- "$old_dump"
done

printf 'Created and validated %s\n' "$dump_path"