#!/usr/bin/env bash
set -Eeuo pipefail

APP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_ROOT="$APP_ROOT/server"
NODE_IMAGE="${NODE_IMAGE:-node:22-alpine}"
DOTNET_SDK_IMAGE="${DOTNET_SDK_IMAGE:-mcr.microsoft.com/dotnet/sdk:10.0}"
DOCKER_SOCKET="${DOCKER_SOCKET:-/var/run/docker.sock}"

if [[ "$(uname -s)" != "Linux" ]]; then
    printf 'This test gate is intended for the Ubuntu deployment host.\n' >&2
    exit 1
fi

for command_name in docker git; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "$command_name" >&2
        exit 1
    fi
done

CHECKOUT_COMMIT="$(git -C "$APP_ROOT" rev-parse --verify HEAD)"
APP_COMMIT="${DEPLOY_COMMIT:-$CHECKOUT_COMMIT}"
if ! APP_COMMIT="$(git -C "$APP_ROOT" rev-parse --verify "${APP_COMMIT}^{commit}" 2>/dev/null)"; then
    printf 'Invalid deployment commit identifier.\n' >&2
    exit 1
fi
if [[ "$APP_COMMIT" != "$CHECKOUT_COMMIT" ]]; then
    printf 'DEPLOY_COMMIT does not match the checked-out commit.\n' >&2
    exit 1
fi
if [[ -n "$(git -C "$APP_ROOT" status --porcelain --untracked-files=all -- .)" ]]; then
    printf 'The next checkout contains uncommitted changes.\n' >&2
    exit 1
fi
APP_TAG="${APP_COMMIT:0:12}"

if [[ ! -f "$APP_ROOT/web/package-lock.json" || ! -f "$APP_ROOT/compose.yaml" ]]; then
    printf 'The checkout does not contain the expected MediaDock Next files.\n' >&2
    exit 1
fi

if [[ ! "$APP_TAG" =~ ^[[:alnum:]_.-]+$ ]]; then
    printf 'Invalid deployment commit identifier.\n' >&2
    exit 1
fi

docker info >/dev/null
if [[ ! -S "$DOCKER_SOCKET" ]]; then
    printf 'Docker socket not found: %s\n' "$DOCKER_SOCKET" >&2
    exit 1
fi

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TEMP_DIR"' EXIT
mkdir -p "$TEMP_DIR/nuget"

HOST_UID="$(id -u)"
HOST_GID="$(id -g)"
DOCKER_SOCKET_GID="$(stat -c '%g' "$DOCKER_SOCKET")"

run_logged() {
    local name="$1"
    shift
    local log_file="$TEMP_DIR/$name.log"
    local exit_code

    if "$@" >"$log_file" 2>&1; then
        printf '[%s] passed\n' "$name"
        tail -n 12 "$log_file"
    else
        exit_code="$?"
        printf '[%s] failed; last 120 log lines follow\n' "$name" >&2
        tail -n 120 "$log_file" >&2
        return "$exit_code"
    fi
}

printf 'Validating commit %s\n' "$APP_COMMIT"

run_logged web docker run --rm \
    --user "$HOST_UID:$HOST_GID" \
    --env HOME=/tmp/npm-home \
    --env npm_config_cache=/tmp/npm-cache \
    --mount "type=bind,source=$APP_ROOT/web,target=/workspace" \
    --workdir /workspace \
    "$NODE_IMAGE" \
    sh -ec 'npm ci --no-audit --no-fund && npm run lint && npm run test && npm run build'

run_logged dotnet-unit docker run --rm \
    --user "$HOST_UID:$HOST_GID" \
    --env HOME=/tmp/dotnet-home \
    --env DOTNET_CLI_HOME=/tmp/dotnet-home \
    --env NUGET_PACKAGES=/tmp/nuget-packages \
    --mount "type=bind,source=$SERVER_ROOT,target=/workspace/server" \
    --mount "type=bind,source=$TEMP_DIR/nuget,target=/tmp/nuget-packages" \
    --workdir /workspace/server \
    "$DOTNET_SDK_IMAGE" \
    dotnet test tests/MediaDock.UnitTests/MediaDock.UnitTests.csproj --configuration Release

run_logged dotnet-integration docker run --rm \
    --network host \
    --user "$HOST_UID:$HOST_GID" \
    --group-add "$DOCKER_SOCKET_GID" \
    --env HOME=/tmp/dotnet-home \
    --env DOTNET_CLI_HOME=/tmp/dotnet-home \
    --env NUGET_PACKAGES=/tmp/nuget-packages \
    --env DOCKER_HOST=unix:///var/run/docker.sock \
    --env TESTCONTAINERS_HOST_OVERRIDE=127.0.0.1 \
    --env TESTCONTAINERS_RYUK_DISABLED=true \
    --mount "type=bind,source=$SERVER_ROOT,target=/workspace/server" \
    --mount "type=bind,source=$TEMP_DIR/nuget,target=/tmp/nuget-packages" \
    --mount "type=bind,source=$DOCKER_SOCKET,target=/var/run/docker.sock" \
    --workdir /workspace/server \
    "$DOTNET_SDK_IMAGE" \
    dotnet test tests/MediaDock.IntegrationTests/MediaDock.IntegrationTests.csproj --configuration Release

run_logged compose-build env \
    POSTGRES_PASSWORD=validation-only \
    API_IMAGE="mediadock-next-api:validation-$APP_TAG" \
    WORKER_IMAGE="mediadock-next-worker:validation-$APP_TAG" \
    docker compose \
        --project-directory "$APP_ROOT" \
        --env-file /dev/null \
        --project-name mediadock-next-validation \
        --file "$APP_ROOT/compose.yaml" \
        build api worker