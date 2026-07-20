# Accuracy Rules — Seeker OS

**Source:** User-configured (`config/accuracy_rules.yml`)
**Purpose:** Config-driven constraints for AI-generated artifacts (resumes, cover letters,
application answers). These are NOT just prompt instructions — they are validated
programmatically after generation by an artifact-agnostic validator that reads the
rules from YAML.

## Core Principle

**NO EMBELLISHING.** Every claim in a generated artifact (resume, cover letter, or
application answer) must be traceable to the master resume. The generated artifact may
reorganize, emphasize, or de-emphasize content from the master resume to align with a
specific JD, but it may never:
- Invent new skills not in the master resume
- Inflate years of experience
- Claim depth/expertise beyond what the master resume states
- Use technologies explicitly listed as "never claim"
- Contradict any accuracy rule in the config

## Config-Driven Validation Rules

Rules are defined in `config/accuracy_rules.yml` and checked programmatically after
artifact generation by a generic validator. The validator implements the mechanism (rule
dispatch, phrase matching, section parsing); the YAML provides the policy (which phrases
are disallowed, which technologies are forbidden, etc.). Violations are flagged and the
resume is held for manual review.

The rules below are examples — customize them for your own resume and constraints.

### Rule Types

| Type | Description | Fields | Example |
|---|---|---|---|
| `disallowed_phrases` | Block specific phrases from appearing (case-insensitive) | `phrases` | "expert in", "mastery of", "deep expertise" |
| `forbidden_technologies` | Technologies that must never appear (word-boundary match) | `technologies` | List of tech names |
| `required_phrases` | Phrases that MUST appear (case-insensitive) | `phrases` | Contact URLs, required disclaimers |
| `experience_anchor` | Flag non-standard year counts via regex | `patterns` | Regex matching inflated year counts |
| `education_omission` | Flag education mentions via regex | `patterns` | Regex matching degree names, university names |

> **Note:** The experience anchor phrase, its disallowed variants, and the
> identity-layer never-claim list now live in `config/identity_rules.yml`
> (see [Identity Rules](#identity-rules-layer) below). The `experience_anchor`
> rule type in `accuracy_rules.yml` still provides regex `patterns` for matching,
> but the validator also merges `disallowed_variants` from `identity_rules.yml`
> at check time. The violation message uses the configured anchor phrase from
> `identity_rules.yml`.
>
> The `forbidden_technologies` rule type in `accuracy_rules.yml` is the
> resume-output guard. The `never_claim` list in `identity_rules.yml` is the
> identity-layer guard (used in JD analysis and prompt injection). Both are
> enforced independently.

**Unknown rule types are flagged at load time** — a warning is logged and the
rule is ignored. This prevents silent failures when a config has a typo or
references a type that does not exist in the validator.

### Example Rules

```yaml
rules:
  # Avoid superlative claims — show via impact, not adjectives
  - id: no_expert_claims
    description: "Avoid claiming 'expert' or 'mastery' — show via impact, not adjectives"
    type: disallowed_phrases
    phrases: ["expert in", "mastery of", "deep expertise", "world-class", "ninja", "rockstar", "guru"]
    severity: medium

  # Don't inflate years of experience — customize the phrases to match
  # whatever year counts would be inflated for YOUR resume
  - id: no_year_inflation
    description: "Don't inflate years of experience beyond what's in the master resume"
    type: disallowed_phrases
    phrases: ["NN+ years", "NN+ years in"]  # Replace NN with your inflated thresholds
    severity: high

  # Technologies you don't know — must never appear in generated resumes
  - id: forbidden_technologies
    description: "These technologies must NEVER appear in generated resumes"
    type: forbidden_technologies
    technologies: []  # Add your own list
    severity: high

  # Required phrases — ensure contact info or disclaimers are present
  - id: contact_urls_visible
    description: "Always render full literal https:// URLs as visible text"
    type: required_phrases
    phrases: []  # Add your portfolio, LinkedIn, GitHub URLs here
    severity: medium

  # Experience anchor — flag non-standard year counts via regex
  - id: experience_anchor
    description: "Use the standard experience anchor from your profile, not arbitrary counts"
    type: experience_anchor
    patterns:
      - "(NN|NN)\\+\\s*years"  # Replace NN with year counts that would be inflated for you
    severity: medium

  # Education omission — flag education mentions if you choose to omit
  # Uncomment and add patterns if you want to flag education mentions.
  # - id: education_omission
  #   description: "Omit education entirely from generated resumes"
  #   type: education_omission
  #   patterns:
  #     - "(?i)\\b(b\\.?s\\.?|b\\.?a\\.?|m\\.?s\\.?|m\\.?a\\.?|ph\\.?d|mba|associate|diploma)\\b"
  #     - "(?i)\\b(university|college|institute)\\b"
  #   severity: medium
```

## Validation Implementation

The validator (`backend/seeker_os/validation/__init__.py`) is artifact-agnostic —
it validates resumes, cover letters, and application answers with the same
deterministic deny-list checks. The old `resume/validator.py` is now a
backward-compatible shim that re-exports from `seeker_os.validation`.

The validator reads rules from `config/accuracy_rules.yml` and dispatches by `type`:

- `disallowed_phrases` — case-insensitive substring match
- `forbidden_technologies` — case-insensitive word-boundary regex match
- `required_phrases` — case-insensitive substring match (flags if MISSING)
- `experience_anchor` — regex match against `patterns` list (from accuracy_rules.yml) **plus** `disallowed_variants` from `identity_rules.yml`. Violation message references the anchor phrase from `identity_rules.yml`.
- `education_omission` — regex match against `patterns` list

Unknown rule types are logged as warnings at load time and ignored during
validation. High-severity violations block the artifact (flagged as failed);
medium-severity violations are warnings only.

## LLM-Judged Claim Traceability

In addition to the deterministic deny-list checks above, a **traceability pass** runs
after generation (default ON). This pass uses the light/validation tier LLM to:

1. Extract every factual claim from the generated artifact.
2. Judge each claim against the master resume: **supported**, **unsupported**, or
   **overstated**.
3. Flag any unsupported or overstated claim as a HIGH-severity violation that fails
   validation.

The judge prompt instructs: do not be charitable; a claim is unsupported unless the
master resume substantiates it; rounding up a qualifier counts as overstated.

### Configuration

```yaml
# In accuracy_rules.yml:
traceability:
  enabled: true              # default ON for single generations
  task: "accuracy_validation" # LLM task name (routes to light tier)
```

Set `enabled: false` to disable for cost in bulk runs. The traceability checker
lives in `backend/seeker_os/validation/traceability.py`.

```python
# Simplified dispatch logic
for rule in rules:
    if rule.type == "disallowed_phrases":
        # Check each phrase as case-insensitive substring
    elif rule.type == "forbidden_technologies":
        # Check each tech with word-boundary regex
    elif rule.type == "required_phrases":
        # Flag if any required phrase is MISSING
    elif rule.type == "experience_anchor":
        # Check regex patterns from accuracy_rules.yml + identity_rules.yml
        # disallowed_variants. Message uses identity_rules.yml anchor phrase.
    elif rule.type == "education_omission":
        # Check regex patterns for education mentions
    # else: warned at load time, ignored
```

## Model Routing for Generation & Validation Tasks

| Task | Model | Rationale |
|---|---|---|
| Resume generation (standard) | Moderate tier (e.g. Sonnet) | Good writing quality, reasonable cost |
| Resume generation (high-value) | Heavy tier (e.g. Opus) | Best quality for top matches |
| Accuracy validation | Light tier (e.g. Haiku) | Fast, cheap, just constraint checking |
| Cover letter generation | Heavy tier | Good writing quality, user-facing prose |
| Application answer generation | Heavy tier | Good writing quality, user-facing prose |
| Application answer critique | Moderate tier (e.g. Sonnet) | Review/feedback, not authoring — explicitly registered |
| Company research | Light tier or local | Summarization, doesn't need expensive model |

## Identity Rules Layer

The identity rules layer (`config/identity_rules.yml`) defines **who the candidate is** —
separate from accuracy rules (which define **what not to write**). The JD analyzer and
resume generator read identity rules at call time to inject positioning, honest
qualifiers, and the never-claim list into prompts.

### Fields

| Field | Purpose | Consumed by |
|---|---|---|
| `positioning` | One-sentence identity statement | JD analyzer (positioning check), resume generator |
| `experience_anchor.phrase` | The only acceptable experience phrasing | Resume generator (prompt), validator (message) |
| `experience_anchor.applies_to` | What the anchor refers to | Resume generator (prompt) |
| `experience_anchor.disallowed_variants` | Regex patterns for invalid anchors | Validator (merged with accuracy_rules patterns) |
| `honest_qualifiers` | Skills with limited depth + verbatim framing | JD analyzer (prompt), resume generator (prompt) |
| `never_claim` | Technologies that must never be claimed | JD analyzer (prompt) |

If a field is absent or empty, the corresponding behavior is absent — there is no
hardcoded default or fallback in code.

## Channel Rules Layer

Channel rules (`config/channel_rules.yml`) define per-output-type constraints and
AI generation policy. Each channel controls how AI-generated content is produced.

### Channels

| Channel | Consumed by | Key fields |
|---|---|---|
| `resume` | Resume generator | `require_visible_urls`, `format_hints` |
| `cover_letter` | Cover letter generator | `require_visible_urls`, `format_hints` |
| `application_answer` | Application answer generator | `format_hints` |
| `analysis` | Phase 2 | `format_hints` |

### Per-Application AI Policy

In addition to channel-level defaults, each job can have a per-application AI
policy override (`jobs.ai_policy` column, values: `allowed`, `draft_only`,
`forbidden`, or null for channel default). This is set via the job detail page
toggle and persists in the database.

### AI Policy Enforcement (Phase 2 — implemented)

The `ai_policy` value is now consumed by the cover letter and application answer
generation paths:

- **`forbidden`**: The generation path returns a refusal and does NOT call the LLM.
  For application answers, the user may still submit their own draft for critique
  (critique is allowed even when authoring is forbidden).
- **`draft_only`**: The generation path produces clean content (no notice embedded).
  The `is_draft` flag and `draft_notice` string are returned as separate fields in the
  response. The DB content field (`answer_text` / `cover_letter_text`) contains only the
  pure generated content. The markdown file has an HTML comment header (`<!-- DRAFT: ... -->`)
  that is clearly out-of-band. The frontend renders the draft status as a visible banner
  above the copyable content (via the `DraftBanner` component), not inside the text.
- **`allowed`** or **null**: The generation path produces content normally.

Resume generation does not currently check `ai_policy` (resumes are always
user-reviewed); this may be added in a future phase.

## ATS Parse-Survival Gate

The ATS parse-survival gate (`validation/ats_parse.py`) verifies that
critical content from the generated resume survives text extraction —
simulating what an ATS (Applicant Tracking System) does when it parses
a submitted resume. The gate extracts text from three formats (HTML,
DOCX, PDF) and runs assertions against each.

### Assertions (HTML layer)

| # | Assertion | What it checks |
|---|---|---|
| 1 | Contact block | Name, email, location, citizenship line present and intact |
| 2 | URLs | Every URL from the master survives as an exact full-string match |
| 3 | Role titles | Every selected role title extracts as a word-boundary token |
| 4 | Project titles | Every selected portfolio project title extracts |
| 5 | Competency lines | Every selected category label extracts with skills |
| 6 | Pin content | Every pinned bullet's text survives extraction |
| 7 | No artifacts | No HTML fragments, pin markers, placeholders, or table syntax |
| 8 | Role content preservation | Non-bullet role content (intro paragraphs, trailing notes) from the master survives verbatim |
| 9 | Key-term survival (PDF-only) | Critical JD terms survive PDF extraction as word-boundary tokens |

### PDF-Specific Diagnostics

The PDF layer runs a subset of assertions (contact, URLs, artifacts, key-term
survival) plus two diagnostics:

- **Hyphen-merge diagnostic**: Reports compound terms from the resume that
  appear merged (e.g., "Terraformbased") or split across line wraps
  (e.g., "Terraform-\nbased") in the extracted PDF text. Not an assertion —
  surfaces the issue without failing the gate.

- **Non-breaking hyphen substitution**: Curated compound terms in
  `channel_rules.yml` → `content_tiering.non_breaking_hyphen_terms` have
  their ASCII hyphens replaced with U+2011 (non-breaking hyphen) in the PDF
  render path ONLY. This prevents line-wrap splits at hyphens. The
  substitution happens in HTML body text only — never in markdown source,
  DOCX export, tag attributes, or URLs. The key-term survival assertion
  runs against the post-substitution PDF to verify U+2011 compounds still
  yield their key component tokens.

### CSS PDF Optimizations

- **`list-style-position: inside`**: Places the bullet marker inside the
  content flow of the `<li>` element, preventing PDF extractors from
  placing the marker on a separate line (detached bullet markers).

### Source of Expected Values

Expected values are sourced from the generation's own audit records — no
hardcoded duplicates. The validator receives:
- `selected_role_titles` / `selected_project_titles` from the bullet
  selection audit
- `selected_category_labels` from the competency selection audit
- `pinned_bullet_texts` from the bullet selection audit (`reason=pinned`)
- `key_terms` from the competency selection audit (kept skill items +
  category labels)
- `master_resume` for role content preservation (parsed in-situ)
