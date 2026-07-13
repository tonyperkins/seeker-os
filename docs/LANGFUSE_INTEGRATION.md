# Langfuse LLM Observability Integration

Seeker OS optionally integrates with [Langfuse](https://langfuse.com) for
LLM tracing — a visual trace UI and prompt management layer on top of the
built-in SQLite LLM ledger.

## Local Stack Runbook — Bring Up Everything

This section covers bringing up the complete stack (Seeker OS + Langfuse)
for local testing. If you've already done the first-time setup, jump to
[Day-to-day](#day-to-day).

### First-time setup

**1. Langfuse stack secrets** (its own `.env`, separate from the app's):

```bash
cd deploy/langfuse
cp .env.example .env
# Replace every placeholder:
#   openssl rand -base64 32   (for secrets)
#   openssl rand -base64 24   (for passwords)
cd ../..
```

**2. App-side observability config:**

```bash
cp config/observability.example.yml config/observability.yml
# Leave enabled: false for now — you flip it after you have keys
```

**3. Bring up the stacks** — order matters:

```bash
docker compose up -d                                    # main stack first — creates the seekeros network
docker compose -f deploy/langfuse/compose.yaml up -d    # then Langfuse (6 containers; ClickHouse takes ~30s)
```

The main stack must come first because the Langfuse compose declares
`seekeros` as an external network. If you ever want Langfuse up without
the app, `docker network create seekeros` substitutes.

**4. Get keys and enable:**

1. Open `http://localhost:3001`, create the admin account, an org, and a project
2. **Project Settings → API Keys** → copy both keys into the main app's `.env`:
   ```
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   ```
3. In `config/observability.yml`: set `enabled: true` (leave `base_url` at its
   default `http://langfuse-web:3000` — that's container DNS on the shared
   network, correct for this setup)
4. Restart the backend or hit **Reload Config** in Settings — the Langfuse
   status chip on the Settings page should flip to **initialized**

**5. Verify:**

Run one JD analysis and check `http://localhost:3001` for the trace.

### Day-to-day

After first-time setup, it's just the two `up -d` commands; keys and config
persist:

```bash
docker compose up -d
docker compose -f deploy/langfuse/compose.yaml up -d
```

Stop Langfuse independently (volumes keep its data):

```bash
docker compose -f deploy/langfuse/compose.yaml down
```

The app degrades gracefully while Langfuse is down — the sink logs a warning
and the SQLite ledger carries on.

### Notes

- **Capture content:** Traces are metadata-only by default. For full
  prompts/responses in the trace UI while testing locally, set
  `capture_content: true` in `observability.yml` and reload. Remember it's
  sending your resume/JD content to the Langfuse containers on your machine.
- **Headless init:** The vendored compose passes through Langfuse's
  `LANGFUSE_INIT_*` env vars — set org/project/user/keys in
  `deploy/langfuse/.env` and the stack provisions itself headlessly on first
  boot. Worth wiring up for public deployment; overkill for local testing.

---

## How it relates to the SQLite ledger

The SQLite LLM ledger (`seeker_os/observability/llm_ledger.py`, landed in #108)
is the **canonical record** for per-call token/latency/cost data. Langfuse is
**purely additive** — it provides a web UI for browsing traces, prompt
management, and evaluation. When Langfuse is disabled (default), there is zero
overhead and zero behavior change. The ledger always works regardless.

## Two modes

1. **Disabled** (default) — no Langfuse SDK import, no network calls, zero overhead
2. **External** — point at any Langfuse instance via URL + API keys:
   - The vendored self-hosted stack (below)
   - Langfuse Cloud (`https://cloud.langfuse.com`)
   - Any other self-hosted Langfuse instance

## Setup: vendored self-hosted stack

### Prerequisites

- Docker and Docker Compose
- The main Seeker OS stack running (or at least the `seekeros` network exists)

### 1. Start the main stack first

The vendored Langfuse stack attaches to the `seekeros` Docker network, which
is created by the main stack's `compose.yaml`. Start the main stack first:

```bash
docker compose up -d
```

Or just create the network manually:

```bash
docker network create seekeros
```

### 2. Configure Langfuse secrets

```bash
cd deploy/langfuse
cp .env.example .env
# Edit .env and replace all placeholder values with generated secrets:
#   openssl rand -base64 32
```

### 3. Start the Langfuse stack

```bash
docker compose -f deploy/langfuse/compose.yaml up -d
```

Wait for all services to be healthy (~30 seconds):

```bash
docker compose -f deploy/langfuse/compose.yaml ps
```

### 4. Create an admin account

Open `http://localhost:3001` (or the port you configured as `LANGFUSE_PORT`).
Follow the first-run setup to create an admin account.

### 5. Create a project and API keys

1. Create a new organization and project
2. Go to **Project Settings → API Keys**
3. Copy the **Public Key** and **Secret Key**

### 6. Configure Seeker OS to use Langfuse

Add the keys to your main `.env`:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

Copy the example config and enable Langfuse:

```bash
cp config/observability.example.yml config/observability.yml
```

Edit `config/observability.yml`:

```yaml
langfuse:
  enabled: true
  base_url: "http://langfuse-web:3000"  # vendored stack container DNS
  public_key: ${LANGFUSE_PUBLIC_KEY}
  secret_key: ${LANGFUSE_SECRET_KEY}
  capture_content: false  # metadata-only by default
```

Reload config via the Settings page or restart the backend.

### 7. Verify

Run a pipeline operation (analyze a job, generate a resume). The trace should
appear in the Langfuse UI within seconds.

## Setup: Langfuse Cloud

1. Sign up at [cloud.langfuse.com](https://cloud.langfuse.com)
2. Create a project and API keys
3. Set `base_url: "https://cloud.langfuse.com"` in `config/observability.yml`
4. Add the keys to `.env` as above

## Privacy: capture_content

By default (`capture_content: false`), traces carry **metadata only**:
- `operation_id`, task name, prompt name/version
- Provider, model, tokens in/out, latency, cost
- Route reason, stop reason

**No** prompt text, response text, job titles, company names, resume content,
or user profile data is sent to Langfuse.

Set `capture_content: true` for local debugging to capture full prompt/response
content. **WARNING**: this sends PII to the Langfuse server. Only enable this
on a self-hosted instance you control, never on Langfuse Cloud with real data.

## Troubleshooting

### "Connection refused" or DNS resolution failure

The default `base_url` (`http://langfuse-web:3000`) uses Docker container DNS.
If you see a DNS resolution failure, the vendored stack isn't running:

```bash
docker compose -f deploy/langfuse/compose.yaml up -d
```

### Traces not appearing

1. Check that `enabled: true` in `config/observability.yml`
2. Check that keys are set in `.env` (not empty)
3. Check the backend logs for Langfuse warnings
4. Verify the Langfuse UI is accessible at your configured URL

### Disabling Langfuse

Set `enabled: false` in `config/observability.yml` and reload config. The sink
becomes a no-op — no SDK calls, no network traffic. The SQLite ledger
continues recording as usual.

### Changing keys or base_url

After changing keys or `base_url`, reload config via the Settings page or
restart the backend. The sink re-initializes with the new configuration.

## Vendored stack maintenance

The vendored compose file at `deploy/langfuse/compose.yaml` is a minimally
modified copy of [Langfuse's official docker-compose.yml](https://github.com/langfuse/langfuse/blob/main/docker-compose.yml).
Modifications:

- Pinned image versions (no `:latest` tags)
- Container/volume names prefixed `seekeros-langfuse-*`
- Host port configurable via `LANGFUSE_PORT` (default 3001)
- Only `langfuse-web` joins the `seekeros` network (external); internal
  services stay on the stack's own default network

To upgrade Langfuse, diff against the upstream compose file and update pinned
image versions. Do not use `:latest` tags.
