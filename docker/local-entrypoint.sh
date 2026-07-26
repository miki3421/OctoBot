#!/bin/bash
set -e

# Keep browser assets and Jinja templates linked to the read-only checkout in
# local development. Pure dashboard edits then become visible without
# restarting the trading runtime.
if [ "${OCTOBOT_WEB_HOT_ASSETS:-false}" = "true" ]; then
    rm -rf \
        /octobot/tentacles/Services/Interfaces/web_interface/static \
        /octobot/tentacles/Services/Interfaces/web_interface/templates
fi

# Overlay the checked-out tentacles on the locally generated package.  The
# generated __init__.py files stay in place while edited source files are
# refreshed on every development run.
cp -a /workspace/packages/tentacles/. /octobot/tentacles/

if [ "${OCTOBOT_WEB_HOT_ASSETS:-false}" = "true" ]; then
    rm -rf \
        /octobot/tentacles/Services/Interfaces/web_interface/static \
        /octobot/tentacles/Services/Interfaces/web_interface/templates
    ln -s \
        /workspace/packages/tentacles/Services/Interfaces/web_interface/static \
        /octobot/tentacles/Services/Interfaces/web_interface/static
    ln -s \
        /workspace/packages/tentacles/Services/Interfaces/web_interface/templates \
        /octobot/tentacles/Services/Interfaces/web_interface/templates
fi

# Install the local guarded-AI profile once without overwriting later edits made
# through the OctoBot web interface.
local_profile_id="${OCTOBOT_LOCAL_PROFILE_ID:-local_ai_trading}"
if [ ! -d "/octobot/user/profiles/${local_profile_id}" ]; then
    cp -a \
        "/workspace/packages/tentacles/profiles/${local_profile_id}" \
        /octobot/user/profiles/
fi

exec /octobot/docker-entrypoint.sh "$@"
