# Dockerization Decisions Log

## Branch
`feat/dockerize` — full Docker containerization of Seeker OS.

## Architecture
- **Two services** via `docker-compose.yml`: `backend` (FastAPI/uvicorn) and `frontend` (Next.js).
- **Build context** is the project root (`.`) for both Dockerfiles, so paths like `frontend/package.json` are correct in COPY commands.
- **No reverse proxy** (nginx/traefik) — ports are mapped directly to the host. This is the simplest setup that works for local/dev. For production behind a domain, add a reverse proxy service.

## Backend Dockerfile (`backend/Dockerfile`)
- **Base image:** `python:3.12-slim` (Python >=3.11 required by pyproject.toml; 3.12 is latest stable).
- **System packages:** `libpango`, `libpangoft2`, `libcairo2`, `libgdk-pixbuf2.0`, `libffi-dev`, `shared-mime-info` — required by `weasyprint` for PDF export.
- **Install:** `pip install -e /app/backend` (editable install so `PROJECT_ROOT` path computation in `config.py` resolves correctly to `/app/`).
- **CMD:** `uvicorn seeker_os.api.app:app --host 0.0.0.0 --port 8000 --app-dir /app/backend`
- **No `--reload`** in production image. For dev, override command in compose or use a dev compose override.

## Frontend Dockerfile (`frontend/Dockerfile`)
- **Multi-stage build:** `node:22-alpine` builder → `node:22-alpine` runner.
- **`NEXT_PUBLIC_API_URL`** is a build-time arg (Next.js bakes public env vars into the client bundle during `next build`). Default: `http://localhost:8000`. Override via compose build arg or `--build-arg`.
- **`npm ci`** for reproducible installs from `package-lock.json`.
- **Non-root user** (`nextjs:nodejs`) in the runner stage for security.
- **Next.js standalone output not used** — the project doesn't enable `output: 'standalone'` in `next.config.ts`. Full `node_modules` and `.next` are copied. If standalone mode is enabled later, the Dockerfile can be slimmed significantly.

## Volumes & Persistence
- `./config:/app/config` — real config files (gitignored) mounted at runtime. Only `*.example.yml` templates are baked into the image.
- `./data:/app/data` — SQLite DB, caches, resumes, logs, and `.env` (symlinked from `/app/.env`). Persisted on host.
- `.env` is **not** bind-mounted directly. Instead, the Dockerfile symlinks `/app/.env` → `/app/data/.env`, and an entrypoint script ensures the file exists on first run. This avoids the "Docker creates a directory when bind-mount source doesn't exist" problem. UI-written keys persist via the data volume.

## Environment Variables
- `CORS_ORIGINS` — set in compose to `http://localhost:3000,http://127.0.0.1:3000` so the frontend can reach the backend. Override for production.
- `NEXT_PUBLIC_API_URL` — passed as build arg to frontend. Defaults to `http://localhost:8000` (browser-accessible URL).
- API keys (`ANTHROPIC_API_KEY`, `KILO_API_KEY`, `RETRIEVAL_API_KEY`) — **dual-path**: passed through from host env via compose `environment:` (takes precedence), or loaded from the mounted `.env` file via `load_dotenv(override=False)` if not in the host env. The settings UI can also write keys to `.env` at runtime via `write_env()`.
- OAuth tokens — stored at `data/.anthropic_oauth.json`, persisted via the `./data` volume mount. Independent of `.env`.
- All other env vars come from the mounted `.env` file.

## .dockerignore
- Excludes `.git`, `.venv`, `node_modules`, `.next`, real config files, data files, logs.
- Real config files (`config/profile.yml`, etc.) are excluded from the build context to prevent personal data in images. Only `*.example.yml` templates are included.
- `frontend/.env.local` excluded — env vars are provided via build args instead.

## Decisions / Assumptions (Best-Guess)

### 1. No dev vs. prod compose split
**Decision:** Single `docker-compose.yml` for simplicity. **Assumption:** This is primarily for local/development use. For production, create a `docker-compose.prod.yml` override with different env vars, no port exposure (behind reverse proxy), etc.

### 1a. Reverse Proxy / Production Deployment
**Decision:** Ports are bound to `127.0.0.1` only — not publicly exposed. A reverse proxy (nginx, Caddy, Traefik) on the host fronts the services. **Assumption:** For production with a domain (e.g. `seeker-os.example.com`), set these in `.env`:
- `NEXT_PUBLIC_API_URL=https://seeker-os.example.com` — browser-facing URL (baked into frontend at build time; requires rebuild)
- `CORS_ORIGINS=https://seeker-os.example.com` — allowed origin for the backend
- `BACKEND_PORT` / `FRONTEND_PORT` — pick non-conflicting ports (the reverse proxy proxies to these localhost ports)

The reverse proxy routes:
- `domain/api/*` → `http://127.0.0.1:BACKEND_PORT` (FastAPI)
- `domain/*` → `http://127.0.0.1:FRONTEND_PORT` (Next.js)

`SERVER_API_URL` stays `http://backend:8000` (internal Docker DNS, unaffected by host port mapping or reverse proxy).

### 2. No health check in compose
**Decision:** Not adding health checks yet. **Assumption:** The `depends_on` in compose only ensures start order, not readiness. For production, add health checks (`/api/health` for backend, `/` for frontend).

### 3. Cross-reference repo not mounted
**Decision:** The cross-reference repo (`~/projects/job-search` per `profile.yml`) is not mounted in Docker. **Assumption:** The cross-reference feature may not work in Docker unless the user mounts the repo path. Users can add a volume mount in compose for this. The path in `profile.yml` would need to point to the container path (e.g., `/job-search`).

### 4. WeasyPrint system deps
**Decision:** Installed `libpango`, `libcairo2`, etc. in the backend image. **Assumption:** These are the correct Debian packages for weasyprint on `python:3.12-slim`. If the PDF export feature is unused, these can be removed to slim the image.

### 5. No `.env` file creation
**Decision:** The `.env` file is mounted as a volume, not created in the image. **Assumption:** The user has a `.env` file in the project root. If not, the backend will warn about unresolved env vars but still start. The compose file will fail to mount a non-existent file — users should `cp .env.example .env` first.

### 6. SQLite not replaced with external DB
**Decision:** SQLite remains in a mounted volume. **Assumption:** Per project rules, SQLite is the chosen DB (single-user, zero-config). Docker doesn't change this. The `data/seeker.db` file persists via the volume mount.

### 7. No Docker-specific config changes
**Decision:** No changes to Python code or config files for Docker. **Assumption:** The existing `PROJECT_ROOT` path computation works correctly when the backend is at `/app/backend/seeker_os/` (resolves to `/app/` as project root). Config and data directories are mounted at the expected paths.
