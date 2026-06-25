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

| Type | Description | Example |
|---|---|---|
| `disallowed_phrases` | Block specific phrases from appearing | "expert in", "mastery of", "deep expertise" |
| `disallowed_in_section` | Block phrases only in specific sections | "ansible" in competencies section |
| `forbidden_technologies` | Technologies that must never appear | List of tech names |
| `experience_anchor` | Enforce a specific experience phrase | Required phrase + disallowed alternatives |
| `required_urls` | URLs that must appear as visible text | Portfolio, LinkedIn, GitHub |
| `role_constraint` | Per-company constraints on resume content | Max bullets, disallowed framings |

### Example Rules

```yaml
rules:
  # Avoid superlative claims — show via impact, not adjectives
  - id: no_expert_claims
    description: "Avoid claiming 'expert' or 'mastery' — show via impact, not adjectives"
    type: disallowed_phrases
    phrases: ["expert in", "mastery of", "deep expertise", "world-class", "ninja", "rockstar", "guru"]
    severity: medium

  # Don't inflate years of experience
  - id: no_year_inflation
    description: "Don't inflate years of experience beyond what's in the master resume"
    type: disallowed_phrases
    phrases: ["20+ years", "30+ years"]
    severity: high

  # Technologies you don't know — must never appear in generated resumes
  - id: forbidden_technologies
    description: "These technologies must never appear in generated resumes"
    type: forbidden_technologies
    technologies: []  # Add your own list
    severity: high

  # Experience anchor — enforce consistent phrasing
  - id: experience_anchor
    description: "Use the standard experience anchor from your profile"
    type: experience_anchor
    required_phrase: "N+ years"
    disallowed_phrases: ["inflated year counts"]
    severity: medium

  # Contact URLs must be visible text (ATS parsers miss hidden URLs)
  - id: contact_urls
    description: "Full literal https:// URLs must be visible text"
    type: required_urls
    urls:
      - "https://your-portfolio.com"
      - "https://linkedin.com/in/yourprofile"
      - "https://github.com/yourusername"
    severity: medium
```

## Validation Implementation

```python
# Pseudocode for accuracy validation
def validate_resume(generated_text: str, master_resume: str) -> ValidationResult:
    violations = []

    # Check for disallowed phrases
    for rule in DISALLOWED_PHRASES:
        if rule.pattern in generated_text.lower():
            violations.append({
                'rule': rule.name,
                'violation': f"Contains disallowed phrase: '{rule.pattern}'",
                'severity': 'high'
            })

    # Check for technologies that should never appear
    for tech in NEVER_CLAIM_TECH:
        if tech.lower() in generated_text.lower():
            violations.append({
                'rule': f'never_claim_{tech}',
                'violation': f"Claims {tech} — not in master resume",
                'severity': 'high'
            })

    # Check experience anchor
    if re.search(r'(20|30)\+\s*years', generated_text):
        violations.append({
            'rule': 'experience_anchor',
            'violation': "Uses non-standard experience anchor",
            'severity': 'medium'
        })

    return ValidationResult(
        passed=len(violations) == 0,
        violations=violations
    )
```

## Model Routing for Resume Tasks

| Task | Model | Rationale |
|---|---|---|
| Resume generation (standard) | Moderate tier (e.g. Sonnet) | Good writing quality, reasonable cost |
| Resume generation (high-value) | Heavy tier (e.g. Opus) | Best quality for top matches |
| Accuracy validation | Light tier (e.g. Haiku) | Fast, cheap, just constraint checking |
| Cover letter (optional) | Moderate tier | Good writing, moderate cost |
| Company research | Light tier or local | Summarization, doesn't need expensive model |
