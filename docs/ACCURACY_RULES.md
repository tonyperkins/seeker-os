# Resume Accuracy Rules — Seeker OS

**Source:** User-configured (`config/accuracy_rules.yml`)
**Purpose:** Config-driven constraints for resume generation. These are NOT just prompt
instructions — they are validated programmatically after generation by a generic
validator that reads the rules from YAML.

## Core Principle

**NO EMBELLISHING.** Every claim in a generated resume must be traceable to the master
resume. The generated resume may reorganize, emphasize, or de-emphasize content from the
master resume to align with a specific JD, but it may never:
- Invent new skills not in the master resume
- Inflate years of experience
- Claim depth/expertise beyond what the master resume states
- Use technologies explicitly listed as "never claim"
- Contradict any accuracy rule in the config

## Config-Driven Validation Rules

Rules are defined in `config/accuracy_rules.yml` and checked programmatically after
resume generation by a generic validator. The validator implements the mechanism (rule
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

The validator (`backend/seeker_os/resume/validator.py`) reads rules from
`config/accuracy_rules.yml` and dispatches by `type`:

- `disallowed_phrases` — case-insensitive substring match
- `forbidden_technologies` — case-insensitive word-boundary regex match
- `required_phrases` — case-insensitive substring match (flags if MISSING)
- `experience_anchor` — regex match against `patterns` list
- `education_omission` — regex match against `patterns` list

Unknown rule types are logged as warnings at load time and ignored during
validation. High-severity violations block the resume (flagged as failed);
medium-severity violations are warnings only.

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
        # Check regex patterns for non-standard year counts
    elif rule.type == "education_omission":
        # Check regex patterns for education mentions
    # else: warned at load time, ignored
```

## Model Routing for Resume Tasks

| Task | Model | Rationale |
|---|---|---|
| Resume generation (standard) | Moderate tier (e.g. Sonnet) | Good writing quality, reasonable cost |
| Resume generation (high-value) | Heavy tier (e.g. Opus) | Best quality for top matches |
| Accuracy validation | Light tier (e.g. Haiku) | Fast, cheap, just constraint checking |
| Cover letter (optional) | Moderate tier | Good writing, moderate cost |
| Company research | Light tier or local | Summarization, doesn't need expensive model |
