#!/bin/sh
set -eu

# Fail closed before loading a model, strategy, broker, or collector input.
python3 /workspace/docker/paper_hardened_mount_check.py
if [ "${1:-}" = '--module' ]; then
    shift
    exec python3 -m "$@"
fi

test -r /octobot/user/config.json
test -d /octobot/user/profiles
# The OctoBot CLI's -s flag forces simulator mode. No copy, update or tunnel.
exec /opt/venv/bin/OctoBot -s --user-folder /octobot/user --log-folder /octobot/logs "$@"
