#!/bin/bash
set -e

profile_id="local_v5_binance_paper"

if [ ! -f /octobot/tentacles/__init__.py ]; then
    cp -a /octobot/reference_tentacles/. /octobot/tentacles/
fi

if [ ! -f /octobot/user/config.json ]; then
    cp /workspace/docker/v5-binance-paper-config.json /octobot/user/config.json
fi

if [ ! -d "/octobot/user/profiles/${profile_id}" ]; then
    mkdir -p /octobot/user/profiles
    cp -a \
        "/workspace/packages/tentacles/profiles/${profile_id}" \
        /octobot/user/profiles/
fi

exec /bin/bash /workspace/docker/local-entrypoint.sh "$@"
