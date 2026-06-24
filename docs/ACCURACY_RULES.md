# Resume Accuracy Rules — Seeker OS

**Source:** `~/projects/job-search/resume/Tony_Perkins_Master_Resume.md` (Accuracy Notes section)
**Purpose:** Config-driven constraints for resume generation (`config/accuracy_rules.yml`).
These are NOT just prompt instructions — they are validated programmatically after
generation by a generic validator that reads the rules from YAML.

## Core Principle

**NO EMBELLISHING.** Every claim in a generated resume must be traceable to the master
resume. The generated resume may reorganize, emphasize, or de-emphasize content from the
master resume to align with a specific JD, but it may never:
- Invent new skills not in the master resume
- Inflate years of experience
- Claim depth/expertise beyond what the master resume states
- Use technologies explicitly listed as "never claim"
- Contradict any accuracy note below

## Config-Driven Validation Rules

These rules are defined in `config/accuracy_rules.yml` and checked programmatically
after resume generation by a generic validator. The validator implements the mechanism
(rule dispatch, phrase matching, section parsing); the YAML provides the policy (which
phrases are disallowed, which technologies are forbidden, etc.). Violations are flagged
and the resume is held for manual review.

The rules below document Tony's specific values — the engine itself is generic.

### Rule 1: AWS

**Constraint:** Never claim "deep AWS expertise" or a hard year count for AWS.
**Allowed framing:** "Breadth across core services + delivery-with-AI"
**Disallowed phrases:** "deep AWS expertise", "AWS expert", "X+ years AWS",
"since AWS launch" (implies mastery)
**Rationale:** Uses AWS since near launch, but never went deep in any single area.
Relies on AI assistance for cloud operations. Frame as breadth, not depth.

### Rule 2: Azure

**Constraint:** Never claim deep independent Azure expertise.
**Allowed framing:** "Production project experience with AI assistance"
**Disallowed phrases:** "Azure expert", "deep Azure", "X+ years Azure"
**Rationale:** Production project experience built with significant AI assistance.
Demonstrates ability to deliver, not years of deep independent expertise.

### Rule 3: GCP

**Constraint:** Never claim production depth on GCP.
**Allowed framing:** "Minimal GCP exposure" or omit entirely
**Disallowed phrases:** "GCP experience", "Google Cloud production", "GCP expertise"
**Rationale:** Minimal only — never had production GCP work.

### Rule 4: PowerShell

**Constraint:** Never claim PowerShell depth, mastery, or "strong proficiency."
**Allowed framing:** List as a scripting language (backed by Accelya bullets)
**Disallowed phrases:** "PowerShell expert", "PowerShell mastery",
"strong PowerShell proficiency", "deep PowerShell"
**Rationale:** Real GitLab CI + PowerShell work at Accelya, but rewrote much of the
legacy PowerShell WITH AI assistance. Not a PowerShell expert.

### Rule 5: Ansible

**Constraint:** Never claim Ansible as a current competency.
**Allowed framing:** The Fidelity bullet (2015-2016) is retained as dated, historical work
**Disallowed phrases:** "Ansible" in competency table, "Ansible expertise",
"current Ansible experience"
**Rationale:** Never had production Ansible. The Fidelity bullet is defensible as past
experience in an interview, not a current competency.

### Rule 6: Kubernetes

**Constraint:** Never claim cluster administration depth. Honest self-rating: 1-3 currently.
**Allowed framing:** "Production at Hilton 2016-2020. Re-ramping. Operated at
SRE/deployment layer."
**Disallowed phrases:** "Kubernetes admin", "Kubernetes expert", "deep K8s",
"cluster administration", "K8s architect"
**Rationale:** Production at Hilton 2016-2020. Re-ramping. Operated at SRE/deployment
layer — not cluster administration.

### Rule 7: Go

**Constraint:** Never claim Go as a primary language.
**Allowed framing:** "Familiar, growing — not a primary language"
**Disallowed phrases:** "Go expert", "Go primary language", "deep Go",
"Go proficiency"
**Rationale:** Familiar with Go, growing — but not a primary language.

### Rule 8: Spinnaker

**Constraint:** Never claim Spinnaker operational depth.
**Allowed framing:** "Source-of-builds consumer" (at Accelya)
**Disallowed phrases:** "Spinnaker expertise", "operated Spinnaker",
"Spinnaker administration"
**Rationale:** At Accelya, Spinnaker was the source-of-builds consumer, not something
Tony operated deeply.

### Rule 9: Experience Anchor

**Constraint:** Use "25+ years" only. Attach to overall engineering career, NOT to cloud.
**Disallowed:** "20+ years", "30+ years", "25+ years in cloud",
"25+ years in DevOps"
**Rationale:** Career began Feb 1995 (~31 years total). 25+ is the agreed anchor across
all materials.

### Rule 10: Education

**Constraint:** Omit education entirely.
**Disallowed:** Any mention of "DeVry", "Electronics Engineering Technology", "B.S.",
"Bachelor's" (unless context requires it and it's from the JD requirements, not claimed
as Tony's credential)
**Rationale:** BS Electronics Engineering Technology from DeVry — no value to add.

### Rule 11: AI Assistance

**Constraint:** Claims should reflect what Tony can do WITH AI assistance, not deep
independent expertise.
**Allowed framing:** "Uses AI tooling extensively to accelerate platform work and ships
faster because of it."
**Rationale:** Tony relies heavily on AI tooling (Claude, Copilot, Windsurf) to
accelerate implementation. This is a strength, but claimed depth should reflect
AI-assisted capability, not deep independent expertise.

### Rule 12: Technologies NOT on Resume

**Constraint:** These technologies must NEVER appear in generated resumes:
- ArgoCD
- Helm
- Kargo
- Consul
- Vault (production)
- Rust
- Temporal
- Ansible (as current competency)

**Rationale:** These are not in Tony's skill set. If a JD requires them, the resume
should not claim them — the gap is noted in the scoring/gaps section instead.

### Rule 13: Contact URLs

**Constraint:** Always render full literal `https://` URLs as VISIBLE text.
**Required:** `https://perkinslab.com`, `https://linkedin.com/in/tonyperkins`,
`https://github.com/tonyperkins`
**Rationale:** ATS parsers routinely miss shortened display text or URLs that live only
in hyperlink targets. Hyperlink is fine as long as visible text is the complete URL.

### Rule 14: Marriott

**Constraint:** Honest 3-bullet version only.
**Allowed:** "Contributed to CI/CD, built NiFi file transfer workflows, participated in
Dynatrace discussions."
**Disallowed:** Any embellishment beyond these three bullets.
**Rationale:** Do not embellish the Marriott role.

### Rule 15: Hilton Location

**Constraint:** Collierville, TN — primarily onsite. Do not frame as remote.
**Allowed:** "Collierville, TN (primarily onsite, near Memphis office)"
**Disallowed:** "Hilton (Remote)", "Remote at Hilton"
**Rationale:** Remote only briefly at the start and during COVID. Do not frame as a
remote role.

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
            'violation': "Uses non-standard experience anchor (must be 25+)",
            'severity': 'medium'
        })

    # Check education omission
    if re.search(r'devry|electronics engineering technology', generated_text, re.I):
        violations.append({
            'rule': 'education_omission',
            'violation': "Mentions education — should be omitted",
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
| Resume generation (standard) | Claude Sonnet 4.6 | Good writing quality, reasonable cost |
| Resume generation (high-value, score ≥8) | Claude Opus 4 | Best quality for top matches |
| Accuracy validation | Claude Haiku 4.5 | Fast, cheap, just constraint checking |
| Cover letter (optional) | Claude Sonnet 4.6 | Good writing, moderate cost |
| Company research | Haiku or Ollama (local) | Summarization, doesn't need expensive model |
