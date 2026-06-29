# Seeker OS — Demo Mode Deploy Shape Spec

This document defines the deploy shape for the public, read-only demo. It is a
spec only; it does not add build code. Implementation should follow this shape.

## 1. Goal

Run a public, keyless demo that:
- Shows synthetic data (15 jobs, dossiers, 2 resumes) authored in Phase 1.
- Never loads or exposes real personal configs, API keys, or provider credentials.
- Blocks all mutations by default at the HTTP layer.
- Builds from the same repository as the live app, differentiated only by the
  `DEMO_MODE=true` environment variable.

## 2. Deployment Toggle

The demo is controlled by a single env var:

| Env var | Value | Effect |
|---|---|---|
| `DEMO_MODE` | `true` | Fail-closed read-only demo mode. |
| `DEMO_MODE` | `false` | Normal live mode. |
| `DEMO_MODE` | unset / empty / any other value | Treated as `true` (demo). Only the exact clean string `false` disables demo mode. |

The deploy must set `DEMO_MODE=true` explicitly in the demo runtime. The local
`dev.sh` and `.env.example` set `DEMO_MODE=false` so developers work in live mode.

## 3. Demo Config Layout

When `DEMO_MODE=true`, the backend loads only the fictional persona configs from
`config/demo/`:

- `profile.demo.yml`
- `filters.demo.yml`
- `scoring_rubric.demo.yml`
- `identity_rules.demo.yml`
- `channel_rules.demo.yml`
- `company_research.demo.yml`
- `master_resume.demo.md`
- `accuracy_rules.demo.yml`

It does **not** load:
- `config/profile.yml`, `config/filters.yml`, `config/scoring_rubric.yml`, etc.
- `config/providers.yml` (no LLM providers).
- `config/queries.yml` (no live pipeline queries).
- `config/sources.yml` (no live source adapters).
- `config/blacklist.txt` (blacklist comes from the demo profile).
- Any `.env` secrets.

## 4. Database

In demo mode the backend uses `data/seeker.demo.db` instead of `data/seeker.db`.
The demo DB must be **immutable and pre-baked** into the image. The runtime app
opens it with SQLite `?mode=ro` (read-only) and skips all migrations. This is
enforced at the connection layer, not only at the HTTP guard.

### Build-time seeding

1. Run the seeder at image build time:
   ```bash
   cd backend
   DEMO_MODE=true python3 -m seeker_os.demo.seed
   ```
2. This writes `data/seeker.demo.db` with the 15 synthetic jobs, dossiers, and resumes.
3. Copy `data/seeker.demo.db` into the runtime container at the same path.
4. At runtime, the lifespan opens the DB read-only and does not write to it.

Runtime seeding is **not supported**: if the demo DB is missing at startup, the app
raises an error and exits. This guarantees the demo never mutates its own data,
never requires a writable `data/` directory, and cannot silently degrade into a
live keyless instance.

### Logging

In demo mode logs are emitted to **stdout only**. The `data/` directory does not
need write access. The `/api/logs` endpoint returns an empty list with a note
that logs are stdout-only.

## 5. Mutation Guard

A single FastAPI middleware (`backend/seeker_os/api/demo_guard.py`) blocks all
requests that are not explicitly allowlisted. The allowlist is path-based and
contains only read operations. All `POST`, `PUT`, `PATCH`, `DELETE`, and unknown
`GET` endpoints return `403 Forbidden` with body:

```json
{"detail": "Demo mode is read-only. This action is disabled.", "demo_mode": true}
```

The guard is allowlist-by-default, not method-based. A future endpoint added
without being added to the read-allowlist is automatically denied in demo mode.

Blocked route categories include, but are not limited to:
- Pipeline runs and streaming endpoints (`/api/pipeline/run`, `/api/pipeline/run/stream`, etc.).
- Resume generation and parsing (`/api/resumes/generate`, `/api/resumes/generate/stream`, `/api/resumes/parse`, etc.).
- Job mutations (`/api/jobs`, status changes, apply, reject, skip, delete, override).
- Company research runs (`/api/jobs/{id}/company-research` POST).
- Backup restore (`/api/backup/restore`, `/api/backup/db/restore`).
- Provider/model mutations (`/api/models/providers/{id}`, `/api/models/fetch/{id}`, `/api/models/test/{id}`, `/api/models/anthropic/oauth/*`).
- Settings writes (`/api/profile`, `/api/filters`, `/api/settings/*`, `/api/accuracy-rules`).

## 6. No Live Clients in Demo Mode

The demo image must not instantiate or import any code that resolves API keys or
constructs outbound clients. Current behavior:

- `ModelRouter` is only instantiated when `settings.providers` is non-empty.
- In demo mode `settings.providers` is empty, so no LLM provider clients are built.
- `build_retrieval_adapter` only runs when `company_research.retrieval.type` is set.
- The demo `company_research.demo.yml` sets `type: ""` and `api_key: ""`, so no
  retrieval adapter is built.
- The demo boots cleanly under `env -i DEMO_MODE=true` with no `ANTHROPIC_API_KEY`,
  `KILO_API_KEY`, or `RETRIEVAL_API_KEY` present.

## 7. Frontend

The frontend detects demo mode via `GET /api/demo-mode` and:
- Renders a non-dismissible banner: "Demo mode: read-only synthetic data. Runs,
  edits, uploads, and settings changes are disabled."
- Disables mutation controls: run pipeline, add job, run research, generate resume,
  resume upload, parse, profile save, filter save, and job action buttons.

The frontend is the same build for both live and demo; only the backend flag and
button disabled states change.

## 8. Proposed Image Build

```dockerfile
# Dockerfile.demo
FROM python:3.12-slim

WORKDIR /app

# Install backend
COPY backend ./backend
RUN pip install ./backend

# Install demo configs and seed data
COPY config/demo ./config/demo
COPY backend/seeker_os/demo/fixtures ./backend/seeker_os/demo/fixtures

# Bake the seeded demo DB
ENV DEMO_MODE=true
RUN python3 -m seeker_os.demo.seed

# The frontend static build is served by a separate Next.js container or a CDN.
# The backend only needs the API at runtime.
EXPOSE 8000

CMD ["uvicorn", "seeker_os.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Notes:
- The build context is the whole repo, so a `.dockerignore` is required to make
  the exclusions enforceable. The repo-root `.dockerignore` must exclude:
  - `config/*.yml`, `config/*.txt`, `config/*.md` (real configs)
  - `config/*.example.*` and `config/demo/` are allowlisted and copied explicitly
  - `.env*`, `data/seeker.db`, `data/seeker.demo.db`, `data/*.log`, `data/cache/`,
    `data/retrieval_cache/`, `data/resumes/`, `data/pre-restore-snapshots/`,
    `data/master_resume.*`, `data/.anthropic_oauth.json`, `data/checkpoint.json`
  - `master_resume.md` at the repo root
  - frontend build artifacts (`frontend/.next/`, `frontend/node_modules/`)
- The image should contain only `config/demo/`, the backend code, and the
  pre-baked `data/seeker.demo.db`.

## 9. Proposed Compose Shape

This compose stack includes the backend, the frontend, and a Caddy reverse proxy
that terminates TLS and routes the public domain to the frontend and `/api/*` to
the backend. The backend and frontend are **not** exposed directly; only the
proxy binds the public port.

```yaml
services:
  backend-demo:
    build:
      context: .
      dockerfile: backend/Dockerfile.demo
    environment:
      - DEMO_MODE=true
      - CORS_ORIGINS=https://demo.seeker-os.example.com
    # No ports exposed to the host; only reachable inside the proxy network.
    networks:
      - demo-net

  frontend-demo:
    build:
      context: ./frontend
    environment:
      - NEXT_PUBLIC_API_URL=https://demo.seeker-os.example.com
    # No ports exposed to the host; only reachable inside the proxy network.
    networks:
      - demo-net

  caddy:
    image: caddy:2-alpine
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./Caddyfile.demo:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config
    networks:
      - demo-net
    depends_on:
      - backend-demo
      - frontend-demo

volumes:
  caddy-data:
  caddy-config:

networks:
  demo-net:
```

Example `Caddyfile.demo`:

```caddy
demo.seeker-os.example.com {
    reverse_proxy /api/* backend-demo:8000
    reverse_proxy /* frontend-demo:3000
}
```

## 10. Hosting Considerations

- The backend and frontend services are **not** bound to the host directly.
  Only the Caddy proxy is exposed on ports 80/443.
- Caddy terminates TLS and routes `/api/*` to the backend and everything else to
  the frontend.
- Set `CORS_ORIGINS` to the exact public demo domain only.
- No auth is required for the demo because the backend is read-only at every
  layer (HTTP guard + immutable SQLite + no live clients).
- The demo container does not need a writable `data/` directory. The only
  runtime writes are optional: Caddy TLS state and container logs (stdout).

## 11. Verification Checklist

Before shipping the demo:

- [ ] `DEMO_MODE=true` boots with no `ANTHROPIC_API_KEY`, `KILO_API_KEY`, or `RETRIEVAL_API_KEY`.
- [ ] `GET /api/demo-mode` returns `{"demo_mode": true}`.
- [ ] `GET /api/jobs` returns 15 synthetic jobs.
- [ ] `POST /api/jobs` returns `403`.
- [ ] `POST /api/pipeline/run/stream` returns `403`.
- [ ] `POST /api/resumes/generate/stream` returns `403`.
- [ ] `POST /api/backup/restore` returns `403`.
- [ ] `POST /api/models/anthropic/oauth/callback` returns `403`.
- [ ] Frontend banner is visible and mutation buttons are disabled.
- [ ] No live config files or secrets are present in the image.
- [ ] `data/seeker.demo.db` is opened read-only at runtime (`?mode=ro`).
- [ ] The demo container can run with a read-only root filesystem.
- [ ] `pytest tests/test_demo_mode.py` passes.

## 12. Future Work (out of Phase 3 scope)

- Add a GitHub Action that builds and pushes the demo image on release.
- Add a separate production compose file for the live deployment.
- Add a `/api/health` check that reports `demo_mode`.
- Consider a read-only analytics dashboard for demo visitors.
