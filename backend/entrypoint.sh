#!/bin/sh
set -e

# Ensure /app/data/.env exists (symlinked from /app/.env in Dockerfile).
# The data volume is mounted at runtime; the file may not exist on first run.
if [ ! -f /app/data/.env ]; then
    touch /app/data/.env
fi

exec "$@"
