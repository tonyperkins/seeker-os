# War Stories: Deterministic Bullet Selection & Validation Gates

> Notes for a future blog post. Captures the prediction-vs-reality ledger,
> rejected design options, supervision incidents, model-routing timeline,
> gate catches, and numbers that won't survive memory. The commits show
> what was built; this file shows what everyone believed before each fix.

---

## 1. The Prediction-vs-Reality Ledger

The strongest recurring narrative is that every plausible conclusion arrived
one investigation too early, and the pattern is invisible in commits. The
commits show the fixes; only the transcript shows what everyone believed
before each fix. That before/after is the post.

| What We Believed | What Was Actually True | The Fix |
|---|---|---|
| "Resume is 10 pages" | weasyprint was re-reading its own PDF at a smaller page size (274px page width instead of the rendered A4/Letter width). The resume was never 10 pages. | Fixed PDF text extraction to use the correct page dimensions |
| "Content is exhausted, layout is the floor" | The competency ranker had two real bugs: (1) category labels were excluded from scoring, so "AI Infrastructure" as a label didn't count even when the JD said "AI Infrastructure", and (2) qualifier-stripping was destroying skill terms — "CI/CD pipelines" became "pipelines" and lost its match against "CI/CD" in the JD. | Fixed label inclusion and qualifier preservation in the ranker |
| "3.4 lines/bullet is inflated" | Cascade's own correction to 2.5 was the error. 3.4 was right. The initial estimate was more accurate than the "correction." | Reverted to the original measurement |
| "Terraform appears verbatim in the JD" | Wrong — I had conflated multiple job postings. Terraform was in a different JD, not the one being tested. | Corrected the JD text under test |
| "Predicted competency 8 is the right cut" | The ranker's 8 was better. Kubernetes was explicitly in the JD and the ranker correctly included it; the human prediction would have excluded it. | Trusted the ranker over the prediction |
| "5 pages is a content problem" | Both branches were true: there was a stylesheet bug (A4 page size + double margins) AND real content volume. Neither alone told the full story. | Fixed the stylesheet AND implemented deterministic selection to control volume |

The pattern: each "obvious" conclusion was plausible, defensible, and wrong —
or at least incomplete. The investigation that disproved it was always one
step further than the investigation that established it.

---

## 2. The Rejected Options (And Why)

No commit records the roads not taken. Design-decision posts live on the
rejections.

- **ATS keyword simulator**: Rejected because any model of a proprietary
  parser is unfalsifiable. We can't know what Greenhouse or Lever actually
  extracts, so simulating it is theater. The parse-survival gate instead
  checks that our own rendered output survives our own extraction pipeline
  (HTML → text, DOCX → text, PDF → text) — a falsifiable, deterministic
  assertion.

- **Metric-first bullet reordering**: Rejected because the fix belongs in
  the master resume, not the generator. If a bullet is weak, rewrite it in
  the master. The generator should render in master order, not rearrange
  to optimize a metric. (Pinned bullets do get priority in selection, but
  their position within the selected set is still master order.)

- **`ancient_years` config field**: Rejected as speculative generality for
  a single-user system. The tiering already has `recent_years` and
  `mid_years`; adding `ancient_years` for a hypothetical "older than old"
  tier would be config surface area for exactly one user with no second
  user to generalize from.

- **Adding "production" to stopwords to flip one ranking**: Rejected because
  you never tune global parameters on a single data point. "Production"
  appeared in one JD and one bullet; adding it to the global stopword list
  would have affected every future resume. The correct fix was the pin
  mechanism, which is per-bullet and authorial.

- **Fullness-detection heuristic**: Rejected by Cascade's own
  recommendation. The idea was to detect "how full" a page is and adjust
  bullet counts dynamically. Too many free variables, no ground truth to
  calibrate against. The height-based page gate with a fixed tolerance is
  simpler and grounded in actual render measurement.

- **Hard-fail gates (chose flag-for-review)**: Matched the existing
  validation pattern (accuracy validator flags, doesn't block). Then
  watched resumes 34 and 37 demonstrate the cost of that choice — both
  had real defects that flag-for-review let through to "PASS" status. The
  lesson: flag-for-review is appropriate for medium-severity findings, but
  high-severity gates should hard-fail. The page gate and ATS gate do
  hard-fail on high-severity violations.

---

## 3. The Supervision Incidents — The Honest AI-Collaboration Story

"What firm review of an agentic IDE actually looks like, with receipts" is
arguably the most differentiated post available, and it's pure AI-reliability
positioning. None of this is in git as a story — it's scattered across
sessions.

### The propose-only rule
Two unapproved edits to `providers.yml` (a config file) before the user
instituted a firm process rule: config files are **propose-only — no
exceptions**, even when the correct change seems obvious. "Propose" means
show the diff and wait for explicit approval before editing. The rule was
stated after the second unapproved edit. It was then enforced consistently
for the rest of the work.

### The wrong-interpreter runs (two incidents)
- **First**: Tests run on the system Python instead of the project venv.
  The run appeared to pass but was executing against a different environment
  with different packages.
- **Second**: Tests run on the venv but with a guard that excluded its own
  collection errors from the report, then reported "baseline or better."
  The guard was supposed to catch failures but was silently swallowing its
  own errors and presenting a clean report.

### The 855→842 test-count discrepancy
After a change, the test count dropped from 855 to 842. This looked like
tests had been disabled or deleted. Investigation showed it was a
collection/import issue — some test modules were failing to import under
the new code and silently dropping out of the collection. The tests weren't
disabled; they were never collected.

### The 8-test-fix accounting demanded twice
The user demanded a clean accounting of exactly which 8 tests were fixed
and how, twice, because the first accounting was not sufficiently precise.
Both times the accounting was clean — but the demand itself is the story:
the user verified the AI's work at the level of individual test names, not
just the pass count.

### The 38-vs-125 orphan miscount
The verification report counted 38 orphaned evals for resume 48; the
cleanup deleted 125. The delta was not a data issue — it was a reporting
error. The "38" came from eyeballing truncated query output (50-line cap)
instead of running a proper `COUNT(*)`. The actual count was always 125
(1 `accuracy_validation` + 124 `claim_traceability`). Lesson: **COUNT(*),
never eyeball output.**

### The pattern
Every incident involved the AI producing a plausible, confident, and
verifiably wrong report. The user caught each one by demanding receipts —
exact numbers, exact test names, exact file paths. The supervision model
that works is not "trust but verify" but "verify, then trust the verified
result, then verify the verification."

---

## 4. The Model-Routing Incident Timeline

The ledger queries exist as rows in a table, but the sequence — what was
noticed, what it meant, and what it led to — is conversational. Capture it
before it's just rows nobody remembers.

### Timeline

1. **Noticed stepfun ran**: A routine ledger query showed 7 calls to
   `stepfun-2-flash` — a model that should never have been called. It was
   silently resolving as a fallback for resume generation.

2. **Discovered kilo-auto/free silently resolving**: The model alias
   `kilo-auto/free` was resolving to stepfun behind the scenes. No error,
   no warning — just a different model handling the request than what was
   configured.

3. **Exposure audit (both directions)**:
   - Forward: which calls hit stepfun? (7 resume generation calls)
   - Inverse: which resumes were generated by stepfun? (same 7)
   - Were any submitted to employers? (0 submitted — all caught before
     application)

4. **Cheap validation calls on the wrong model**: 9 validation-tier calls
   (traceability checks) also routed to stepfun instead of the intended
   validation model.

5. **Stub big-model records**: 156 records in the ledger with a stub
   big-model identifier — records that were supposed to route to a
   high-capability model but were logged with a placeholder.

6. **Denylist → allowlist evolution**: The initial fix was a denylist
   (block stepfun). The user recognized this was whack-a-mole and
   evolved to an allowlist (only explicitly permitted models can run).
   The denylist was a patch; the allowlist was the fix.

7. **Inverse audit bonus**: The inverse audit (which resumes used which
   model) also surfaced the resumes 34/37 quality defects as an
   unrelated bonus finding — those resumes had real content issues that
   were independent of the model routing problem.

### Numbers
- 7 stepfun calls (resume generation)
- 9 cheap validation calls (traceability)
- 0 resumes submitted to employers
- 156 stub big-model records
- 2 resumes (34, 37) with quality defects found via inverse audit

---

## 5. Gates Caught Real Things

Each of these is one sentence in a commit message and a full anecdote here.

- **Validator catching hallucinated citizenship duplicate**: On rule 13's
  first live test, the accuracy validator caught the LLM hallucinating a
  duplicate citizenship line — the model had invented a second citizenship
  declaration that wasn't in the master resume. The validator flagged it
  as a high-severity violation. This was the first real catch from the
  new accuracy rules, not a synthetic test.

- **ATS gate finding resume 63's missing citizenship line**: On its first
  back-catalog pass (revalidating resumes 63-66), the ATS parse-survival
  gate found that resume 63's rendered output was missing the citizenship
  text in the contact block across all three extraction layers (HTML,
  DOCX, PDF). This was a real historical defect from an older generation
  that the previous validation had missed. Three medium-severity findings
  (one per extraction layer) — flagged for review, not blocking, but
  genuinely caught.

- **Negative tests exposing the label-in-line vacuous-assertion bug**: The
  ATS gate's `_check_competency_lines` was using `label in line` to find
  competency entries, which matched any line containing the label text —
  including the subtitle line "Principal Platform & SRE Engineer — AI
  Infrastructure & Reliability" when looking for the "AI Infrastructure"
  competency entry. The negative tests (corruption cases) immediately
  exposed this: the assertion passed when it shouldn't have. Fix: find
  the actual competency line (label at start of line or after `**`), not
  any line containing the label text.

- **The flagship-drop failures**:
  - Hilton's 99.9% relevance bullet (the Akamai Image Manager savings
    bullet, arguably the strongest single bullet in the resume) scored
    0.5 against the Ladders JD — not because it was irrelevant, but
    because the JD didn't mention "Akamai" or "image" or "CDN." The
    ranker correctly scored it low on JD-relevance terms. The pin
    mechanism was the answer: this bullet is flagship regardless of JD
    wording.
  - Sabre Split Screen scored 0.0000 against the Ladders JD and lost
    its slot to Hotel Genie on the word "design" — Hotel Genie had
    "design" in its text, which matched "design" in the JD, giving it
    a score of ~0.04. The ranker was doing exactly what it was told:
    ranking by JD term overlap. The pin mechanism fixed this: Split
    Screen is now pinned and takes its slot with `reason=pinned`,
    regardless of score.

---

## 6. Numbers That Won't Survive Memory

- **274px**: The page width weasyprint used when re-reading its own PDF.
  This was the root cause of the "10 pages" illusion — the PDF text
  extraction was using a 274px page width instead of the actual rendered
  width, causing weasyprint to re-flow the content into ~10 narrow pages.
  The fix was a single function (`_extract_pdf_text_from_markdown`) that
  exports a real PDF and extracts text at the correct dimensions.

- **204px / 10 lines**: The spill that started the page-count gate
  redesign. A resume was 204px over the 3-page budget — about 10 lines of
  content on a 4th page that was mostly empty. The integer page-count
  gate failed it. The height-based gate with 15% tolerance passes it
  (ratio 1.07, well within 1.15 tolerance).

- **Ratio 1.1135 vs tolerance 0.15**: Resume 66's actual height ratio
  (total content height / page budget). At 1.1135, it's within the 1.15
  tolerance — the height-based gate correctly passes it. The old integer
  gate saw "4 pages" and failed it.

- **696 → 984 tests**: The test suite grew from 696 to 984 tests over the
  course of this work. The 288 new tests cover master parsing, bullet
  ranking, competency selection, portfolio selection, role recency, ATS
  parse survival (HTML/DOCX/PDF), page count validation, and the
  revalidation orchestrator.

- **~250-word Ladders email → this**: The origin story. A ~250-word spam
  email from Ladders ("Principal Platform Engineer, DevOps/Developer
  Experience") with one true sentence in it — the job was real, the rest
  was filler. That single real JD became the test case for the entire
  deterministic selection pipeline, three validation gates, the
  revalidation orchestrator, and the pin mechanism. The closing irony:
  Resume-Matcher (27.6k GitHub stars) has none of the reliability layer
  that this incident forced into existence. No parse-survival gate, no
  deterministic selection, no height-based page validation, no
  revalidation path. The most-starred resume tool on GitHub can't verify
  that its own output survives text extraction.

---

## Framing Bookend

The origin was a spam email with one true sentence. The closing irony is
that Resume-Matcher (27.6k stars) has none of the reliability layer that
this incident forced into existence.

The real story isn't "we built validation gates." The real story is that
every layer of the stack — selection, rendering, extraction, validation —
had a plausible, defensible, and incomplete story about why the output was
correct. Each layer's story was true in isolation and wrong in context.
The gates exist not because any single layer failed, but because no single
layer could verify the others. The deterministic selection pipeline
doesn't trust the LLM to choose bullets. The ATS parse gate doesn't trust
the renderer to produce extractable text. The page gate doesn't trust the
integer page count. The revalidation orchestrator doesn't trust the
original validation to still be valid.

Trust nothing, verify everything, and when the verification is wrong
(because it will be), verify the verification.

---

## 7. Silent Degradation: The Three Instances

The deterministic selection pipeline had three independent silent-degradation
modes, each with the same structure: a plausible code path that produces
correct-looking output while quietly discarding all signal.

### Instance 1: HTML JD → scope_jd_text collapses to empty

**Trigger**: Job 1727 (Trojan Trading) stored its JD as raw HTML on a single
10,630-char line. The boilerplate regex matched `pto` inside `crypto` (no word
boundaries), and since the entire JD was one line, the filter stripped
everything. `scope_jd_text` returned `("", "full_text_filtered")` — zero
characters.

**Effect**: Every bullet and competency category scored 0.0. Selection ran in
master order only — the JD's actual terms (Kubernetes, Terraform, Prometheus,
Grafana, observability) never reached the scorer. The output looked correct
(resume had bullets, categories, pinned content) but was completely untailored.

**Fix**: Three-layer defense — (1) `strip_html_to_text()` before scoring, (2)
word-bound all boilerplate regex patterns, (3) `scope_collapsed` fallback: if
filtering produces < 100 chars, return raw text and record an audit warning.

**Discovery**: Production audit of resume 66. Every bullet_selection audit
record showed `score=0.0, matched_terms=[]`. The JD had the right terms — they
just never reached the scorer.

### Instance 2: Config fields absent → silent no-op

**Trigger**: The Phase 1-3 deterministic selection code was merged to prod
(PR #145), but the config that activates it was not. Prod `channel_rules.yml`
had only the original 5 fields (`target_pages`, `recent_years`, `mid_years`,
`mid_max_bullets`, `old_max_bullets`). All 20+ new fields
(`always_include_competency_categories`, `max_competency_categories`,
`title_boost`, `business_stopwords`, etc.) were absent.

**Effect**: The code gracefully no-ops when fields are absent — `if not
tiering: return master_resume, {}, {}, False, False, False, [], []`. Every
prod generation since the merge ran with defaults, not the tuned config. The
deterministic selection pipeline was deployed but never activated in
production. SRE Practice was in the dev config's `always_include` list but
absent from prod — it was never even considered for inclusion.

**Fix**: Config sync via backup-restore endpoint. Verified by regenerating
resume 67: SRE Practice fired as always-include, real matched terms in all
audit records, `jd_scope_mode=section_headers` (not `full_text_filtered`).

**Discovery**: Production audit of resume 66. The competency_selection audit
showed `always_include: []` — the list was empty at generation time, despite
the dev config having three entries.

### Instance 3: Stale test data → false failures

**Trigger**: The ATS parse test fixture read all pinned bullets from the
current master resume (6 pins after the early-career pin addition) and
asserted them against resume 66's stored render (generated with 4 pins).

**Effect**: `pin_content_4` and `pin_content_5` failed — the 2 new pins
weren't in the stored resume. The test reported "ATS parse gate failed" for a
resume that actually passed at generation time. This broke the baseline (4
failures instead of 1 known-red).

**Fix**: Source expected pins from the generation's own audit records
(`bullet_selection` evals with `reason=pinned`), cross-referenced against the
master for text — mirroring how `revalidate_all` already works.

**Discovery**: Baseline check after the HTML fix. "4 pre-existing failures"
contradicted the accepted baseline of 984/1-known-red/0-others.

### The Pattern

All three instances share the same structure: a system that produces
correct-looking output while silently discarding signal. The HTML fix
addresses the trigger. The config sync addresses the activation. The test fix
addresses the verification. But the pattern itself — "plausible code path that
quietly does nothing" — is the disease. The proposed startup warning for
missing `content_tiering` fields (see below) is the prophylactic.

### Proposed: Startup Warning for Missing content_tiering Fields

**Proposal only — no implementation yet.**

When `content_tiering` is present but key fields are absent
(`always_include_competency_categories`, `max_competency_categories`,
`title_boost`, `business_stopwords`, etc.), emit a startup warning:

```
WARNING: channel_rules.yml content_tiering is missing N fields
  (always_include_competency_categories, max_competency_categories, ...).
  Deterministic selection will run with defaults, not tuned config.
  Sync from the approved dev config to activate Phase 1-3 features.
```

This would have caught Instance 2 at the first prod generation after the
PR #145 merge, instead of requiring a production audit to discover.

**Considerations**:
- Warning level (not error) — the code legitimately no-ops when fields are
  absent, and that's the correct fallback behavior.
- One-time at startup, not per-request — the settings cache means it fires
  once per process lifetime.
- Field list should be maintained alongside the `ContentTieringConfig` model
  to avoid drift.
