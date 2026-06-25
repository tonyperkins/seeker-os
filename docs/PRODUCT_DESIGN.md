# Seeker OS — Product Design Framework

**Principle:** Seeker OS is a reusable product. User-specific values (comp floor,
blacklist, scoring weights, accuracy rules, resume path) are configuration, not code.
The engines are generic; the config makes them personal.

---

## Configuration Layer Architecture

```
┌─────────────────────────────────────────────────┐
│                  Seeker OS Engine                 │
│  (generic — no personal values in code)          │
│                                                  │
│  discovery · filtering · scoring · dedup ·       │
│  resume_gen · crossref · pipeline                │
└────────────────────┬────────────────────────────┘
                     │ reads
    ┌────────────────┼────────────────┐
    │                │                │
┌───▼──────┐  ┌─────▼──────┐  ┌──────▼───────┐
│ profile   │  │ scoring    │  │ accuracy     │
│ .yml      │  │ _rubric    │  │ _rules       │
│           │  │ .yml       │  │ .yml         │
│ WHO am I  │  │ HOW to     │  │ WHAT not to  │
│           │  │ score      │  │ embellish    │
└───────────┘  └────────────┘  └──────────────┘

┌─────────────────────────────────────────────────┐
│           AI Rules Layer (three-tier)             │
│                                                   │
│  identity_rules.yml  →  WHO (positioning, anchor) │
│  channel_rules.yml   →  HOW (per-channel format)  │
│  jobs.ai_policy      →  WHEN (per-application)    │
└───────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│              Operational Config                   │
│  queries.yml · filters.yml · blacklist.txt       │
│  (already configurable — no changes needed)      │
└───────────────────────────────────────────────────┘
```

## Config Files

| File | Purpose | Personal data? |
|---|---|---|
| `config/sources.yml` | Source adapter config (hiring.cafe + future sources), source_map | No — can be committed |
| `config/providers.yml` | LLM providers, models, tier mapping | Yes (API keys via env vars) — `.gitignore`d |
| `config/profile.yml` | User identity, comp, location, blacklist, paths | Yes — `.gitignore`d |
| `config/scoring_rubric.yml` | Scoring weights, patterns, thresholds | Yes — `.gitignore`d |
| `config/accuracy_rules.yml` | Resume accuracy rules | Yes — `.gitignore`d |
| `config/identity_rules.yml` | Candidate identity: positioning, experience anchor, honest qualifiers, never-claim | Yes — `.gitignore`d |
| `config/channel_rules.yml` | Per-channel AI generation rules (resume, cover letter, analysis) | No — can be committed |
| `config/queries.yml` | Search queries (hiring.cafe URL slugs) | Somewhat — `.gitignore`d |
| `config/filters.yml` | Filter thresholds, request settings | No — can be committed |
| `config/blacklist.txt` | Company blacklist (flat list) | Yes — `.gitignore`d |

All ship `*.example.yml` templates with placeholder values. Real configs are `.gitignore`d.

### `config/providers.yml` — LLM Providers & Models ("Which AI")

Supports 1 to N providers, each with 1 to N models. Models are assigned to 3 task tiers.
See `docs/LLM_ROUTING.md` for the full schema, model auto-discovery, and search features.

```yaml
# Simplified view — see docs/LLM_ROUTING.md for full schema
providers:
  - id: anthropic_direct
    type: anthropic              # native Anthropic API
    api_key: ${ANTHROPIC_API_KEY}
    models:
      - id: claude-opus-4
        tags: [heavy]
      - id: claude-sonnet-4
        tags: [heavy, moderate]
      - id: claude-haiku-4
        tags: [light]

  - id: kilo
    type: openai_compatible      # OpenAI-compat (Kilo, Ollama, vLLM, etc.)
    base_url: "https://kilo.gateway/v1"
    api_key: ${KILO_API_KEY}
    auto_fetch_models: true      # auto-discover available models
    models: [...]                # manually tagged + auto-fetched

  - id: ollama_local
    type: openai_compatible
    base_url: "http://localhost:11434/v1"
    enabled: false
    auto_fetch_models: true

tiers:
  heavy:       { provider: anthropic_direct, model: claude-opus-4 }
  moderate:    { provider: kilo, model: claude-sonnet-4 }
  light:       { provider: kilo, model: claude-haiku-4 }

tasks:
  resume_generation_high_value: { tier: heavy, provider: anthropic_direct, model: claude-opus-4 }
  resume_generation_standard:   { tier: heavy, provider: kilo, model: claude-sonnet-4 }
  accuracy_validation:          { tier: light }
  onboarding_interview:         { tier: moderate }
  # ... (see LLM_ROUTING.md for full task list)
```

**Key features:**
- 1 to N providers (anthropic direct + any OpenAI-compatible gateway)
- 1 to N models per provider
- Auto-fetch available models from provider APIs (`GET /models`)
- Search models by name/tag (CLI: `models search "claude"`, dashboard: search box)
- 3 tiers: heavy (generation), moderate (analysis), light (validation)
- Per-task overrides for fine-grained control
- Fallback providers per tier
- API keys as env var references, never literal in config

### `config/profile.yml` — User Profile ("Who am I")

Everything personal to the user. This is the file that makes Seeker OS yours
vs anyone else's.

```yaml
# User identity
user:
  name: "Your Name"
  email: "you@example.com"
  location: "Your City, ST"

# Location preferences
location:
  remote_only: true
  accepted_cities:
    - your_city
  accepted_states: [your_state]
  rejected_cities: [new york, san francisco, seattle]

# Compensation
comp:
  floor: 150000              # hard reject if comp_max < this (ceiling below floor)
  target: 165000             # positive scoring modifier at this level (comp_min >= target)
  stretch: 220000            # ranking/display context only

# Experience
experience:
  years: 20
  anchor_phrase: "20+ years"  # the only acceptable experience claim

# Employment preferences
employment:
  commitment: "Full Time"     # required commitment type
  reject_commitments: []      # e.g. ["Part Time", "Contract"]
  role_type: "Individual Contributor"
  reject_role_types: ["Manager", "Director", "VP", "Head of"]

# Company blacklist (also in blacklist.txt for simple list)
# This is the structured version — blacklist.txt is the flat list
blacklist:
  - company_one
  - company_two

# Resume
resume:
  master_path: "~/path/to/your/master_resume.md"
  accuracy_rules_path: "config/accuracy_rules.yml"
  output_dir: "data/resumes"
  contact_urls:
    - "https://your-portfolio.com"
    - "https://linkedin.com/in/yourprofile"
    - "https://github.com/yourusername"

# Cross-reference
cross_reference:
  repo_path: "~/projects/job-search"
  auto_pull: true

# Hard rejects (role-level — not scoring, just "never show me these")
hard_rejects:
  - reason: "Clearance required"
    pattern: "security clearance|active clearance|ts/sci|top secret"
  - reason: "Customer-facing/solutions role"
    pattern: "pre.?sales|solutions architect|customer success|technical account manager"
  - reason: "Early career/junior"
    pattern: "early.?career|entry.?level|new.?grad|junior|intern|associate"
  - reason: "Relocation required"
    pattern: "relocation required"
```

### `config/scoring_rubric.yml` — Scoring Configuration ("How to score")

The entire scoring rubric is data-driven. The scoring engine reads this file and
applies it. No scoring logic is hardcoded.

```yaml
scoring:
  post_threshold: 6.0
  per_company_cap: 3
  max_score: 10
  min_score: 0

  # Base score — first matching pattern wins
  # Customize these patterns for your target role(s)
  base_scores:
    - pattern: "(principal|staff).*engineer"
      score: 4.5
      label: "Principal/Staff Engineer"
    - pattern: "(senior|sr\\.?).*engineer"
      score: 3.5
      label: "Senior Engineer"
    - pattern: "engineer"
      score: 2.0
      label: "Engineer title match"
    - score: 0
      label: "No title match"

  # Positive modifiers — all matching patterns are summed
  positive_modifiers:
    - signal: "your_city"
      pattern: "your_city|your_state"
      points: 1.5
      check: "location_or_jd"
    - signal: "key_skill_1"
      pattern: "your_key_skill"
      points: 1.0
      check: "jd"
    - signal: "remote_us"
      pattern: "remote"
      points: 1.0
      check: "jd"
      requires: "united states|us.?based|within the us"
    - signal: "comp_target"
      points: 1.0
      check: "structured_comp"
      threshold: 165000
    - signal: "small_company"
      pattern: "small team|startup|series [abc]"
      points: 0.5
      check: "jd"

  # Negative modifiers — all matching patterns are summed
  negative_modifiers:
    - signal: "relocation_required"
      pattern: "on.?site only|in.?office only|must.*relocat|relocation required"
      points: -3.0
      check: "jd"
    - signal: "hybrid_non_local"
      pattern: "hybrid"
      points: -3.0
      check: "jd"
      unless: "your_city|remote"
    - signal: "comp_below_floor"
      points: -3.0
      check: "structured_comp"
      threshold_max: 140000
    - signal: "people_management"
      pattern: "performance review|headcount|hiring decision|manage.*team of"
      points: -2.0
      check: "jd"
    - signal: "large_enterprise"
      pattern: "fortune\\s*(?:500|100|50)|\\b\\d{2,3},000\\+?\\s*employees"
      points: -1.5
      check: "jd"
    - signal: "staffing_agency"
      pattern: "staffing|consulting llc|recruiting agency"
      points: -1.5
      check: "jd"
    - signal: "missing_location"
      points: -1.5
      check: "no_location_no_remote"

  # Freshness (minor ranking factor, not a score modifier)
  freshness:
    boost_days: 7           # ranking boost within N days
    neutral_days: 14        # neutral between boost and penalty
    penalty_days: 30        # slight ranking penalty after N days
    hard_filter_days: 30    # hard reject at Tier 2 if older than N days
```

### `config/accuracy_rules.yml` — Resume Accuracy Constraints

The accuracy validation engine reads these rules. No rules are hardcoded in Python.

```yaml
# Resume accuracy rules — validated after generation
# Each rule is checked programmatically. Violations are flagged.
# Customize these for your own resume and constraints.

rules:
  # --- Skill depth constraints ---
  - id: no_expert_claims
    description: "Avoid claiming 'expert' or 'mastery' — show via impact, not adjectives"
    type: disallowed_phrases
    phrases: ["expert in", "mastery of", "deep expertise", "world-class", "ninja", "rockstar", "guru"]
    severity: medium

  - id: no_year_inflation
    description: "Don't inflate years of experience beyond what's in the master resume"
    type: disallowed_phrases
    phrases: ["20+ years", "30+ years"]
    severity: high

  # --- Forbidden technologies ---
  # Add technologies you don't know or don't want associated with your profile.
  - id: forbidden_technologies
    description: "These technologies must never appear in generated resumes"
    type: forbidden_technologies
    technologies: []
    severity: high

  # --- Experience anchor ---
  - id: experience_anchor
    description: "Use the standard experience anchor from your profile"
    type: experience_anchor
    required_phrase: "N+ years"
    disallowed_phrases: ["inflated year counts"]
    severity: medium

  # --- Contact URLs ---
  - id: contact_urls
    description: "Full literal https:// URLs must be visible text"
    type: required_urls
    urls:
      - "https://your-portfolio.com"
      - "https://linkedin.com/in/yourprofile"
      - "https://github.com/yourusername"
    severity: medium
```

## Engine Design Principles

### 1. Config-Driven, Not Code-Driven

Every engine module reads its configuration from YAML files. The Python code
implements the *mechanism* (how to match patterns, how to sum scores, how to validate);
the YAML provides the *policy* (what to match, what scores to assign, what to reject).

```python
# BAD — hardcoded in engine.py
if 'aws' in jd_lower:
    score += 1.0

# GOOD — driven by scoring_rubric.yml
for modifier in config.positive_modifiers:
    if modifier.check == "jd" and re.search(modifier.pattern, jd_lower):
        score += modifier.points
```

### 2. Profile Is the User's Identity

`profile.yml` is the single file that personalizes Seeker OS. A different user
creates their own `profile.yml` and gets their own scoring, filtering, and resume
generation — without touching any Python code.

### 3. Scoring Rubric Is Swappable

A frontend engineer could create a different `scoring_rubric.yml` with different
base scores, modifiers, and patterns. The engine doesn't care — it just applies
whatever rubric it's given.

### 4. Accuracy Rules Are User-Defined

The resume accuracy rules in `accuracy_rules.yml` are specific to the user's master
resume. A different user defines their own constraints. The validation engine is
generic; the rules are data.

### 5. No User-Specific Values in Code

Audit rule: grep the codebase for any of these — if found in `.py` files (not
`.yml`), it's a bug:
- Personal names, emails, locations
- Specific comp threshold numbers in logic
- Specific company names in blacklist logic
- Specific experience year counts
- Specific technology names in scoring logic

## Config Validation

On startup, Seeker OS validates all config files:

```python
def validate_config(config_dir: str) -> list[ConfigError]:
    """Validate all config files on startup.

    Checks:
    - profile.yml: required fields present, types correct
    - scoring_rubric.yml: at least one base_score, patterns compile
    - accuracy_rules.yml: rule types are valid, phrases are strings
    - queries.yml: at least one query, slugs are valid
    - filters.yml: thresholds are numbers, patterns compile
    - blacklist.txt: one company per line

    Returns list of ConfigError objects (empty if all valid).
    """
```

## Default Configs (Shipping)

Seeker OS ships with:
- `config/profile.example.yml` — template with placeholder values
- `config/scoring_rubric.example.yml` — a generic example rubric
- `config/accuracy_rules.example.yml` — template with example rules
- `config/queries.example.yml` — example queries
- `config/filters.example.yml` — example filter thresholds
- `config/sources.example.yml` — example source adapter config
- `config/providers.example.yml` — example LLM provider config

The user copies these to their active config and customizes. The actual
`profile.yml` etc. are in `.gitignore` (they contain personal data).

## Config ↔ DB Sync Ownership

**YAML files are the source of truth. DB tables are derived caches.**

| Config file | DB table | Sync direction | Phase 1 behavior |
|---|---|---|---|
| `queries.yml` | `search_queries` | YAML → DB on startup | YAML wins; DB overwritten |
| `filters.yml` | `settings` (key-value) | YAML → DB on startup | YAML wins; DB overwritten |
| `profile.yml` | (not in DB) | N/A | Read from file at runtime |
| `scoring_rubric.yml` | (not in DB) | N/A | Read from file at runtime |
| `accuracy_rules.yml` | (not in DB) | N/A | Read from file at runtime |
| `sources.yml` | (not in DB) | N/A | Read from file at runtime |
| `providers.yml` | (not in DB) | N/A | Read from file at runtime |

**Phase 1:** YAML is the only source of truth. `queries.yml` and `filters.yml` are
synced to DB on startup (YAML wins). Other configs are read from file at runtime.

**Phase 2 (dashboard):** Dashboard edits update DB, then write back to YAML.
On next startup, YAML and DB should match. If they diverge (manual YAML edit),
YAML wins on startup (DB is overwritten). The dashboard detects divergence and
warns the user.

**Why YAML wins:** YAML is version-controlled (via `.example.yml` templates) and
human-editable. DB is a runtime cache. If someone edits YAML manually, that should
take effect on next startup — not be silently overwritten by stale DB values.

## Multi-Profile & Multi-Resume Support (Future)

Phase 1 uses a single profile and single resume. Future: support multiple profiles
and resumes. The architecture doesn't prevent this:

**Multi-profile** (e.g., searching for both backend and frontend roles):
- `--profile` CLI flag + `profiles/` directory
- Each profile has its own `scoring_rubric.yml`, `queries.yml`, `filters.yml`

**Multi-resume** (e.g., backend resume + platform resume):
- `resume:` (single) or `resumes:` (list) in `profile.yml`
- Config loader accepts either; code always works with a list internally
- Per-resume `model_tier` field routes to different LLM tiers
- See `docs/LLM_ROUTING.md` for the multi-resume config schema

Not built in Phase 1 but the config schema is designed to accept both forms.
