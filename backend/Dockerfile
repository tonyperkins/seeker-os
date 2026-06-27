FROM python:3.12-slim AS base

# System dependencies for weasyprint (PDF export) and general build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy backend source and install
COPY backend/ /app/backend/
COPY config/ /app/config/

RUN pip install --no-cache-dir -e /app/backend

# Create data directory (will be overridden by volume mount in compose)
RUN mkdir -p /app/data

EXPOSE 8000

# uvicorn with --app-dir so the package is importable
CMD ["uvicorn", "seeker_os.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/backend"]
