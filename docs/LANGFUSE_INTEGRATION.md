# Langfuse LLM Observability Integration

Seeker OS optionally integrates with [Langfuse](https://langfuse.com) for
LLM tracing — a visual trace UI and prompt management layer on top of the
built-in SQLite LLM ledger.

## Architecture

The Langfuse stack is deployed as infrastructure in the
[homelab repo](https://github.com/tonyperkins/homelab) at
`docker/langfuse/`. It is not vendored in this repo — Seeker OS connects to
it as a client via URL + API keys, the same way it would connect to Langfuse
Cloud or any other self-hosted instance.

## Quick start (local dev)

**Prerequisites:** Langfuse stack running on the Docker host (milo). See
`docker/langfuse/` in the homelab repo for setup.

**1. App-side observability config:**

```bash
cp config/observability.example.yml config/observability.yml
```

Edit `config/observability.yml`:
```yaml
langfuse:
  enabled: true
  base_url: "http://localhost:3001"   # dev.sh mode (app on host)
  # base_url: "http://langfuse-web:3000"  # Docker mode (app in container)
  # base_url: "https://langfuse.perkinslab.com"  # Caddy reverse proxy
  public_key: ${LANGFUSE_PUBLIC_KEY}
  secret_key: ${LANGFUSE_SECRET_KEY}
  capture_content: false
```

**2. Get API keys from Langfuse:**

1. Open the Langfuse UI (e.g. `http://localhost:3001` or `https://langfuse.perkinslab.com`)
2. Create an admin account, org, and project
3. **Project Settings → API Keys** → copy both keys

**3. Add keys to the app's `.env`:**

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

**4. Reload config:**

Hit **Reload Config** in Settings, or restart the backend. The Langfuse
status chip should flip to **initialized**.

**5. Verify:**

Run one JD analysis or resume generation. Check the Langfuse UI for the trace.

## How it relates to the SQLite ledger

The SQLite LLM ledger (`seeker_os/observability/llm_ledger.py`, landed in #108)
is the **canonical record** for per-call token/latency/cost data. Langfuse is
**purely additive** — it provides a web UI for browsing traces, prompt
management, and evaluation. When Langfuse is disabled (default), there is zero
overhead and zero behavior change. The ledger always works regardless.

## Two modes

1. **Disabled** (default) — no Langfuse SDK import, no network calls, zero overhead
2. **External** — point at any Langfuse instance via URL + API keys:
   - Self-hosted on the homelab Docker host (`docker/langfuse/` in the homelab repo)
   - Langfuse Cloud (`https://cloud.langfuse.com`)
   - Any other self-hosted Langfuse instance

## base_url by environment

| Environment | base_url | Why |
|-------------|----------|-----|
| `dev.sh` (app on host) | `http://localhost:3001` | Host port mapping |
| Docker (app in container) | `http://langfuse-web:3000` | Container DNS on shared network |
| Remote / prod | `https://langfuse.perkinslab.com` | Caddy reverse proxy with TLS |

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

Check that the Langfuse stack is running on the Docker host:
```bash
docker compose -f docker/langfuse/compose.yaml ps   # on milo
```

If running via `dev.sh`, use `http://localhost:3001` as `base_url` — the
container DNS name `langfuse-web` is not resolvable from the host.

### Traces not appearing

1. Check that `enabled: true` in `config/observability.yml`
2. Check that keys are set in `.env` (not empty)
3. Check the backend logs for Langfuse warnings
4. Verify the Langfuse UI is accessible at your configured URL
5. After changing `base_url`, always reload config — the old OTel exporter
   thread is shut down and a new sink is created with the updated URL

### Disabling Langfuse

Set `enabled: false` in `config/observability.yml` and reload config. The sink
becomes a no-op — no SDK calls, no network traffic. The SQLite ledger
continues recording as usual.

### Changing keys or base_url

After changing keys or `base_url`, reload config via the Settings page or
restart the backend. The sink re-initializes with the new configuration.

## Headless init

The Langfuse compose file passes through `LANGFUSE_INIT_*` env vars — set
org/project/user/keys in `docker/langfuse/.env` (homelab repo) and the stack
provisions itself headlessly on first boot. Useful for reproducible deploys.
