#!/bin/bash
set -e

# Overlay the checked-out tentacles on the locally generated package.  The
# generated __init__.py files stay in place while edited source files are
# refreshed on every development run.
cp -a /workspace/packages/tentacles/. /octobot/tentacles/

# Install the local guarded-AI profile once without overwriting later edits made
# through the OctoBot web interface.
if [ ! -d /octobot/user/profiles/local_ai_trading ]; then
    cp -a /workspace/packages/tentacles/profiles/local_ai_trading /octobot/user/profiles/
fi

exec /octobot/docker-entrypoint.sh "$@"
