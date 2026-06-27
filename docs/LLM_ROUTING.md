# LLM Routing — Provider & Model Configuration

**Principle:** Seeker OS supports 1 to N providers, each with 1 to N models. Models are
assigned to one of 3 task tiers. The provider layer is abstracted — the rest of the
code never knows which provider or model it's using.

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                    Task Caller                         │
│  (resume gen, accuracy check, onboarding, etc.)       │
└────────────────────┬─────────────────────────────────┘
                     │ calls
                     ▼
┌──────────────────────────────────────────────────────┐
│              Model Router                             │
│  maps task → tier → provider + model                  │
│  resolves per-task overrides                          │
└────────────────────┬─────────────────────────────────┘
                     │ routes to
        ┌────────────┼────────────┐
        │            │            │
┌───────▼──┐  ┌─────▼────┐  ┌───▼──────┐
│ Provider  │  │ Provider  │  │ Provider  │
│   A       │  │   B       │  │   C       │
│ (anthropic)│ │(openai-   │  │(openai-   │
│           │  │ compat)   │  │ compat)   │
│ direct    │  │ Kilo      │  │ Ollama    │
└───────────┘  └───────────┘  └───────────┘
```

## Provider Types

Two provider types, both first-class:

| Type | Interface | Examples |
|---|---|---|
| `anthropic` | Native Anthropic Messages API | Anthropic direct |
| `openai_compatible` | OpenAI Chat Completions API (`/v1/chat/completions`) | Kilo, OpenAI, Ollama, vLLM, LiteLLM, any OpenAI-compat endpoint |

Both implement the same internal interface:

```python
class LLMProvider(Protocol):
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> LLMResponse: ...

    def list_models(self) -> list[ModelInfo]: ...
```

## 3-Tier Model System

| Tier | Name | Tasks | What it needs | Typical model |
|---|---|---|---|---|
| `heavy` | Generation | Resume tailoring, cover letter, application answers | Creative writing quality — output is user-facing prose | Opus (top matches) / Sonnet (standard) |
| `moderate` | Analysis | Onboarding interview, JD analysis, application answer critique, resume parsing | Reasoning — output is structured data/config | Sonnet |
| `light` | Validation | Accuracy checking, claim traceability, metadata extraction, company dossier generation | Speed — follow rules, check constraints, parse text | Haiku |

**Why 3, not 2:** Generation and analysis are both "heavy" but have different quality
requirements. Generation output is prose a hiring manager reads — quality matters
enormously, use the best model. Analysis output is YAML/JSON a machine reads —
reasoning quality matters but creative writing doesn't, a mid-tier model is sufficient.
Lumping them together means either overpaying for analysis or underpowering generation.

## Configuration Schema

### `config/providers.yml` — Provider & Model Configuration

```yaml
# 1 to N providers, each with 1 to N models
# Providers are typed: anthropic (native) or openai_compatible (standard API)

providers:
  # --- Provider 1: Anthropic direct ---
  - id: anthropic_direct
    type: anthropic
    label: "Anthropic Direct"
    api_key: ${ANTHROPIC_API_KEY}        # env var reference
    # base_url optional — defaults to https://api.anthropic.com
    # base_url: "https://api.anthropic.com"
    enabled: true
    models:
      - id: claude-opus-4
        label: "Claude Opus 4"
        context_window: 200000
        max_output: 32000
        tags: [heavy]                    # which tiers this model is suited for
      - id: claude-sonnet-4
        label: "Claude Sonnet 4"
        context_window: 200000
        max_output: 16000
        tags: [heavy, moderate]
      - id: claude-haiku-4
        label: "Claude Haiku 4"
        context_window: 200000
        max_output: 8192
        tags: [light]

  # --- Provider 2: Kilo gateway (OpenAI-compatible) ---
  - id: kilo
    type: openai_compatible
    label: "Kilo Gateway"
    base_url: "https://kilo.gateway/v1"
    api_key: ${KILO_API_KEY}
    enabled: true
    # Auto-fetched models are merged with manually listed ones.
    # Manually listed models can add tags/labels that auto-fetched ones lack.
    auto_fetch_models: true              # fetch available models on startup/sync
    models:
      # Manually tagged models (override or supplement auto-fetched)
      - id: claude-sonnet-4
        label: "Claude Sonnet 4 (via Kilo)"
        tags: [heavy, moderate]
      - id: claude-haiku-4
        label: "Claude Haiku 4 (via Kilo)"
        tags: [light]
      - id: gpt-4o
        label: "GPT-4o"
        tags: [moderate]
      - id: gpt-4o-mini
        label: "GPT-4o mini"
        tags: [light]
      # Auto-fetched models without manual tags get tag: [untagged]
      # User can tag them via CLI or dashboard

  # --- Provider 3: Ollama (local, fully offline) ---
  - id: ollama_local
    type: openai_compatible
    label: "Ollama (Local)"
    base_url: "http://localhost:11434/v1"
    api_key: "ollama"                    # Ollama ignores this but field is required
    enabled: false                       # disabled by default
    auto_fetch_models: true
    models:
      - id: llama3.3
        label: "Llama 3.3 70B"
        tags: [moderate, light]
      - id: qwen2.5
        label: "Qwen 2.5"
        tags: [light]

# --- Tier → model mapping ---
# Each tier maps to a provider + model. Can be overridden per-task.
tiers:
  heavy:
    provider: anthropic_direct
    model: claude-opus-4
    # Fallback: if this provider/model is unavailable, use this
    fallback:
      provider: kilo
      model: claude-sonnet-4

  moderate:
    provider: kilo
    model: claude-sonnet-4
    fallback:
      provider: anthropic_direct
      model: claude-sonnet-4

  light:
    provider: kilo
    model: claude-haiku-4
    fallback:
      provider: ollama_local
      model: qwen2.5

# --- Per-task overrides (optional) ---
# If a task isn't listed here, it uses its tier's default.
# This allows fine-grained control: e.g., use Opus for high-value resume gen
# but Sonnet for standard resume gen.
tasks:
  resume_generation:
    tier: heavy                          # uses heavy tier default
  resume_generation_high_value:
    tier: heavy
    provider: anthropic_direct           # override: always Opus for top matches
    model: claude-opus-4
  resume_generation_standard:
    tier: heavy
    provider: kilo                       # override: Sonnet via Kilo for standard
    model: claude-sonnet-4
  accuracy_validation:
    tier: light
  onboarding_interview:
    tier: moderate
  cover_letter_generation:
    tier: heavy
  application_answer_generation:
    tier: heavy
  application_answer_critique:
    tier: moderate
  jd_analysis:
    tier: moderate
  company_dossier_generation:
    tier: light
  metadata_extraction:
    tier: light
  resume_parsing:
    tier: moderate
```

### Environment Variables

API keys are referenced as `${ENV_VAR_NAME}` in the YAML and resolved at load time.
Never hardcode keys in config files. The `.example.yml` uses placeholder env var names.

```bash
# .env (gitignored)
ANTHROPIC_API_KEY=sk-ant-...
KILO_API_KEY=sk-...
```

## Model Auto-Discovery

### How It Works

Both provider types support model listing:

| Provider type | Endpoint | Notes |
|---|---|---|
| `anthropic` | `GET https://api.anthropic.com/v1/models` | Returns available Claude models |
| `openai_compatible` | `GET {base_url}/models` | Standard OpenAI endpoint. Works with Kilo, Ollama, vLLM, etc. |

```python
@dataclass
class ModelInfo:
    id: str                    # model identifier for API calls
    label: str                 # human-readable name
    provider_id: str           # which provider owns this
    context_window: int | None # max context (if reported)
    tags: list[str]            # tier tags: heavy, moderate, light, untagged
    source: str                # 'manual' (in config) or 'auto' (fetched)
    available: bool            # is it currently available?


def fetch_available_models(provider: LLMProvider) -> list[ModelInfo]:
    """Fetch available models from a provider.

    For anthropic: GET /v1/models
    For openai_compatible: GET {base_url}/models

    Returns list of ModelInfo with source='auto'.
    Merges with manually configured models:
      - If model ID exists in config: update availability, keep manual tags/label
      - If model ID is new: add with tags=['untagged'], source='auto'
      - If manual model not in API response: mark available=False (don't delete)
    """
```

### CLI Model Management

```bash
# List all providers and their models
python -m seeker_os.main models list

# List models for a specific provider
python -m seeker_os.main models list --provider kilo

# Search available models (across all providers or one)
python -m seeker_os.main models search "claude"
python -m seeker_os.main models search "gpt-4" --provider kilo
python -m seeker_os.main models search "haiku" --tag light

# Fetch/update models from provider APIs
python -m seeker_os.main models fetch --provider kilo
python -m seeker_os.main models fetch --all

# Tag a model for a tier
python -m seeker_os.main models tag claude-opus-4 --provider anthropic_direct --tier heavy

# Set tier mapping
python -m seeker_os.main models set-tier heavy --provider anthropic_direct --model claude-opus-4

# Test a provider connection
python -m seeker_os.main models test --provider kilo
```

### Search Feature

Kilo (and similar gateways) expose hundreds of models. The search feature helps users
find the right one without scrolling a massive list.

**CLI search:**
```bash
$ python -m seeker_os.main models search "sonnet" --provider kilo

Models matching 'sonnet' on kilo:
  ID                          Label                        Tags
  claude-3-5-sonnet           Claude 3.5 Sonnet            [moderate]
  claude-3-5-sonnet-v2        Claude 3.5 Sonnet v2         [moderate]
  claude-sonnet-4             Claude Sonnet 4              [heavy, moderate]
  claude-sonnet-4-0520        Claude Sonnet 4 (May 2025)   [untagged]

  Use 'models tag <id> --provider kilo --tier <tier>' to assign a tier.
```

**Dashboard search (Phase 2):**
- Search box with live filtering
- Filter by provider, tier tag, or text match
- Columns: model ID, label, provider, tags, context window, availability
- Click to tag or assign to tier
- "Fetch models" button per provider to refresh

### Model Caching

Auto-fetched models are cached to avoid hitting the API on every startup:

```
data/
├── seeker.db
├── cache/
│   └── models/                    # model list cache
│       ├── anthropic_direct.json  # cached model list + fetch timestamp
│       └── kilo.json
└── ...
```

Cache TTL: 24 hours (configurable). `models fetch` command forces refresh.

## Provider Abstraction (Internal)

```python
# backend/seeker_os/llm/provider.py

class LLMProvider(Protocol):
    """Abstract LLM provider interface."""

    @property
    def id(self) -> str: ...
    @property
    def type(self) -> str: ...         # 'anthropic' or 'openai_compatible'

    def generate(self, request: LLMRequest) -> LLMResponse: ...
    def list_models(self) -> list[ModelInfo]: ...
    def test_connection(self) -> bool: ...


@dataclass
class LLMRequest:
    system_prompt: str
    user_prompt: str
    model: str
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


# backend/seeker_os/llm/anthropic_provider.py
class AnthropicProvider:
    """Direct Anthropic API provider using native Messages API."""
    ...


# backend/seeker_os/llm/openai_compat_provider.py
class OpenAICompatProvider:
    """OpenAI-compatible provider (Kilo, Ollama, vLLM, etc.)."""
    ...


# backend/seeker_os/llm/router.py
class ModelRouter:
    """Routes tasks to the correct provider + model based on config."""

    def __init__(self, config: LLMConfig):
        self.providers: dict[str, LLMProvider] = {}
        self.tiers: dict[str, TierMapping] = config.tiers
        self.tasks: dict[str, TaskMapping] = config.tasks

    def resolve(self, task: str) -> tuple[LLMProvider, str]:
        """Resolve a task name to (provider, model).

        1. Check tasks[task] for per-task override
        2. Fall back to tier default
        3. If provider/model unavailable, use fallback
        4. If fallback also unavailable, raise
        """

    def generate(self, task: str, system_prompt: str, user_prompt: str,
                 **kwargs) -> LLMResponse:
        """Generate a response for a given task."""
        provider, model = self.resolve(task)
        return provider.generate(LLMRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            **kwargs
        ))
```

## Multi-Resume Future-Proofing

The config schema supports multiple resumes without Phase 1 changes:

```yaml
# Phase 1 (single resume) — config/profile.yml
resume:
  master_path: "data/master_resume.md"
  accuracy_rules_path: "config/accuracy_rules.yml"

# Future (multiple resumes) — same file, just a list
resumes:
  - id: default
    label: "Your Target Role"
    master_path: "data/master_resume.md"
    accuracy_rules_path: "config/accuracy_rules.yml"
    model_tier: heavy                   # per-resume model selection
  - id: platform
    label: "Platform Engineering"
    master_path: "~/resumes/Platform_Engineer_Resume.md"
    accuracy_rules_path: "config/accuracy_rules_platform.yml"
    model_tier: heavy
```

**Implementation approach:** The config loader accepts either `resume:` (single) or
`resumes:` (list). Internally, code always works with a list. In Phase 1, the list has
one entry. Zero extra effort now, no rewrite later.

Per-resume model selection: the `model_tier` field on each resume entry routes to a
specific tier. Combined with per-task overrides, this allows:
- SRE resume → Opus (heavy tier)
- Platform resume → Sonnet (moderate tier, if quality is sufficient)
- Both use Haiku (light tier) for accuracy validation

## Task → Tier Reference

Complete list of tasks and their default tier assignments:

| Task | Tier | Why |
|---|---|---|
| `resume_generation_high_value` | heavy | User-facing prose for top matches — quality critical |
| `resume_generation_standard` | heavy | User-facing prose — quality matters |
| `cover_letter_generation` | heavy | User-facing prose — quality matters |
| `application_answer_generation` | heavy | User-facing prose — quality matters |
| `application_answer_critique` | moderate | Critique of user-supplied draft — reasoning, not generation |
| `jd_analysis` | moderate | Structured analysis of JD content — reasoning quality |
| `company_dossier_generation` | light | Summarization of retrieved snippets — doesn't need expensive model |
| `accuracy_validation` | light | Rule checking + LLM-judged claim traceability — fast, structured output |
| `onboarding_interview` | moderate | Conversational reasoning, structured output |
| `resume_parsing` | moderate | Parse resume text into structured profile data |
| `metadata_extraction` | light | Extract metadata from JD text |

An unrecognized task name warns rather than silently defaulting.

## Error Handling

| Scenario | Behavior |
|---|---|
| Provider API key missing | Fail at startup with clear message: "ANTHROPIC_API_KEY not set" |
| Provider unreachable | Use fallback provider/model for that tier |
| Model not available on provider | Use fallback, log warning |
| All providers for a tier unavailable | Fail with message: "No available provider for tier 'heavy'. Check providers.yml." |
| Rate limited (429) | Exponential backoff (1s, 2s, 4s, 8s), then fallback provider |
| Auto-fetch models fails | Use cached model list, log warning |

## Anthropic OAuth Flow

In addition to API key auth, Seeker OS supports Anthropic OAuth (PKCE flow) for
the `anthropic` provider type. This allows users to authenticate via their Claude
account without managing API keys manually.

**Implementation:** `seeker_os/llm/anthropic_oauth.py`

### Flow

1. **Initiate** — `POST /api/models/anthropic/oauth/initiate` generates a PKCE
   code_verifier + code_challenge and returns an authorization URL.
2. **User authorizes** — User opens the URL in their browser, logs into claude.ai,
   and authorizes the app.
3. **Callback** — The callback page displays a code. User pastes it back.
4. **Exchange** — `POST /api/models/anthropic/oauth/callback` exchanges the
   code + verifier for access/refresh tokens. Body: `{code, state}`.
5. **Storage** — Tokens are saved to `data/.anthropic_oauth.json` (gitignored).
   The token file format: `{accessToken, refreshToken, expiresAt}`.
6. **Auto-refresh** — The `AnthropicProvider` checks token expiry and auto-refreshes
   using the refresh token before making API calls.

### Configuration

OAuth is used when `api_key` is absent or empty for an `anthropic` provider. The
provider checks for a valid OAuth token file and uses it as a Bearer token. If both
API key and OAuth token are present, the API key takes precedence.

### Security

- Token file (`data/.anthropic_oauth.json`) is `.gitignore`d
- PKCE state is in-memory only (per-process, short-lived)
- Uses the same client_id as the Claude CLI / Hermes (shared PKCE flow)
- Scopes: `org:create_api_key user:profile user:inference`

---

## Security

- API keys are env var references (`${VAR_NAME}`), never literal in config files
- `.env` file is `.gitignore`d
- `providers.yml` with real keys is `.gitignore`d; `providers.example.yml` ships with placeholder env var names
- API keys are never logged, never included in error messages
- Model auto-fetch sends only the API key to the provider's own `/models` endpoint — no user data
- OAuth tokens are stored in `data/.anthropic_oauth.json` (gitignored), never in config files
- OAuth token refresh happens automatically before API calls when the token is near expiry
