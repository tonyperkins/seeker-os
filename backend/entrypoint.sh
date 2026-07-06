#!/bin/sh
set -e

# Ensure /app/data/.env exists (symlinked from /app/.env in Dockerfile).
# The data volume is mounted at runtime; the file may not exist on first run.
if [ ! -f /app/data/.env ]; then
    touch /app/data/.env
fi

# Start Xvfb in background for Playwright non-headless Chromium (Vercel
# JS challenge requires non-headless mode). We start Xvfb manually instead
# of using xvfb-run because xvfb-run swallows stdout/stderr, making it
# impossible to see application logs or crash errors in Docker.
if command -v Xvfb >/dev/null 2>&1; then
    export DISPLAY=:99
    # Clean up stale lock files from previous container instance
    rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
    Xvfb :99 -screen 0 1280x720x24 -nolisten tcp &
    # Give Xvfb a moment to start
    sleep 1
fi

exec "$@"
