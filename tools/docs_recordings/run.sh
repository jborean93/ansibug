#!/usr/bin/env bash
# Regenerates docs/images from scenarios/ inside a container so every recording looks the same.
# Usage: tools/docs_recordings/run.sh [scenario ...]   (no names records every scenario)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "${here}/../.." && pwd)"
image=ansibug-docs-recordings

podman build --quiet --tag "${image}" "${here}" >/dev/null
# keep-id maps the host user to the image's node user so written files keep the host owner.
podman run --rm --init \
    --userns=keep-id --user node \
    --security-opt label=disable \
    --volume "${repo}:/repo" \
    --workdir /repo/tools/docs_recordings \
    "${image}" \
    bash -c 'npm ci --no-audit --no-fund --no-update-notifier --loglevel=error && xvfb-run -a -s "-screen 0 2560x1600x24" node record.mjs "$@"' \
    bash "$@"
