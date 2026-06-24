# Scoring Rubric — Seeker OS

**Source:** Extracted from Hermes job-scanner skill + `~/projects/job-search/ARCHITECTURE.md`
**Status:** Canonical rubric for Seeker OS (break from Hermes version)

## Overview

Jobs are scored 1–10 against Tony Perkins' SRE/Platform/DevOps profile.
Post threshold: **≥6.0** (configurable).

## Step 0: Evidence Gate

Skip entirely if:
- JD < 500 characters
- No location information available
- City-header location with no "remote" anywhere in JD

## Step 1: Hard Reject (return score=0, do not post)

| Filter | Pattern / Logic |
|---|---|
| Relocation required | `relocation required` in JD |
| Hybrid/onsite outside Austin metro | Austin metro = Austin, Leander, Cedar Park, Round Rock, Georgetown, Pflugerville, Taylor |
| Non-US location (unless JD confirms US eligibility) | Check location field + JD for US/remote confirmation |
| Comp ceiling < $150K | If comp is listed and max < $150K |
| FedRAMP/clearance/TS-SCI | `fedramp`, `security clearance`, `active clearance`, `ts/sci`, `top secret` |
| Customer-facing / pre-sales | `pre-sales`, `solutions architect`, `customer success`, `technical account manager`, `tam ` |
| AI/ML Engineer (non-infra) | Title contains `ai/ml engineer` or `machine learning engineer` AND JD does NOT contain `ml infra`, `ml platform`, `gpu infra`, `model serving`, `mlops` |
| Early career / junior | `early career`, `entry-level`, `new grad`, `junior`, `intern`, `associate engineer` |
| Defense contractor / ITAR | `defense contractor`, `itar`, `classified` |
| Blacklisted company | From `profile.yml` blacklist (e.g. AvidXchange, Fidelity, Marriott, Zapcom) |

**Note:** Large enterprise is NOT a hard reject — it's a scoring penalty (see Step 4:
`large_enterprise` -1.5, `known_large_enterprise` -1.5). Company size data is often
unreliable at card level, so it's handled in scoring rather than as a hard filter.

## Step 2: Base Score

| Title pattern | Base score | Label |
|---|---|---|
| `(principal\|staff).*(sre\|site reliability\|platform\|infra\|devops)` | 4.5 | Principal/Staff SRE/Platform/Infra |
| `senior.*(sre\|site reliability\|platform\|infra)` | 4.0 | Senior SRE/Platform/Infra |
| `senior.*(devops\|cloud engineer)` | 3.5 | Senior DevOps/Cloud |
| `senior.*(release\|build)` | 3.0 | Senior Release/Build |
| `(sre\|site reliability\|platform engineer\|infrastructure engineer\|devops\|cloud engineer)` | 2.0 | Infrastructure title match |
| `software engineer.*(infra\|platform\|cloud\|sre)` | 2.0 | SE on infra/platform team |
| `(infra\|cloud\|security.*cloud).*engineer` | 2.0 | Infra/Cloud Security Engineer |
| JD matches infra role (no title match) | 2.0 | JD matches infrastructure role |
| No match | 0 | No title/JD match for target roles |

## Step 3: Positive Modifiers

| Signal | Points | Pattern |
|---|---|---|
| Austin area (location or JD) | +1.5 | `austin\|leander\|cedar park\|round rock\|georgetown\|pflugerville\|taylor\|texas\|tx` |
| AWS / Amazon Web Services | +1.0 | `aws\|amazon web services` |
| Terraform | +1.0 | `terraform` |
| Remote + US confirmed | +1.0 | `remote` AND (`united states\|us\b\|us-based\|within the us`) |
| Comp ≥ $165K | +1.0 | Structured comp_min ≥ 165000, or regex match in JD |
| "You build it, you run it" | +1.0 | `you build it.*you run it\|build it.*run it\|own.*production` |
| Kubernetes / k8s | +0.5 | `kubernetes\|k8s` |
| CI/CD | +0.5 | `ci/cd\|cicd\|continuous integration\|pipeline` |
| Observability | +0.5 | `prometheus\|grafana\|datadog\|observability\|elk\|splunk` |
| Docker | +0.5 | `docker` |
| Platform / DevEx / golden path | +0.5 | `platform\|developer experience\|devex\|golden path` |
| Small company (100-500) | +0.5 | `small team\|startup\|series [abc]` or company size data |
| AI infra (ml platform, gpu, model serving) | +0.5 | `ml platform\|gpu infra\|model serving\|inference infra` |

## Step 4: Negative Modifiers (Penalties)

| Signal | Points | Pattern |
|---|---|---|
| On-site/relocation required | -3.0 | `on.?site only\|in.?office only\|must.*relocat\|relocation required` |
| Hybrid non-Austin city | -3.0 | `hybrid.*(new york\|chicago\|san francisco\|seattle\|...)` |
| City-only non-Austin (no remote in JD) | -2.0 | Location is just a city, JD never says "remote" |
| Comp below $140K | -3.0 | Structured comp_max < 140000, or regex in JD |
| FedRAMP/clearance | -2.5 | (also hard reject, but if somehow reaches scoring) |
| Pre-sales/SA/TAM | -2.0 | `pre.?sales\|solutions architect\|customer success` |
| People management duties | -2.0 | `performance review\|headcount\|hiring decision\|manage.*team of` |
| Comp $140K–$165K | -1.5 | Structured comp in this range, or regex in JD |
| Follow-the-sun / global 24-7 | -1.5 | `follow.?the?sun\|24.?7 global\|offices? in \d+ countries` |
| Large enterprise (50K+ employees) | -1.5 | `fortune\s*(?:500\|100\|50)\|\b\d{2,3},000\+?\s*employees` |
| Known large enterprise (by name) | -1.5 | `cvs\|walgreens\|bank of america\|wells fargo\|jpmorgan\|chase\|citibank` |
| Staffing agency | -1.5 | `jobs? via dice\|robert half\|akkodis\|jobgether\|intellisoft\|manpower\|randstad\|adecco\|insight global\|tek systems\|staffing\|consulting llc` |
| Extreme on-call (12hr/day) | -2.5 | `(?:12.?hour\|24.?hour).{0,30}(?:on.?call\|shift\|rotation)` or `7\s*days?.{0,30}(?:on.?call\|rotation)` |
| On-call + comp < $200K | -1.0 | On-call rotation mentioned AND comp < 200K |
| On-call + comp ≥ $200K | -0.5 | On-call rotation mentioned AND comp ≥ 200K (partially offsets) |
| K8s 5yr primary requirement | -1.0 | `5\+.*years.*kubernetes` |
| First-line support | -1.0 | `first.?line.*support\|first.?line.*response\|first.*escalation point` |
| GCP primary | -0.5 | `\bgcp\b\|\bgoogle cloud\b` (when GCP is primary cloud) |
| Azure primary (no AWS) | -0.5 | `\bazure\b(?!.*\baws\b)` |
| Compliance heavy (PCI, SOX, HIPAA) | -0.5 | `pci.?dss\|sox\b\|hipaa\|iso.?27001` |
| 10+/15+ years experience bar | -0.5 | `10\+.*years\|15\+.*years` |
| MTS without seniority qualifier | -1.0 | `\bmember of technical staff\b` without senior/staff/principal |
| Generic SWE title | -2.0 | Title is "Software Engineer" without infra/platform/SRE/DevOps/Cloud qualifier |
| Missing location + no remote confirmation | -1.5 | No location AND no "remote"/"united states" in JD |

**Note on comp thresholds vs Tier 2 hard filter:**
The Tier 2 hard filter rejects jobs with `comp_max < 150000` (structured comp only).
The scoring rubric's `comp_below_floor` and `comp_marginal` modifiers apply to
**JD-text-parsed comp** (jobs where structured comp is null/missing). These are
independent:
- Tier 2: structured `comp_max < 150000` → hard reject (never reaches scoring)
- Scoring: JD-text-parsed comp below `comp_below_floor` → -3.0 penalty
- Scoring: JD-text-parsed comp in `comp_marginal` range → -1.5 penalty
- Scoring: structured `comp_min >= comp.target` → +1.0 bonus (target reached)

The `comp_below_floor` and `comp_marginal` thresholds are config fields in
`scoring_rubric.yml`, not hardcoded. They default below `profile.comp.floor` to
catch jobs that slipped through Tier 2 because they had no structured comp field.

## Step 5: Final Clamp

```python
score = max(0, min(10, score))
```

## Per-Company Cap

Max **3 jobs per company** per run. If more score ≥6, post top 3 by score and log skipped.

## Structured-Field Input Optimization (hiring.cafe specific)

For jobs sourced from hiring.cafe, use structured fields instead of regex where possible:

| Rubric input | Regex source (Clawford) | Structured source (hiring.cafe) |
|---|---|---|
| Comp min/max | `\$([0-9,]+)` regex on JD text | `v5_processed_job_data.yearly_min_compensation` (integer) |
| Comp currency | inferred | `v5_processed_job_data.listed_compensation_currency` |
| Workplace type | `remote\|hybrid\|on.?site` regex | `v5_processed_job_data.workplace_type` (enum) |
| Seniority | inferred from title | `v5_processed_job_data.seniority_level` (enum) |
| Skills | regex on JD | `v5_processed_job_data.technical_tools` (array) |

The rubric logic (weights, thresholds, hard rejects) stays identical. Only the input
extraction method improves. This bypasses the known comp-parser bug (free-text dollar
format misreads).

## Freshness Factor (minor, in ranking not scoring)

Jobs are not penalized in the score for age, but age is a minor factor in ranking:
- Jobs posted within 7 days: ranking boost
- Jobs posted 7-14 days: neutral
- Jobs posted 14-30 days: slight ranking penalty
- Jobs posted >30 days: hard filter at Tier 2 (configurable)
