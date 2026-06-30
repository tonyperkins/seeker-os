FROM python:3.12-slim AS base

# System dependencies for weasyprint (PDF export) and general build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    xvfb \
    xauth \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy backend source and install
COPY backend/ /app/backend/
COPY config/ /app/config/

RUN pip install --no-cache-dir -e "/app/backend[browser]"

# Install Playwright Chromium browser and its system dependencies
RUN playwright install chromium --with-deps

# Create data directory (will be overridden by volume mount in compose)
RUN mkdir -p /app/data

# Symlink .env into the data volume so UI-written keys persist across recreations.
# The entrypoint ensures /app/data/.env exists before the app starts.
RUN ln -sf /app/data/.env /app/.env

# Entrypoint ensures the .env file exists (data volume may be empty on first run)
COPY backend/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "seeker_os.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/backend"]
