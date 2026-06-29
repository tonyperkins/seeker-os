#!/bin/sh
set -e

# Ensure /app/data/.env exists (symlinked from /app/.env in Dockerfile).
# The data volume is mounted at runtime; the file may not exist on first run.
if [ ! -f /app/data/.env ]; then
    touch /app/data/.env
fi

# Wrap with Xvfb so Playwright can run in non-headless mode (required for
# Vercel JS challenge resolution). xvfb-run provides a virtual display.
exec xvfb-run --auto-servernum --server-args="-screen 0 1280x720x24" "$@"
