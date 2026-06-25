# hiring.cafe `__NEXT_DATA__` Field Reference

**Source:** Empirical probe (2026-06-18) + verification (2026-06-23)
**Access:** `curl -s "https://hiring.cafe/jobs/{query-slug}"` → extract `<script id="__NEXT_DATA__">` JSON

## Top-Level Structure

```
props.pageProps = {
  ssrHits: [...],           // array of job cards (20 per page)
  ssrPage: 0,               // current page (0-indexed)
  ssrTotalCount: 1023,      // total results for this query
  ssrCompanyCount: 618,     // unique companies
  ssrPageSize: 20,          // results per page
  ssrIsLastPage: false,     // is this the last page?
  ssrError: null,           // error state
  initialSearchState: {...},// the search query + location context
  metadata: {...},          // SEO metadata
}
```

## Job Card Fields (each item in `ssrHits[]`)

### Identity & Source

| Field | Type | Example | Maps to |
|---|---|---|---|
| `.id` | string | `"grnhse___trexsolutions___8534403002"` | Composite dedup key |
| `.source` | string | `"grnhse"` | ATS platform (see source map) |
| `.board_token` | string | `"trexsolutions"` | Company slug on ATS |
| `.apply_url` | string | `"https://www.trexsolutionsllc.com/..."` | Canonical ATS URL |
| `.objectID` | string | (same as .id usually) | Algolia object ID |
| `.requisition_id` | string | varies | ATS requisition ID |
| `.collapse_key` | string | varies | hiring.cafe's own dedup key |
| `.is_hc_pinned` | boolean | `true` / `false` | Skip if true (sponsored) |
| `.hc_pinned_slug` | string | (only if pinned) | Pinned job slug |

### Job Information

| Field | Type | Example | Maps to |
|---|---|---|---|
| `.job_information.title` | string | `"DevOps Engineer"` | Raw title |
| `.job_information.description` | string | (often empty/short) | Brief description |
| `.job_title` | string | `"DevOps Engineer"` | Same as above |

### Processed Job Data (v5)

Located at `.v5_processed_job_data`:

| Field | Type | Example | Maps to |
|---|---|---|---|
| `.core_job_title` | string | `"DevOps Engineer"` | Normalized title |
| `.formatted_workplace_location` | string | `"Annapolis Junction or Fort Meade"` | Location string |
| `.workplace_cities` | array | `["Cupertino, CA, US"]` | City list |
| `.workplace_countries` | array | `["US"]` | Country list |
| `.workplace_states` | array | `["CA, US"]` | State list |
| `.workplace_type` | string | `"Remote"` / `"On-Site"` / `"Hybrid"` | Remote policy |
| `.commitment` | array | `["Full Time"]` | Employment type |
| `.yearly_min_compensation` | integer/null | `150000` | Comp min (USD) |
| `.yearly_max_compensation` | integer/null | `250000` | Comp max (USD) |
| `.listed_compensation_currency` | string | `"USD"` | Currency |
| `.listed_compensation_frequency` | string | `"yearly"` | Frequency |
| `.seniority_level` | string | `"Senior Level"` / `"Mid Level"` | Seniority |
| `.role_type` | string | `"Individual Contributor"` | Role type |
| `.job_category` | string | `"Engineering"` | Category |
| `.technical_tools` | array | `["AWS", "Docker", "Kubernetes", ...]` | Skills/tools |
| `.requirements_summary` | string | `"Fully cleared DevOps Engineer..."` | 1-2 sentence summary |
| `.estimated_publish_date` | string (ISO) | `"2026-06-18T23:43:55.966Z"` | Date posted |
| `.company_name` | string | `"TREX Solutions"` | Company name |
| `.company_tagline` | string | `"..."` | Company tagline |

### Processed Job Data (v7)

Located at `.v7_processed_job_data` (richer nested structure):

| Field | Type | Notes |
|---|---|---|
| `.work_arrangement.workplace_type` | string | Same as v5 |
| `.work_arrangement.workplace_locations` | array | Objects with city/state/country_code |
| `.work_arrangement.commitment` | array | Same as v5 |
| `.compensation_and_benefits.salary` | object | `{low, high, currency, frequency}` |
| `.experience_requirements.requirements_summary` | string | Same as v5 |
| `.company_profile` | object | Company details |

### Company Data

Located at `.enriched_company_data`:

| Field | Type | Example |
|---|---|---|
| `.status` | string | `"VALID_COMPANY"` |
| `.name` | string | `"TREX Solutions"` |
| `.homepage_uri` | string | `"trexsolutionsllc.com"` |
| `.tagline` | string | `"..."` |

## Source Name Mapping

| hiring.cafe `source` | Canonical name | Currently scanned directly? |
|---|---|---|
| `grnhse` | `greenhouse` | YES |
| `ashby` | `ashby` | YES |
| `lever` | `lever` | YES |
| `workday` | `workday` | YES (PANW, CrowdStrike) |
| `icims2` | `icims` | NO — new |
| `bamboohr` | `bamboohr` | NO — new |
| `brassring` | `brassring` | NO — new |
| `paylocity` | `paylocity` | NO — new |
| `rippling` | `rippling` | NO — new |
| `adp` | `adp` | NO — new |
| `smartrecruiters` | `smartrecruiters` | NO — new |
| `taleo_careersection` | `taleo` | NO — new |
| `taleo_rss` | `taleo` | NO — new |
| `oraclecloud` | `oraclecloud` | NO — new |
| `ultipro` | `ultipro` | NO — new |
| `jazzhr` | `jazzhr` | NO — new |
| `breezy` | `breezy` | NO — new |
| `pinpoint` | `pinpoint` | NO — new |
| `sparkhire` | `sparkhire` | NO — new |
| `eightfold` | `eightfold` | NO — new |
| `paycor` | `paycor` | NO — new |
| `saashr` | `saashr` | NO — new |
| `hrmdirect` | `hrmdirect` | NO — new |
| `hiring_cafe_pin` | SKIP | Sponsored/pinned — exclude |

## ID Decomposition

The `.id` field decomposes as `{source}___{board_token}___{jobid}`:

```
grnhse___trexsolutions___8534403002
  → source: grnhse → greenhouse
  → board: trexsolutions
  → jobid: 8534403002
  → canonical key: greenhouse:trexsolutions:8534403002
```

URL-encoded IDs need decoding first:
```
careflow%2FEA.00A → careflow/EA.00A (after URL decode)
```

## Query Result Counts (verified 2026-06-23)

| Query slug | Total results | Companies |
|---|---|---|
| `senior-devops-engineer-remote` | 1,023 | 618 |
| `senior-devops-engineer-remote-us` | 130 | 87 |
| `senior-sre-remote` | 339 | 121 |
| `senior-site-reliability-engineer-remote` | 173 | 121 |
| `staff-platform-engineer-remote` | 206 | ~100 |
| `principal-devops-engineer-remote` | 49 | 42 |
| `staff-sre-remote` | 28 | 27 |
| `principal-sre-remote` | 21 | 17 |
| `senior-infrastructure-engineer-remote` | 994 | 597 |
| `senior-cloud-engineer-remote` | 3,851 | 1,632 |
| `senior-platform-engineer-remote` | 1,930 | 1,013 |

## Notes

- "remote" in the query string acts as a server-side filter — results are overwhelmingly Remote
- "senior" in the query string filters to Senior Level seniority
- More specific queries (staff-sre, principal-sre) return much smaller, more targeted sets
- Page 0 returns ~20 results (sometimes 21 with a pinned job)
- Pinned jobs should always be filtered out (`is_hc_pinned == true` or `source == "hiring_cafe_pin"`)
- ~50% of hits have structured compensation (integer); other 50% have null comp

## ⚠ Seniority Enum — Probe Results (2026-06-23)

A probe across all 8 queries (167 total hits) confirmed the seniority enum is very coarse:

| `seniority_level` | Count | Notes |
|---|---|---|
| `"Senior Level"` | 155 | Dominant — includes Staff and Principal roles |
| `None` (null) | 8 | No seniority tag at all |
| `"Mid Level"` | 4 | Appears even in senior/staff/principal queries |

**Key finding:** There is NO distinct "Staff Level", "Principal Level", or "Lead" enum
value. Staff and Principal roles are tagged as `"Senior Level"`. The `seniority_level`
field cannot distinguish between Senior, Staff, and Principal — it only distinguishes
Senior-ish from Mid/Entry.

**Implementation guidance:**
- The `seniority_floor` filter should accept `"Senior Level"` (which covers Staff/Principal
  too) and reject `"Mid Level"` / `"Entry Level"` / `"Junior"` / `"Associate"`.
- Use title-based fallback: if `seniority_level` is None, check the title for keywords
  (staff, principal, senior, lead, jr, junior, entry, associate).
- `filters.yml` includes `seniority_unknown_passes: true` so unrecognized/None values
  pass through to scoring rather than being rejected.
- The Staff/Principal distinction is made by the scoring rubric's base_scores patterns
  (which match on title), NOT by the seniority_level field.
