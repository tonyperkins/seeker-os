# Scoring Rubric — Seeker OS

**Source:** User-configured (`config/scoring_rubric.yml`)
**Status:** Reference documentation for the scoring system

## Overview

Jobs are scored 0–10 against the user's configured profile.
Post threshold: **≥6.0** (configurable in `scoring_rubric.yml`).

## Step 0: Evidence Gate

Skip entirely if:
- JD shorter than `min_jd_length` characters (default 500, configurable in `scoring_rubric.yml`)
- No location field **and** no match against any `location_fallback_patterns` in JD text (default: `remote`, `united states`, `\bus\b`)

Both thresholds are configurable in `scoring_rubric.yml` — no hardcoded values in Python.

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
| Domain mismatch | -4.0 | Off-domain pattern density — fires when ≥ `min_distinct_hits` (default 3) **distinct** patterns from `patterns` match the JD text |

**Domain mismatch check (`domain_mismatch`):** Catches roles that match the
title (e.g. "Senior SRE") but actually belong to a different engineering
domain (e.g. carrier/network engineering). The rubric entry supplies a
`patterns` list of off-domain term regexes and a `min_distinct_hits`
threshold (default 3). The check fires when the number of **distinct**
patterns matching the JD text meets the threshold — the same term repeated
many times counts as 1 distinct hit. Matched patterns are recorded in the
score breakdown reason string for auditability. Penalty magnitude, pattern
list, and threshold all live in `scoring_rubric.yml` — nothing domain-specific
in Python.

Example config:

```yaml
- signal: "domain_mismatch"
  check: "domain_mismatch"
  points: -4.0
  min_distinct_hits: 3
  patterns:
    - "\\bcisco\\s+ios\\b"
    - "\\bjuniper\\b"
    - "\\bbgp\\b"
    - "\\bospf\\b"
    - "sd.?wan"
    - "\\bnoc\\b"
    - "carrier.?grade"
    - "\\bmpls\\b"
```

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

---

## Research-Adjusted Score

When company research has run, a separate adjusted score is produced from the base
score plus confidence-gated, deterministic modifiers over dossier fields. This is
**additive and auditable** and **never overwrites the base score** — both `score`
(base) and `research_adjusted_score` are preserved in the `jobs` table.

**Implementation:** `seeker_os/scoring/research_adjustment.py` → `compute_research_adjustment()`

### Modifiers (config-driven, from `company_research.yml`)

| Signal | Direction | Condition |
|---|---|---|
| Layoffs | Negative | Dossier mentions recent layoffs |
| Runway | Negative | Short runway reported (< 12 months) |
| Remote walkback | Negative | Company reversed remote-friendly policy |
| Recurring negative sentiment | Negative | High-confidence recurring themes in sentiment data |

### Rules

- An `is_stub` or no-retrieval dossier produces **zero adjustment** (delta = 0).
- Thin-sample sentiment ratings do not move the score; only high-confidence
  recurring themes do.
- Modifier thresholds and magnitudes live in `config/company_research.yml`.
- The breakdown (factor / delta / confidence / section) is stored in
  `jobs.research_breakdown` as JSON for auditability.

### Formula

```
research_adjusted_score = clamp(base_score + research_delta, min_score, max_score)
```

---

## Net Score (Composite)

The Net score is the final composite that combines the base score, research
adjustment, and AI analysis verdict. It is stored in `jobs.net_score` and is the
primary score shown in the UI.

**Implementation:** `seeker_os/scoring/net_score.py` → `compute_net_score()`

### Formula (Option B: verdict acts as a CAP, not an addend)

```
adjusted = clamp(base_score + research_delta, min_score, max_score)
Net = min(adjusted, verdict_cap)   if analysis exists
Net = adjusted                      if no analysis (fallback)
```

### Verdict Caps (config-driven, from `scoring_rubric.yml` `verdict_caps` section)

| Verdict | Cap | Rationale |
|---|---|---|
| `APPLY` | `null` (no ceiling) | Full adjusted score shows |
| `CONDITIONAL` | e.g. `7.0` | Partial-fit cannot present as top |
| `MONITOR` | e.g. `5.0` | Lower priority |
| `SKIP` | e.g. `3.0` | Low priority |

### Score Preservation

All three score components are preserved separately in the `jobs` table:

| Column | Description |
|---|---|
| `score` | Base heuristic rubric score (Step 5 above) |
| `research_adjusted_score` | Base + research delta, clamped |
| `research_delta` | Signed delta from company research |
| `research_breakdown` | JSON breakdown of research adjustment factors |
| `net_score` | Final composite: min(adjusted, verdict_cap) |
| `analysis_verdict` | AI verdict string (`APPLY`, `CONDITIONAL`, `MONITOR`, `SKIP`) |
| `analysis_delta` | Reserved for future use |

### ScoringConfig fields (from `scoring_rubric.yml`)

| Field | Default | Description |
|---|---|---|
| `min_jd_length` | `500` | Minimum JD character count to pass the evidence gate |
| `location_fallback_patterns` | `["remote", "united states", "\\bus\\b"]` | Regex patterns that signal remote/US work when location field is empty; used in evidence gate and `location_only` modifier |
| `metadata_max_jd_chars` | `8000` | Max JD characters sent to the LLM metadata extractor (company, comp, seniority) |
| `calibration` | see below | Calibration report settings |

The Net score is never computed if no analysis has run — the UI falls back to
showing the base or research-adjusted score.

## Calibration Report

`GET /api/analytics/calibration` measures how well rubric scores predict what
the user actually does. It joins the jobs table against the
`application_events` log to derive the decision per job:

- **applied** — a candidate `applied` event exists (an apply always wins over
  an earlier or later skip)
- **skipped** — a candidate `skipped` or `rejected` event exists
- **ignored** — no decision recorded

The event log is authoritative — job status is not consulted, because status
`rejected` is also written by the pipeline (`scored_rejected`), which is not a
user decision. Jobs are keyed by their effective net score (`net_score` →
`research_adjusted_score` → `score` fallback); unscored jobs are excluded and
counted separately.

Three outputs:

1. **Score-bucket vs. decision-rate table** — per net-score bucket, counts and
   percentages of applied/skipped/ignored. A well-calibrated rubric shows
   applied-rate rising monotonically with score.
2. **Miss lists** — *false positives* (skipped with net ≥
   `high_score_threshold`) and *false negatives* (applied with net <
   `low_score_threshold`). Each entry carries the fired base-score pattern
   label, positive/negative modifiers (signal → realized points), research
   factors, and the AI verdict, so the cause of each miss is inspectable.
3. **Per-modifier precision** — for each rubric signal, of the jobs where it
   fired, what fraction were applied to (`precision`), plus
   `decided_precision` = applied / (applied + skipped), which excludes
   ignored jobs. This identifies miscalibrated modifiers empirically. Signals
   that fired historically but are no longer in the rubric are flagged
   `in_rubric: false`.

   **Read `lift`, not absolute precision.** A broad modifier that fires on
   nearly every job converges toward the overall apply rate
   (`base_apply_rate` = applied / scored), so low absolute precision on a
   broad signal is noise-shaped. `lift` = precision / base_apply_rate: > 1
   means the signal selects for jobs you apply to, < 1 selects against, ≈ 1
   carries no selective signal. `lift` is null when there are no applies yet.

### Config (`scoring_rubric.yml` `calibration` section)

| Field | Default | Description |
|---|---|---|
| `bucket_width` | `1.0` | Net-score bucket width (must be > 0); overridable per request via the `bucket_width` query param |
| `high_score_threshold` | `null` → `post_threshold` | Skipped jobs with net ≥ this are false positives |
| `low_score_threshold` | `null` → `post_threshold` | Applied jobs with net < this are false negatives |

All values are config-driven — no thresholds are hardcoded in Python. When the
`calibration` section is absent the defaults above apply.

The report also surfaces `high_score_unanalyzed` — scored jobs at/above
`high_score_threshold` with no analysis verdict. These jobs have no verdict
cap on their net score, so a pure keyword-matched score presents uncapped;
the count makes the coverage gap visible in the same place misses are.

## Auto-Analysis Policy

JD analysis is manual/on-demand by default (the Analyze button →
`POST /api/jobs/{id}/analysis`). The `auto_analysis` section of
`scoring_rubric.yml` opts in to automatic analysis at the end of each
pipeline run for jobs whose effective net score (`net_score` →
`research_adjusted_score` → `score`) meets `min_score` and that have no
verdict yet. Candidates are analyzed highest-score-first so the rate limit
spends LLM budget where it matters; per-job failures are logged and never
fail the pipeline run.

| Field | Default | Description |
|---|---|---|
| `enabled` | `false` | Turn the policy on; absent section = disabled (current behavior preserved) |
| `min_score` | `null` → `post_threshold` | Effective-net-score floor for auto-analysis |
| `max_per_run` | `10` | Max LLM analyses per pipeline run / backfill batch |

For existing backlogs, `POST /api/jobs/analysis/backfill` runs one batch on
demand: it first re-denormalizes verdicts for jobs that already have a
`job_analyses` row but a NULL `jobs.analysis_verdict` (no LLM call — repairs
rows damaged by DB restores), then analyzes remaining verdict-less
high-scorers up to `max_per_run` (or the request's `limit`). Already-analyzed
jobs are always skipped, so re-running the endpoint is safe and works through
a large backlog in batches.
