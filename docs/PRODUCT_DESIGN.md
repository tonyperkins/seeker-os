# Seeker OS — Product Design Framework

**Principle:** Seeker OS is a reusable product. Tony's specific values (comp floor,
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
│              Operational Config                   │
│  queries.yml · filters.yml · blacklist.txt       │
│  (already configurable — no changes needed)      │
└──────────────────────────────────────────────────┘
```

## Config Files

| File | Purpose | Personal data? |
|---|---|---|
| `config/sources.yml` | Source adapter config (hiring.cafe + future sources), source_map | No — can be committed |
| `config/providers.yml` | LLM providers, models, tier mapping | Yes (API keys via env vars) — `.gitignore`d |
| `config/profile.yml` | User identity, comp, location, blacklist, paths | Yes — `.gitignore`d |
| `config/scoring_rubric.yml` | Scoring weights, patterns, thresholds | Yes — `.gitignore`d |
| `config/accuracy_rules.yml` | Resume accuracy rules | Yes — `.gitignore`d |
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

Everything personal to the user. This is the file that makes Seeker OS "Tony's"
vs "anyone else's."

```yaml
# User identity
user:
  name: "Tony Perkins"
  email: "tony.perkins@perkinslab.com"
  location: "Leander, TX"

# Location preferences
location:
  remote_only: true
  accepted_cities:
    - austin
    - leander
    - cedar park
    - round rock
    - georgetown
    - pflugerville
    - taylor
  accepted_states: [tx, texas]
  rejected_cities: [new york, san francisco, seattle, chicago, boston, denver]

# Compensation
comp:
  floor: 150000              # hard reject if comp_max < this (ceiling below floor)
  target: 165000             # positive scoring modifier at this level (comp_min >= target)
  stretch: 220000            # ranking/display context only

# Experience
experience:
  years: 25
  anchor_phrase: "25+ years"  # the only acceptable experience claim

# Employment preferences
employment:
  commitment: "Full Time"     # required commitment type
  reject_commitments: []      # e.g. ["Part Time", "Contract"]
  role_type: "Individual Contributor"
  reject_role_types: ["Manager", "Director", "VP", "Head of"]

# Company blacklist (also in blacklist.txt for simple list)
# This is the structured version — blacklist.txt is the flat list
blacklist:
  - avidxchange
  - fidelity
  - fidelity investments
  - marriott
  - zapcom

# Resume
resume:
  master_path: "~/projects/job-search/resume/Tony_Perkins_Master_Resume.md"
  accuracy_rules_path: "config/accuracy_rules.yml"
  output_dir: "data/resumes"
  contact_urls:
    - "https://perkinslab.com"
    - "https://linkedin.com/in/tonyperkins"
    - "https://github.com/tonyperkins"

# Cross-reference
cross_reference:
  repo_path: "~/projects/job-search"
  auto_pull: true

# Hard rejects (role-level — not scoring, just "never show me these")
hard_rejects:
  - reason: "FedRAMP/clearance required"
    pattern: "fedramp|security clearance|active clearance|ts/sci|top secret"
  - reason: "Customer-facing/solutions role"
    pattern: "pre.?sales|solutions architect|customer success|technical account manager"
  - reason: "Early career/junior"
    pattern: "early.?career|entry.?level|new.?grad|junior|intern|associate"
  - reason: "Defense/ITAR"
    pattern: "defense contractor|itar|classified"
  - reason: "Relocation required"
    pattern: "relocation required"
  - reason: "AI/ML Engineer (non-infra)"
    pattern: "ai/ml engineer|machine learning engineer"
    unless_pattern: "ml infra|ml platform|gpu infra|model serving|mlops"
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
  base_scores:
    - pattern: "(principal|staff).*(sre|site reliability|platform|infra|devops)"
      score: 4.5
      label: "Principal/Staff SRE/Platform/Infra"
    - pattern: "senior.*(sre|site reliability|platform|infra)"
      score: 4.0
      label: "Senior SRE/Platform/Infra"
    - pattern: "senior.*(devops|cloud.?engineer)"
      score: 3.5
      label: "Senior DevOps/Cloud"
    - pattern: "senior.*(release|build)"
      score: 3.0
      label: "Senior Release/Build"
    - pattern: "(sre|site reliability|platform.?engineer|infrastructure.?engineer|devops|cloud.?engineer)"
      score: 2.0
      label: "Infrastructure title match"
    - pattern: "software.?engineer.*(infra|platform|cloud|sre)"
      score: 2.0
      label: "SE on infra/platform team"
    - pattern: "(infra|cloud|security.*cloud).*engineer"
      score: 2.0
      label: "Infra/Cloud Security Engineer"
    - check: "jd_infra_role"
      score: 2.0
      label: "JD matches infrastructure role (no title match)"
    - score: 0
      label: "No title/JD match"

  # Positive modifiers — all matching patterns are summed
  positive_modifiers:
    - signal: "austin_area"
      pattern: "austin|leander|cedar park|round rock|georgetown|pflugerville|taylor|texas|tx"
      points: 1.5
      check: "location_or_jd"    # check both location field and JD text
    - signal: "aws"
      pattern: "aws|amazon web services"
      points: 1.0
      check: "jd"
    - signal: "terraform"
      pattern: "terraform"
      points: 1.0
      check: "jd"
    - signal: "remote_us"
      pattern: "remote"
      points: 1.0
      check: "jd"
      requires: "united states|us.?based|within the us"  # must also match this
    - signal: "comp_target"
      points: 1.0
      check: "structured_comp"   # use structured comp_min field, not regex
      threshold: 165000
    - signal: "you_build_it"
      pattern: "you build it.*you run it|build it.*run it|own.*production"
      points: 1.0
      check: "jd"
    - signal: "kubernetes"
      pattern: "kubernetes|k8s"
      points: 0.5
      check: "jd"
    - signal: "cicd"
      pattern: "ci/cd|cicd|continuous integration|pipeline"
      points: 0.5
      check: "jd"
    - signal: "observability"
      pattern: "prometheus|grafana|datadog|observability|elk|splunk"
      points: 0.5
      check: "jd"
    - signal: "docker"
      pattern: "docker"
      points: 0.5
      check: "jd"
    - signal: "platform_devex"
      pattern: "platform|developer experience|devex|golden path"
      points: 0.5
      check: "jd"
    - signal: "small_company"
      pattern: "small team|startup|series [abc]"
      points: 0.5
      check: "jd"
    - signal: "ai_infra"
      pattern: "ml platform|gpu infra|model serving|inference infra"
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
      unless: "austin|leander|cedar park|remote"  # don't penalize if local or remote
    - signal: "city_only_no_remote"
      points: -2.0
      check: "location_only"   # location is a city, JD has no "remote"
    - signal: "comp_below_floor"
      points: -3.0
      check: "structured_comp"
      threshold_max: 140000    # comp_max below this
    - signal: "comp_marginal"
      points: -1.5
      check: "structured_comp"
      threshold_min: 140000
      threshold_max: 165000
    - signal: "people_management"
      pattern: "performance review|headcount|hiring decision|manage.*team of"
      points: -2.0
      check: "jd"
    - signal: "follow_the_sun"
      pattern: "follow.?the.?sun|24.?7 global|offices? in \\d+ countries"
      points: -1.5
      check: "jd"
    - signal: "large_enterprise"
      pattern: "fortune\\s*(?:500|100|50)|\\b\\d{2,3},000\\+?\\s*employees"
      points: -1.5
      check: "jd"
    - signal: "known_large_enterprise"
      pattern: "cvs|walgreens|bank of america|wells fargo|jpmorgan|chase|citibank"
      points: -1.5
      check: "jd"
    - signal: "staffing_agency"
      pattern: "jobs? via dice|robert half|akkodis|jobgether|intellisoft|manpower|randstad|adecco|insight global|tek systems|staffing|consulting llc"
      points: -1.5
      check: "jd"
    - signal: "extreme_oncall"
      pattern: "(?:12.?hour|24.?hour).{0,30}(?:on.?call|shift|rotation)|7\\s*days?.{0,30}(?:on.?call|rotation)"
      points: -2.5
      check: "jd"
    - signal: "oncall_low_comp"
      pattern: "on.?call|on-call rotation"
      points: -1.0
      check: "jd"
      requires_comp_below: 200000
    - signal: "oncall_high_comp"
      pattern: "on.?call|on-call rotation"
      points: -0.5
      check: "jd"
      requires_comp_at_least: 200000   # partially offsets on-call burden
    - signal: "k8s_5yr_primary"
      pattern: "5\\+.*years.*kubernetes"
      points: -1.0
      check: "jd"
    - signal: "first_line_support"
      pattern: "first.?line.*support|first.?line.*response|first.*escalation point"
      points: -1.0
      check: "jd"
    - signal: "gcp_primary"
      pattern: "\\bgcp\\b|\\bgoogle cloud\\b"
      points: -0.5
      check: "jd"
    - signal: "azure_primary_no_aws"
      pattern: "\\bazure\\b"
      points: -0.5
      check: "jd"
      unless: "aws"   # don't penalize if AWS also mentioned
    - signal: "compliance_heavy"
      pattern: "pci.?dss|sox\\b|hipaa|iso.?27001"
      points: -0.5
      check: "jd"
    - signal: "high_experience_bar"
      pattern: "10\\+.*years|15\\+.*years"
      points: -0.5
      check: "jd"
    - signal: "mts_no_seniority"
      pattern: "\\bmember of technical staff\\b"
      points: -1.0
      check: "title"
      unless: "senior|staff|principal"
    - signal: "generic_swe_title"
      pattern: "^software engineer$"
      points: -2.0
      check: "title"
      unless: "infrastructure|platform|sre|devops|cloud|release|security|data"
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

rules:
  # --- Skill depth constraints ---
  - id: aws_depth
    description: "Never claim deep AWS expertise or year count"
    type: disallowed_phrases
    phrases: ["deep aws expertise", "aws expert", "since aws launch"]
    severity: high

  - id: azure_depth
    description: "Never claim deep independent Azure expertise"
    type: disallowed_phrases
    phrases: ["azure expert", "deep azure"]
    severity: high

  - id: gcp_depth
    description: "Never claim production GCP depth"
    type: disallowed_phrases
    phrases: ["gcp experience", "google cloud production", "gcp expertise"]
    severity: high

  - id: powershell_depth
    description: "Never claim PowerShell depth/mastery"
    type: disallowed_phrases
    phrases: ["powershell expert", "powershell mastery", "strong powershell"]
    severity: high

  - id: ansible_current
    description: "Never claim Ansible as current competency"
    type: disallowed_in_section
    phrases: ["ansible"]
    section: "competencies"   # only check in competency/skills sections
    severity: high

  - id: kubernetes_depth
    description: "Never claim cluster administration depth"
    type: disallowed_phrases
    phrases: ["kubernetes admin", "kubernetes expert", "deep k8s", "cluster administration", "k8s architect"]
    severity: high

  - id: go_primary
    description: "Never claim Go as primary language"
    type: disallowed_phrases
    phrases: ["go expert", "go primary language", "deep go", "go proficiency"]
    severity: medium

  - id: spinnaker_depth
    description: "Never claim Spinnaker operational depth"
    type: disallowed_phrases
    phrases: ["spinnaker expertise", "operated spinnaker", "spinnaker administration"]
    severity: medium

  # --- Forbidden technologies ---
  - id: forbidden_technologies
    description: "These technologies must never appear in generated resumes"
    type: forbidden_technologies
    technologies:
      - argocd
      - helm
      - kargo
      - consul
      - vault          # production vault
      - rust
      - temporal
      - ansible        # as current competency
    severity: high

  # --- Experience anchor ---
  - id: experience_anchor
    description: "Must use '25+ years' only, attached to overall career not cloud"
    type: experience_anchor
    required_phrase: "25+ years"
    disallowed_phrases: ["20+ years", "30+ years", "25+ years in cloud", "25+ years in devops"]
    severity: medium

  # --- Education ---
  - id: education_omission
    description: "Omit education entirely"
    type: disallowed_phrases
    phrases: ["devry", "electronics engineering technology"]
    severity: medium

  # --- AI assistance framing ---
  - id: ai_assistance
    description: "Claims should reflect AI-assisted capability, not deep independent expertise"
    type: disallowed_phrases
    phrases: ["deep independent expertise"]
    severity: low

  # --- Contact URLs ---
  - id: contact_urls
    description: "Full literal https:// URLs must be visible text"
    type: required_urls
    urls:
      - "https://perkinslab.com"
      - "https://linkedin.com/in/tonyperkins"
      - "https://github.com/tonyperkins"
    severity: medium

  # --- Role-specific constraints ---
  - id: marriott_honest
    description: "Marriott role: honest 3-bullet version only"
    type: role_constraint
    company: "marriott"
    max_bullets: 3
    severity: medium

  - id: hilton_location
    description: "Hilton: Collierville TN, primarily onsite — do not frame as remote"
    type: role_constraint
    company: "hilton"
    disallowed_phrases: ["hilton (remote)", "remote at hilton"]
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

The resume accuracy rules in `accuracy_rules.yml` are specific to Tony's master
resume. A different user defines their own constraints. The validation engine is
generic; the rules are data.

### 5. No Tony-Specific Values in Code

Audit rule: grep the codebase for any of these — if found in `.py` files (not
`.yml`), it's a bug:
- "tony", "perkins", "leander", "austin" (in logic, not tests)
- "165000", "150000", "220000" (comp thresholds)
- "avidxchange", "fidelity", "marriott", "zapcom" (blacklist)
- "25+ years" (experience anchor)
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
- `config/scoring_rubric.example.yml` — a generic SRE/DevOps rubric
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

**Multi-profile** (e.g., searching for both SRE and frontend roles):
- `--profile` CLI flag + `profiles/` directory
- Each profile has its own `scoring_rubric.yml`, `queries.yml`, `filters.yml`

**Multi-resume** (e.g., SRE resume + Platform resume):
- `resume:` (single) or `resumes:` (list) in `profile.yml`
- Config loader accepts either; code always works with a list internally
- Per-resume `model_tier` field routes to different LLM tiers
- See `docs/LLM_ROUTING.md` for the multi-resume config schema

Not built in Phase 1 but the config schema is designed to accept both forms.
