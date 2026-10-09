#!/bin/sh
set -eu
python3 /workspace/docker/v13_trusted_mount_check.py
if [ "${1:-}" != '--module' ]; then
    exit 2
fi
shift
exec python3 -m "$@"
