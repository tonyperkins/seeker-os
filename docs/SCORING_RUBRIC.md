# Scoring Rubric — Seeker OS

**Source:** User-configured (`config/scoring_rubric.yml`)
**Status:** Reference documentation for the scoring system

## Overview

Jobs are scored 0–10 against the user's configured profile.
Post threshold: **≥6.0** (configurable in `scoring_rubric.yml`).

## Step 0: Evidence Gate

Skip entirely if:
- JD < 500 characters
- No location information available
- City-header location with no "remote" anywhere in JD

## Step 1: Hard Reject (return score=0, do not post)

Hard rejects are configured in `profile.yml` under `hard_rejects`. Examples:

| Filter | Pattern / Logic |
|---|---|
| Relocation required | `relocation required` in JD |
| Hybrid/onsite outside accepted area | Configure accepted cities in `profile.yml` |
| Non-US location (unless JD confirms US eligibility) | Check location field + JD for US/remote confirmation |
| Comp ceiling below floor | If comp is listed and max < configured floor |
| Clearance required | `security clearance`, `active clearance`, `ts/sci`, `top secret` |
| Customer-facing / pre-sales | `pre-sales`, `solutions architect`, `customer success` |
| Early career / junior | `early career`, `entry-level`, `new grad`, `junior`, `intern` |
| Blacklisted company | From `profile.yml` blacklist |

**Note:** Large enterprise is NOT a hard reject — it's a scoring penalty (see Step 4).
Company size data is often unreliable at card level, so it's handled in scoring rather
than as a hard filter.

## Step 2: Base Score

Base score patterns are configured in `scoring_rubric.yml` under `base_scores`.
First matching pattern wins. Example:

| Title pattern | Base score | Label |
|---|---|---|
| `(principal\|staff).*engineer` | 4.5 | Principal/Staff Engineer |
| `(senior\|sr\\.?).*engineer` | 3.5 | Senior Engineer |
| `engineer` | 2.0 | Engineer title match |
| No match | 0 | No title match |

## Step 3: Positive Modifiers

All matching patterns are summed. Configured in `scoring_rubric.yml` under
`positive_modifiers`. Examples:

| Signal | Points | Example Pattern |
|---|---|---|
| Your city/area (location or JD) | +1.5 | `your_city\|your_state` |
| Key skill | +1.0 | `your_key_skill` |
| Remote + US confirmed | +1.0 | `remote` AND (`united states\|us\b`) |
| Comp ≥ target | +1.0 | Structured comp_min ≥ configured target |
| Small company | +0.5 | `small team\|startup\|series [abc]` |

## Step 4: Negative Modifiers (Penalties)

All matching patterns are summed. Configured in `scoring_rubric.yml` under
`negative_modifiers`. Examples:

| Signal | Points | Example Pattern |
|---|---|---|
| On-site/relocation required | -3.0 | `on.?site only\|relocation required` |
| Hybrid outside accepted area | -3.0 | `hybrid` (unless your city or remote) |
| Comp below floor | -3.0 | Structured comp_max < configured floor |
| People management duties | -2.0 | `performance review\|headcount\|manage.*team of` |
| Large enterprise | -1.5 | `fortune\s*(?:500\|100\|50)` |
| Staffing agency | -1.5 | `staffing\|consulting llc\|recruiting agency` |
| Missing location + no remote | -1.5 | No location AND no "remote" in JD |

**Note on comp thresholds vs Tier 2 hard filter:**
The Tier 2 hard filter rejects jobs with structured comp below the configured floor.
The scoring rubric's comp modifiers apply to **JD-text-parsed comp** (jobs where
structured comp is null/missing). These are independent:
- Tier 2: structured comp below floor → hard reject (never reaches scoring)
- Scoring: JD-text-parsed comp below floor → penalty
- Scoring: structured comp ≥ target → bonus

All thresholds are config fields in `scoring_rubric.yml`, not hardcoded.

## Step 5: Final Clamp

```python
score = max(0, min(10, score))
```

## Per-Company Cap

Max **3 jobs per company** per run (configurable). If more score above threshold,
post top N by score and log skipped.

## Structured-Field Input Optimization (hiring.cafe specific)

For jobs sourced from hiring.cafe, use structured fields instead of regex where possible:

| Rubric input | Regex source | Structured source (hiring.cafe) |
|---|---|---|
| Comp min/max | `\$([0-9,]+)` regex on JD text | `v5_processed_job_data.yearly_min_compensation` (integer) |
| Comp currency | inferred | `v5_processed_job_data.listed_compensation_currency` |
| Workplace type | `remote\|hybrid\|on.?site` regex | `v5_processed_job_data.workplace_type` (enum) |
| Seniority | inferred from title | `v5_processed_job_data.seniority_level` (enum) |
| Skills | regex on JD | `v5_processed_job_data.technical_tools` (array) |

The rubric logic (weights, thresholds, hard rejects) stays identical. Only the input
extraction method improves.

## Freshness Factor (minor, in ranking not scoring)

Jobs are not penalized in the score for age, but age is a minor factor in ranking:
- Jobs posted within 7 days: ranking boost
- Jobs posted 7-14 days: neutral
- Jobs posted 14-30 days: slight ranking penalty
- Jobs posted >30 days: hard filter at Tier 2 (configurable)
