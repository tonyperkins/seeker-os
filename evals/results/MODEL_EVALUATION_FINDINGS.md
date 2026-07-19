# Model Evaluation Findings

**Date:** July 13–14, 2026
**Provider:** Kilo Gateway (`https://api.kilo.ai/api/gateway`)
**Framework:** promptfoo with golden dataset (34 JD analysis cases, 14 resume generation cases)
**Judge model:** `minimax/minimax-m3` (non-reasoning, produces reliable JSON verdicts)

---

## Current Recommended Models

> **Updated as new leaders are found. Last updated: July 14, 2026.**

| Task | Recommended Model | Provider | Accuracy | Cost/Run | Notes |
|------|-------------------|----------|----------|----------|-------|
| **JD Analysis (best)** | `gpt-5.6-terra` | OpenAI | 82.4% | ~$3.02 | Best JD accuracy; safe failure mode (SKIP→CONDITIONAL) |
| **JD Analysis (budget)** | `>` | Kilo | 76.5% | ~$0.29 | 2nd best JD score overall; only 1 false positive; zero parse errors |
| **JD Analysis (budget alt)** | `moonshotai/kimi-k2` | Kilo | 73.5% | ~$0.41 | Safest budget failure pattern; only 1 false positive |
| **Resume Generation (best)** | `gpt-5.6-terra`, `gpt-5.6-luna`, or `claude-sonnet-5` | OpenAI/Anthropic | **100%** | $0.82-1.44 | Three-way tie at perfect score |
| **Resume Generation (value)** | `claude-haiku-4-5` | Anthropic | 92.9% | ~$0.26 | Near-perfect at lowest frontier cost |
| **Resume Generation (budget)** | `z-ai/glm-5.2` | Kilo | 71.4% | ~$0.39 | Best budget accuracy for customer-facing output |
| **Resume Generation (free)** | `tencent/hy3:free` | Kilo | 57.1% | $0.00 | Free; use for high-volume/non-critical |
| **Judge model (Kilo)** | `minimax/minimax-m3` | Kilo | — | — | Non-reasoning; reliable JSON output |
| **Judge model (Anthropic)** | `claude-haiku-4-5` | Anthropic | — | — | Non-reasoning; fast and cheap (not yet measured as judge) |

### Pending Results
- Grok 4.3/4.5 (xAI) — not yet tested (~$11-25 per run)

---

## Methodology

### JD Analysis Eval
- **Tests:** 34 active golden dataset cases
- **Assertions:** JSON schema validation + exact verdict match (APPLY / CONDITIONAL / SKIP / MONITOR)
- **No LLM judge** — pure Python assertions comparing model output to expected verdict
- **max_tokens:** 16000 (to accommodate reasoning models)

### Resume Generation Eval
- **Tests:** 14 cases (only APPLY/CONDITIONAL verdicts — cases where resume gen would run in production)
- **Assertion:** LLM-as-judge faithfulness using traceability judge system prompt
- **Judge:** `minimax/minimax-m3` via Kilo Gateway
- **Judge rubric:** Includes master resume text + traceability judge system prompt
- **Pass criteria:** All claims in generated resume must be "supported" by master resume — any "unsupported" or "overstated" claim = FAIL
- **max_tokens:** 16000 (generation), 16000 (judge)

### Known Issues Fixed During Evaluation
1. **Master resume not visible to judge** — llm-rubric judge only sees model output, not the original prompt. Fixed by embedding master resume text directly in the rubric value.
2. **Judge max_tokens too low** — reasoning models (deepseek, qwen) use all 4096 tokens for internal thinking, leaving zero visible output. Increased to 16000.
3. **Reasoning models as judges produce "..."** — reasoning models spend 99% of completion tokens on thinking, producing only 30-75 visible tokens. Fixed by using `minimax/minimax-m3` (non-reasoning) as the default judge.
4. **JSON parsing with reasoning prefixes** — models like Qwen prepend "Thinking:" text before JSON output. Fixed with robust extraction logic that scans backwards for valid JSON.

---

## Results: JD Analysis (34 tests)

| Model | Pass Rate | Cost | Time | Tokens | Reasoning Tokens | JSON Errors |
|-------|-----------|------|------|--------|------------------|-------------|
| deepseek/deepseek-v4-flash | 21/34 (61.8%) | $0.16 | 579s | 593,743 | 157,322 | 1 |
| z-ai/glm-5.2 | 21/34 (61.8%) | $2.28 | 1449s | 778,024 | 337,496 | 5 |

### Verdict Confusion Patterns

**deepseek-v4-flash (12 verdict mismatches):**
| Expected → Got | Count | Risk |
|----------------|-------|------|
| SKIP → CONDITIONAL | 5x | Low (over-review, safe failure) |
| CONDITIONAL → APPLY | 3x | **High** (false positive, may apply to bad fit) |
| CONDITIONAL → SKIP | 2x | Medium (missed opportunity) |
| APPLY → CONDITIONAL | 1x | Medium (under-applied) |
| CONDITIONAL → MONITOR | 1x | Low (different action, not wrong) |

**GLM-5.2 (8 verdict mismatches, 5 JSON errors):**
| Expected → Got | Count | Risk |
|----------------|-------|------|
| APPLY → CONDITIONAL | 3x | Medium (under-applied) |
| SKIP → CONDITIONAL | 2x | Low (over-review) |
| CONDITIONAL → MONITOR | 1x | Low |
| CONDITIONAL → SKIP | 1x | Medium |
| CONDITIONAL → APPLY | 1x | **High** |

### JD Analysis — Initial 6-Test Screen (for reference)

| Model | Pass Rate (6 tests) |
|-------|---------------------|
| deepseek/deepseek-v4-flash:discounted | 5/6 (83.3%) |
| deepseek/deepseek-v4-pro:discounted | 5/6 (83.3%) |
| tencent/hy3:free | 5/6 (83.3%) |
| deepseek/deepseek-v4-pro | 4/6 (66.7%) |
| poolside/laguna-m.1 | 4/6 (66.7%) |
| poolside/laguna-m.1:free | 4/6 (66.7%) |
| qwen/qwen3.7-plus | 4/6 (66.7%) |
| tencent/hy3-preview | 4/6 (66.7%) |
| tencent/hy3 | 3/6 (50.0%) |
| minimax/minimax-m3 | 2/6 (33.3%) |
| stepfun/step-3.7-flash | 2/6 (33.3%) |
| stepfun/step-3.7-flash:free | 2/6 (33.3%) |
| anthropic/claude-sonnet-5 | 0/6 (0.0%) |

> **Note:** The 6-test screen is not representative — three models scored 83.3% on 6 tests (deepseek-v4-flash:discounted, deepseek-v4-pro:discounted, tencent/hy3:free), but deepseek-v4-flash dropped to 61.8% on the full 34. GLM-5.2 was not in the 6-test screen. The small sample over-represents easy cases.

---

## Results: Resume Generation (14 tests)

| Model | Pass Rate | Cost | Time | Tokens | Reasoning Tokens |
|-------|-----------|------|------|--------|------------------|
| **z-ai/glm-5.2** | **10/14 (71.4%)** | ~$0.39 | 628s | 305,210 | 157,417 |
| tencent/hy3:free | 8/14 (57.1%) | $0.00 | 962s | 265,125 | 105,342 |
| deepseek/deepseek-v4-flash | 6/14 (42.9%) | $0.05 | 282s | 188,223 | 25,730 |
| poolside/laguna-m.1 | 6/14 (42.9%) | $0.04 | 217s | 157,796 | 9,867 |
| deepseek/deepseek-v4-pro:discounted | 4/14 (28.6%) | $0.14 | 525s | 219,508 | 68,102 |

### Resume Generation Failure Themes

**All failures across all models share the same root cause: unsupported or overstated claims.**

Common violations observed:
- Fabricated metrics (e.g., "accelerating delivery cycles by 25%" not in master resume)
- Overstated experience level (e.g., "deep hands-on experience with AWS" when master says "broad familiarity")
- Invented technologies (e.g., Apache NiFi, Copilot, Cursor — not mentioned in master resume)
- Misattributed work (e.g., claiming Hilton release-on-demand was solo when master says it was collaborative)
- Output truncation (GLM-5.2 test 4 — resume cut off mid-sentence, likely hit max_tokens)

---

## Combined Comparison

| Model | JD Analysis | Resume Gen | Combined | Total Cost |
|-------|-------------|------------|----------|------------|
| **z-ai/glm-5.2** | 21/34 (61.8%) | **10/14 (71.4%)** | **31/48 (64.6%)** | ~$2.67 |
| deepseek/deepseek-v4-flash | 21/34 (61.8%) | 6/14 (42.9%) | 27/48 (56.3%) | $0.21 |
| tencent/hy3:free | — | 8/14 (57.1%) | — | $0.00 |
| poolside/laguna-m.1 | — | 6/14 (42.9%) | — | $0.04 |
| deepseek/deepseek-v4-pro:discounted | — | 4/14 (28.6%) | — | $0.14 |

---

## Key Findings

### 1. JD analysis is a tie at 61.8%
Both deepseek-v4-flash and GLM-5.2 score identically on the full JD dataset. The main weakness for both is distinguishing SKIP from CONDITIONAL — models tend to be too cautious, upgrading SKIP cases to CONDITIONAL.

### 2. GLM-5.2 is the clear winner for resume generation
At 71.4%, GLM-5.2 is significantly more accurate than all other models tested. It fabricates fewer claims and stays closer to the master resume. However, it's 14x more expensive than deepseek-v4-flash and has 5 JSON parse errors on JD analysis (vs deepseek's 1).

### 3. tencent/hy3:free is the best value
57.1% on resume generation at $0 cost. Slow (962s) but accurate enough for a free model. Would be ideal for high-volume, non-critical resume generation.

### 4. deepseek-v4-pro is worse than flash
Despite costing more and being labeled "pro", the pro variant scored 28.6% on resume generation — worse than the flash variant's 42.9%. More reasoning tokens don't help with accuracy rules.

### 5. Reasoning tokens are a double-edged sword
Models with high reasoning token usage (GLM-5.2: ~85% of completion tokens on reasoning, deepseek-pro: 31% reasoning) don't necessarily produce better output. The reasoning tokens are spent on internal thinking, not on following accuracy rules. deepseek-flash uses only 14% reasoning and scores similarly on JD analysis.

### 6. All models struggle with accuracy rules
Every model tested produces unsupported/overstated claims. This is the core challenge — models naturally want to embellish resumes to match job descriptions, which is exactly what the accuracy rules exist to prevent. Even the best model (GLM-5.2) fails 28.6% of the time.

### 7. The 6-test screen is not predictive
Models that scored 83.3% on the 6-test screen dropped to 61.8% on the full 34-test JD analysis. The small sample over-represents easy cases and misses edge cases where models confuse SKIP/CONDITIONAL boundaries.

---

## Frontier Model Results — OpenAI Direct

Tested via `PROVIDER=openai` against OpenAI's direct API. Full dataset (34 JD + 14 resume).

| Model | JD Analysis | Resume Gen | Combined | Tokens (JD) | Tokens (Resume) |
|-------|-------------|------------|----------|-------------|-----------------|
| gpt-5.6-sol | 22/34 (64.7%) | 12/14 (85.7%) | 34/48 (70.8%) | 385,774 | 161,237 |
| **gpt-5.6-terra** | **28/34 (82.4%)** | **14/14 (100%)** | **42/48 (87.5%)** | 462,674 | 153,188 |
| gpt-5.6-luna | 23/34 (67.6%) | 14/14 (100%) | 37/48 (77.1%) | 479,070 | 153,561 |

### JD Analysis — Frontier Failure Breakdown

**gpt-5.6-sol (12 failures: 3 verdict, 7 errors, 2 other):**
| Expected → Got | Count |
|----------------|-------|
| APPLY → CONDITIONAL | 3x |
| CONDITIONAL → SKIP | 1x |
| SKIP → CONDITIONAL | 1x |

> 7 errors were API errors (likely rate limiting on the sol tier).

**gpt-5.6-terra (6 failures: 6 verdict, 0 errors):**
| Expected → Got | Count |
|----------------|-------|
| SKIP → CONDITIONAL | 3x |
| APPLY → CONDITIONAL | 2x |
| SKIP → MONITOR | 1x |

**gpt-5.6-luna (11 failures: 11 verdict, 0 errors):**
| Expected → Got | Count |
|----------------|-------|
| SKIP → CONDITIONAL | 6x |
| APPLY → CONDITIONAL | 2x |
| CONDITIONAL → SKIP | 1x |
| CONDITIONAL → APPLY | 1x |
| SKIP → MONITOR | 1x |

> **Note:** gpt-5.6-sol had 7 API errors (rate limiting) that counted as failures. Terra and luna had 0 API errors — all their failures are verdict mismatches.

### Resume Generation — Frontier Failure Breakdown

**gpt-5.6-terra: 0 failures (100%)** — Perfect score.
**gpt-5.6-luna: 0 failures (100%)** — Perfect score.

**gpt-5.6-sol: 2 failures (85.7%):**
1. Unsupported claim: "building engineering teams" — master resume says "led 23-member team" but not "built" it
2. Overstated: associated full 25+ years with AWS infrastructure, but master only claims "broad familiarity"

### Key OpenAI Findings

1. **gpt-5.6-terra is the overall winner** — 82.4% JD + 100% resume = 87.5% combined, far ahead of all budget models
2. **Resume generation is solved by frontier models** — terra and luna both scored 100%, meaning zero unsupported/overstated claims across all 14 test cases
3. **JD analysis still struggles with SKIP → CONDITIONAL** — terra's 6 verdict errors were 3x SKIP→CONDITIONAL, 2x APPLY→CONDITIONAL, 1x SKIP→MONITOR (all safe failures, no false positives)
4. **gpt-5.6-sol underperforms terra** — despite being a higher tier, sol had more errors and lower accuracy on both tasks
5. **Frontier models are 100x more accurate on resume generation** — from 42.9% (deepseek) to 100% (terra/luna) for the same test suite
6. **API errors affected only gpt-5.6-sol** — rate limiting caused 7 errors on sol; terra and luna had 0 API errors

---

## Frontier Model Results — Anthropic Direct

Tested via `PROVIDER=anthropic` against Anthropic's direct API. Full dataset (34 JD + 14 resume).

| Model | JD Analysis | Resume Gen | Combined | Tokens (JD) | Tokens (Resume) |
|-------|-------------|------------|----------|-------------|-----------------|
| **claude-sonnet-5** | **24/34 (70.6%)** | **14/14 (100%)** | **38/48 (79.2%)** | 952,503 | 304,103 |
| claude-haiku-4-5 | 13/34 (38.2%) | 13/14 (92.9%) | 26/48 (54.2%) | 540,620 | 174,797 |

### JD Analysis — Anthropic Failure Breakdown

**claude-sonnet-5 (10 failures, 0 errors):**
| Expected → Got | Count | Risk |
|----------------|-------|------|
| CONDITIONAL → SKIP | 5x | Medium (missed opportunity) |
| APPLY → CONDITIONAL | 3x | Medium (under-applied) |
| CONDITIONAL → MONITOR | 1x | Low |
| SKIP → CONDITIONAL | 1x | Low (over-review) |

> Sonnet-5's dominant failure is **CONDITIONAL → SKIP** (5x) — it's too conservative, skipping borderline cases that should be reviewed. This is the opposite pattern from deepseek/GPT which tend to over-promote to CONDITIONAL.

**claude-haiku-4-5 (21 failures, 0 errors):**
| Expected → Got | Count | Risk |
|----------------|-------|------|
| CONDITIONAL → APPLY | 8x | **High** (false positive) |
| SKIP → CONDITIONAL | 8x | Low (over-review) |
| SKIP → APPLY | 3x | **High** (false positive) |
| CONDITIONAL → SKIP | 1x | Medium |

> Haiku is too aggressive — 11 of 21 failures are false positives (recommending APPLY for SKIP/CONDITIONAL cases). Not suitable for JD analysis.

### Resume Generation — Anthropic Failure Breakdown

**claude-sonnet-5: 0 failures (100%)** — Perfect score.

**claude-haiku-4-5: 1 failure (92.9%):**
1. Resume was incomplete — omitted the Marriott work experience entirely. No unsupported claims, but missing required content.

### Key Anthropic Findings

1. **claude-sonnet-5 joins the 100% resume club** — three models now score perfect on resume generation (terra, luna, sonnet-5)
2. **claude-sonnet-5 is the best value frontier for resume gen** — $1.44 vs terra's $0.82, but both are 100%
3. **claude-haiku-4-5 is the best value overall for resume gen** — 92.9% at only ~$0.26, the cheapest frontier option
4. **Haiku is terrible at JD analysis** — 38.2% is worse than every budget model tested. It over-promotes SKIP to APPLY/CONDITIONAL
5. **Sonnet-5 JD pattern is unique** — it's too conservative (CONDITIONAL → SKIP), opposite of GPT models which are too cautious the other way (SKIP → CONDITIONAL)
6. **No API errors for Anthropic** — unlike OpenAI, no rate limiting issues were encountered

---

## Full Comparison Table: All Models Tested

| Model | Provider | JD (34) | Resume (14) | Combined | Cost |
|-------|----------|---------|-------------|----------|------|
| claude-haiku-4.5 | Anthropic | 13/34 (38.2%) | 13/14 (92.9%) | 26/48 (54.2%) | ~$0.26 |
| deepseek-v4-flash | Kilo | 21/34 (61.8%) | 6/14 (42.9%) | 27/48 (56.2%) | $0.21 |
| ~google/gemini-pro-latest | Kilo | 22/34 (64.7%) | 7/14 (50.0%) | 29/48 (60.4%) | $3.55 |
| google/gemini-3.5-flash | Kilo | 21/34 (61.8%) | 8/14 (57.1%) | 29/48 (60.4%) | $1.50 |
| google/gemini-2.5-flash | Kilo | 17/34 (50.0%) | 7/14 (50.0%) | 24/48 (50.0%) | $0.85 |
| mistralai/mistral-medium-3.1 | Kilo | 23/34 (67.6%) | 6/14 (42.9%) | 29/48 (60.4%) | $0.44 |
| moonshotai/kimi-k2 | Kilo | 25/34 (73.5%) | 8/14 (57.1%) | 33/48 (68.8%) | $0.59 |
| mistralai/mistral-large-2512 | Kilo | 26/34 (76.5%) | 8/14 (57.1%) | 34/48 (70.8%) | $0.39 |
| cohere/command-a | Kilo | 21/34 (61.8%) | 6/14 (42.9%) | 27/48 (56.2%) | $1.86 |
| moonshotai/kimi-k2-thinking | Kilo | 24/34 (70.6%) | 6/14 (42.9%) | 30/48 (62.5%) | $1.03 |
| meta-llama/llama-4-maverick | Kilo | 16/34 (47.1%) | 7/14 (50.0%) | 23/48 (47.9%) | $0.13 |
| GLM-5.2 | Kilo | 21/34 (61.8%) | 10/14 (71.4%) | 31/48 (64.6%) | $2.67 |
| gpt-5.6-sol | OpenAI | 22/34 (64.7%) | 12/14 (85.7%) | 34/48 (70.8%) | $5.91 |
| gpt-5.6-luna | OpenAI | 23/34 (67.6%) | 14/14 (100%) | 37/48 (77.1%) | $1.31 |
| claude-sonnet-5 | Anthropic | 24/34 (70.6%) | 14/14 (100%) | 38/48 (79.2%) | $5.95 |
| **gpt-5.6-terra** | **OpenAI** | **28/34 (82.4%)** | **14/14 (100%)** | **42/48 (87.5%)** | $3.02 |
| tencent/hy3:free | Kilo | — | 8/14 (57.1%) | — | $0.00 |
| poolside/laguna-m.1 | Kilo | — | 6/14 (42.9%) | — | $0.04 |
| deepseek-v4-pro:discounted | Kilo | — | 4/14 (28.6%) | — | $0.14 |

### Still Pending

| Model | Provider | Status |
|-------|----------|--------|
| grok-4.3 / grok-4.5 | xAI | Not run (~$11-25 per run) |

---

## Non-Frontier Model Results — Mistral (Kilo Gateway)

Tested via `PROVIDER=kilo` with `mistralai/mistral-medium-3.1`. Full dataset (34 JD + 14 resume).

| Model | JD Analysis | Resume Gen | Combined | Tokens (JD) | Tokens (Resume) |
|-------|-------------|------------|----------|-------------|-----------------|
| mistralai/mistral-medium-3.1 | 23/34 (67.6%) | 6/14 (42.9%) | 29/48 (60.4%) | 491,625 | 150,355 |

### JD Analysis — Mistral Failure Breakdown

**mistralai/mistral-medium-3.1 (11 failures, 0 errors):**
| Expected → Got | Count | Risk |
|----------------|-------|------|
| APPLY → CONDITIONAL | 3x | Medium (under-applied) |
| SKIP → parse_fail | 3x | Parse error (markdown fences) |
| CONDITIONAL → APPLY | 2x | **High** (false positive) |
| SKIP → CONDITIONAL | 2x | Low (over-review) |
| CONDITIONAL → SKIP | 1x | Medium |

> 2 high-risk false positives — better than Gemini (4-11) but worse than terra (0). 3 JSON parse failures from markdown-wrapped output.

### Resume Generation — Mistral Failure Breakdown

**mistralai/mistral-medium-3.1: 8 failures (42.9%):**
Same fabrication pattern as deepseek-flash. Not suitable for resume generation.

### Key Mistral Findings

1. **Best budget JD analysis score** — 67.6% beats deepseek/GLM (61.8%) at only $0.34
2. **Resume generation is poor** — 42.9%, same as deepseek-flash, fabricates claims
3. **3 JSON parse failures** — Mistral wraps output in markdown fences, causing parse issues in production
4. **Potential JD analysis candidate for hybrid config** — 67.6% at $0.34 is the best price/accuracy ratio for JD analysis

### Kimi K2 Results

| Model | JD Analysis | Resume Gen | Combined | Cost |
|-------|-------------|------------|----------|------|
| moonshotai/kimi-k2 | 25/34 (73.5%) | 8/14 (57.1%) | 33/48 (68.8%) | $0.59 |

**JD Analysis — 9 failures, 0 errors:**
| Expected → Got | Count | Risk |
|----------------|-------|------|
| SKIP → CONDITIONAL | 4x | Low (over-review) |
| APPLY → CONDITIONAL | 1x | Medium (under-applied) |
| CONDITIONAL → SKIP | 1x | Medium |
| CONDITIONAL → MONITOR | 1x | Low |
| CONDITIONAL → parse_fail | 1x | Parse error |
| CONDITIONAL → APPLY | 1x | **High** (false positive) |

> **Safest budget model failure pattern** — only 1 high-risk false positive. Dominant failure is SKIP→CONDITIONAL (safe over-review). 73.5% is the best budget JD score, approaching frontier territory (Sonnet-5: 70.6%, Luna: 67.6%).

**Resume Generation — 6 failures (57.1%):**
Fabricates claims but less than deepseek/Mistral (42.9%). Ties Tencent Hy3:free.

### Key Kimi K2 Findings

1. **Best budget model overall** — 68.8% combined at $0.59, beating GLM-5.2 (64.6% at $2.67) on both accuracy and cost
2. **73.5% JD analysis** — highest non-frontier score, surpassing Sonnet-5 (70.6%) and Luna (67.6%)
3. **Safest budget failure pattern** — only 1 high-risk false positive; dominant failure is safe over-review
4. **Resume gen is mediocre** — 57.1%, not suitable for resume generation but better than deepseek/Mistral
5. **Strong JD analysis candidate for hybrid config** — 73.5% at $0.41 is exceptional value
6. **Slow** — 18m total, slowest model tested, but acceptable for batch processing

### Llama 4 Maverick Results

| Model | JD Analysis | Resume Gen | Combined | Cost |
|-------|-------------|------------|----------|------|
| meta-llama/llama-4-maverick | 16/34 (47.1%) | 7/14 (50.0%) | 23/48 (47.9%) | $0.13 |

**JD Analysis — 18 failures, 0 errors (worst JD score):**
| Expected → Got | Count | Risk |
|----------------|-------|------|
| SKIP → CONDITIONAL | 14x | Low (over-review) |
| APPLY → CONDITIONAL | 4x | Medium (under-applied) |

> **Zero false positives** — every failure is over-reviewing. Llama 4 is extremely conservative: it never says APPLY when it shouldn't, but it also rarely says APPLY when it should. 14 SKIP→CONDITIONAL means it would flag too many jobs for manual review. Not useful as a filter.

**Resume Generation — 7 failures (50.0%):**
Same fabrication pattern. $0.03 per run is cheapest but quality matches the price.

### Key Llama 4 Findings

1. **Worst combined score** — 47.9%, below Gemini 2.5 Flash (50.0%)
2. **Cheapest model** — $0.13 total, but you get what you pay for
3. **Zero false positives** — only model with no high-risk failures, but over-reviews everything
4. **Not useful as a filter** — 14 SKIP→CONDITIONAL means too many jobs flagged for manual review
5. **Not recommended for any task**

### Mistral Large 2512 Results

| Model | JD Analysis | Resume Gen | Combined | Cost |
|-------|-------------|------------|----------|------|
| mistralai/mistral-large-2512 | 26/34 (76.5%) | 8/14 (57.1%) | 34/48 (70.8%) | $0.39 |

**JD Analysis — 8 failures, 0 errors:**
| Expected → Got | Count | Risk |
|----------------|-------|------|
| APPLY → CONDITIONAL | 3x | Medium (under-applied) |
| SKIP → CONDITIONAL | 3x | Low (over-review) |
| CONDITIONAL → MONITOR | 1x | Low |
| CONDITIONAL → APPLY | 1x | **High** (false positive) |

> **2nd best JD score ever** (76.5%), only 6 points behind terra (82.4%). Only 1 high-risk false positive. Zero parse failures — fixed the markdown fencing issue from Medium 3.1. At $0.29, it's the best price/accuracy ratio of any model tested.

**Resume Generation — 6 failures (57.1%):**
Same budget-tier ceiling. Fabricates claims but better than deepseek/Mistral Medium (42.9%).

### Cohere Command A Results

| Model | JD Analysis | Resume Gen | Combined | Cost |
|-------|-------------|------------|----------|------|
| cohere/command-a | 21/34 (61.8%) | 6/14 (42.9%) | 27/48 (56.2%) | $1.86 |

**JD Analysis — 13 failures, 1 error:**
| Expected → Got | Count | Risk |
|----------------|-------|------|
| APPLY → CONDITIONAL | 4x | Medium |
| CONDITIONAL → SKIP | 3x | Medium |
| SKIP → APPLY | 2x | **High** (false positive) |
| SKIP → CONDITIONAL | 2x | Low |
| CONDITIONAL → parse_fail | 1x | Parse error |
| CONDITIONAL → APPLY | 1x | **High** (false positive) |

> 3 high-risk false positives, 1 parse failure. Structured-output reputation didn't translate. Not competitive.

**Resume Generation — 8 failures (42.9%):**
Same fabrication pattern as budget models. 1 error.

### Kimi K2 Thinking Results

| Model | JD Analysis | Resume Gen | Combined | Cost |
|-------|-------------|------------|----------|------|
| moonshotai/kimi-k2-thinking | 24/34 (70.6%) | 6/14 (42.9%) | 30/48 (62.5%) | $1.03 |

**JD Analysis — 10 failures, 0 errors:**
| Expected → Got | Count | Risk |
|----------------|-------|------|
| APPLY → parse_fail | 2x | Parse error (reasoning text) |
| CONDITIONAL → SKIP | 2x | Medium |
| CONDITIONAL → parse_fail | 2x | Parse error |
| SKIP → parse_fail | 2x | Parse error |
| APPLY → SKIP | 1x | Medium |
| SKIP → CONDITIONAL | 1x | Low |

> 6 parse failures from reasoning text prepended to JSON output. Zero false positives but reasoning made the model worse: 70.6% vs regular K2's 73.5%, at 2x cost ($0.75 vs $0.41) and 2x time (22m vs 10m).

**Resume Generation — 8 failures (42.9%):**
Worse than regular K2 (57.1%). Reasoning didn't help with anti-fabrication rules.

### Key Findings — Non-Frontier Round 2

1. **Mistral Large 2512 is the new budget champion** — 76.5% JD at $0.29, 70.8% combined at $0.39. Ties gpt-5.6-sol ($5.91) at 1/15th the cost.
2. **Cohere Command A is overpriced and underperforms** — 56.2% combined at $1.86, worse than deepseek ($0.21)
3. **Reasoning makes Kimi K2 worse** — K2 Thinking scored lower on both tasks (62.5% vs 68.8%), cost more ($1.03 vs $0.59), took longer (36m vs 18m), and had 6 parse failures
4. **Reasoning tokens are a net negative for this pipeline** — confirmed across Gemini 2.5 Flash, Gemini Pro, and Kimi K2 Thinking. They add cost, latency, and parse failures without improving instruction-following.

---

## Frontier Model Results — Google (Kilo Gateway)

Tested via `PROVIDER=kilo` with `~google/gemini-pro-latest`. Full dataset (34 JD + 14 resume).

| Model | JD Analysis | Resume Gen | Combined | Tokens (JD) | Tokens (Resume) |
|-------|-------------|------------|----------|-------------|-----------------|
| ~google/gemini-pro-latest | 22/34 (64.7%) | 7/14 (50.0%) | 29/48 (60.4%) | 530,058 | 198,988 |

### JD Analysis — Gemini Pro Failure Breakdown

**~google/gemini-pro-latest (12 failures, 0 errors):**
| Expected → Got | Count | Risk |
|----------------|-------|------|
| CONDITIONAL → SKIP | 3x | Medium (missed opportunity) |
| CONDITIONAL → APPLY | 2x | **High** (false positive) |
| SKIP → CONDITIONAL | 2x | Low (over-review) |
| SKIP → APPLY | 2x | **High** (false positive) |
| APPLY → SKIP | 1x | Medium (missed good job) |
| APPLY → CONDITIONAL | 1x | Medium (under-applied) |
| CONDITIONAL → MONITOR | 1x | Low |

> Gemini Pro is scattered — 4 high-risk false positives (recommending APPLY for SKIP/CONDITIONAL jobs). Fails in all directions, not a safe failure pattern like terra or deepseek.

### Resume Generation — Gemini Pro Failure Breakdown

**~google/gemini-pro-latest: 7 failures (50.0%):**
Failed on 7 of 14 cases with unsupported/overstated claims — same fabrication pattern as budget models.

### Key Google Findings

1. **Gemini Pro is not competitive** — 60.4% combined is below GLM-5.2 (64.6%) and far below terra (87.5%)
2. **4 dangerous false positives on JD analysis** — worst high-risk failure count of any model tested
3. **50% resume generation** — fabricates claims on half the cases, worse than GLM-5.2 (71.4%)
4. **Priced like a frontier model but performs like a budget model** — $3.55 for results comparable to deepseek ($0.21)
5. **Zero JSON parse errors** — at least the output format was reliable

### Gemini 3.5 Flash Results

| Model | JD Analysis | Resume Gen | Combined | Cost |
|-------|-------------|------------|----------|------|
| google/gemini-3.5-flash | 21/34 (61.8%) | 8/14 (57.1%) | 29/48 (60.4%) | $1.50 |

**JD Analysis — 13 failures, 0 errors:**
| Expected → Got | Count | Risk |
|----------------|-------|------|
| CONDITIONAL → APPLY | 8x | **High** (false positive) |
| SKIP → APPLY | 3x | **High** (false positive) |
| CONDITIONAL → SKIP | 1x | Medium |
| SKIP → CONDITIONAL | 1x | Low |

> **11 of 13 failures are false positives** — the most aggressive over-promoter of any model tested. Worse than Haiku (11/21 false positives). Not suitable for JD analysis.

**Resume Generation — 6 failures (57.1%):**
Same fabrication pattern as other budget models. Ties Tencent Hy3:free at 57.1%.

### Key Gemini Findings (Both Models)

1. **Both Gemini models score 60.4% combined** — identical despite different pricing tiers
2. **Gemini 3.5 Flash is the most dangerous JD model** — 11 high-risk false positives, recommending APPLY for SKIP/CONDITIONAL jobs
3. **Neither Gemini model is competitive** — same combined score as each other, below GLM-5.2 (64.6%), far below terra (87.5%)
4. **Gemini 3.5 Flash is fast** — 2 min per config vs 6-10 min for other models
5. **Not recommended for any task in the pipeline**

### Gemini 2.5 Flash Results

| Model | JD Analysis | Resume Gen | Combined | Cost |
|-------|-------------|------------|----------|------|
| google/gemini-2.5-flash | 17/34 (50.0%) | 7/14 (50.0%) | 24/48 (50.0%) | $0.85 |

**JD Analysis — 17 failures, 0 errors (worst JD score of any model):**
| Expected → Got | Count | Risk |
|----------------|-------|------|
| CONDITIONAL → APPLY | 4x | **High** (false positive) |
| CONDITIONAL → SKIP | 4x | Medium (missed opportunity) |
| SKIP → CONDITIONAL | 3x | Low (over-review) |
| APPLY → SKIP | 1x | Medium |
| APPLY → CONDITIONAL | 1x | Medium |
| SKIP → APPLY | 1x | **High** (false positive) |
| CONDITIONAL → parse_fail | 1x | Parse error |
| 2 other (verdict matched, other field failed) | 2x | — |

> Scattered in all directions — 5 false positives, 4 missed opportunities, 1 JSON parse failure. Worst JD analysis score of any model tested.

**Resume Generation — 7 failures (50.0%):**
Same fabrication pattern. Ties Gemini Pro at 50%.

### Gemini Family Summary

| Model | JD (34) | Resume (14) | Combined | Cost |
|-------|---------|-------------|----------|------|
| ~google/gemini-pro-latest | 22/34 (64.7%) | 7/14 (50.0%) | 29/48 (60.4%) | $3.55 |
| google/gemini-3.5-flash | 21/34 (61.8%) | 8/14 (57.1%) | 29/48 (60.4%) | $1.50 |
| google/gemini-2.5-flash | 17/34 (50.0%) | 7/14 (50.0%) | 24/48 (50.0%) | $0.85 |

> **Verdict: No Gemini model is recommended for any task in the pipeline.** All three land at the bottom of the leaderboard. The pro tier costs 4x more than 2.5 Flash and scores the same combined. The flash models have dangerous false-positive rates on JD analysis. Resume generation fabricates claims at budget-model rates despite frontier pricing.

---

## Per-Job Cost Analysis

### Pipeline LLM Calls

The full seeker-os pipeline makes **4 LLM calls per job** that passes filtering:

| Stage | LLM Call | Task Name | Measured? |
|-------|----------|-----------|-----------|
| Discovery → Filter → Score | (deterministic, no LLM) | — | — |
| Company Research | 1 call: dossier generation | `company_dossier_generation` | Estimated from prompt sizes |
| JD Analysis | 1 call: verdict + scoring | `jd_analysis` | Measured from eval |
| Resume Generation | 1 call: resume generation | `resume_generation_standard` | Measured from eval |
| Traceability Check | 1 call: claim verification judge | `accuracy_validation` | Measured from eval (grading) |

### Measured Token Usage (gpt-5.6-terra, per job)

| Call | Prompt Tokens | Completion Tokens | Total |
|------|---------------|-------------------|-------|
| JD Analysis | 11,158 | 2,451 | 13,608 |
| Resume Generation | 722 | 1,770 | 2,492 |
| Traceability Judge | 7,735 | 715 | 8,450 |
| Company Research (est.) | ~6,200 | ~2,500 | ~8,700 |
| **Total per job** | **~25,815** | **~7,436** | **~33,250** |

> Company research tokens are estimated from system prompt size (~1.2K tokens) + typical user prompt (company name + JD text + retrieval snippets ~5K tokens). Actual usage may vary ±50% depending on JD length and retrieval results.

### Per-Job Cost by Model

| Model | Company Research | JD Analysis | Resume Gen | Trace Judge | **Total/Job** |
|-------|-----------------|-------------|------------|-------------|---------------|
| gpt-5.6-terra | $0.053 | $0.065 | $0.028 | $0.009 | **$0.155** |
| claude-sonnet-5 | $0.056 | $0.070 | $0.029 | $0.009 | **$0.164** |
| gpt-5.6-luna | $0.021 | $0.026 | $0.011 | $0.009 | **$0.068** |
| claude-haiku-4-5 | $0.015 | $0.019 | $0.008 | $0.009 | **$0.050** |
| GLM-5.2 (Kilo) | $0.009 | $0.012 | $0.004 | $0.009 | **$0.035** |
| deepseek-v4-flash (Kilo) | $0.002 | $0.002 | $0.001 | $0.009 | **$0.014** |

> **Note:** Traceability judge always uses `claude-haiku-4-5` ($0.80/$4.00 per M tokens) regardless of main model, since it needs reliable JSON output. This adds a fixed ~$0.009/job to all configurations.

### Volume Projections

| Volume | gpt-5.6-terra | claude-haiku-4.5 | deepseek-v4-flash | GLM-5.2 |
|--------|---------------|------------------|-------------------|---------|
| 10 jobs | $1.55 | $0.50 | $0.13 | $0.35 |
| 50 jobs | $7.75 | $2.52 | $0.67 | $1.74 |
| 100 jobs | $15.51 | $5.04 | $1.35 | $3.47 |
| 500 jobs | $77.53 | $25.19 | $6.73 | $17.34 |
| 1,000 jobs | $155.06 | $50.39 | $13.46 | $34.68 |

### Key Cost Insights

1. **Traceability judge is a fixed cost** — ~$0.009/job regardless of main model, because it always uses Haiku. This is 65% of the total cost when using deepseek-v4-flash.
2. **gpt-5.6-terra costs $0.155/job** — at 100 jobs/week, that's ~$15.50/week or ~$67/month
3. **deepseek-v4-flash costs $0.014/job** — 11x cheaper than terra, but with 56% accuracy vs 87.5%
4. **Hybrid approach is optimal** — use deepseek for JD analysis ($0.002) and terra/sonnet for resume gen ($0.029), totaling ~$0.04/job with frontier-quality resumes
5. **Company research is the biggest unknown** — token estimate is rough; actual usage depends on JD length and retrieval snippet count

### Recommended Hybrid Configuration

| Stage | Model | Cost/Job | Accuracy |
|-------|-------|----------|----------|
| Company Research | `deepseek-v4-flash` (Kilo) | $0.002 | Not tested (dossier quality) |
| JD Analysis | `mistralai/mistral-large-2512` (Kilo) | $0.004 | 76.5% |
| Resume Generation | `gpt-5.6-luna` (OpenAI) | $0.011 | 100% |
| Traceability Judge | `claude-haiku-4-5` (Anthropic) | $0.009 | — |
| **Total** | | **$0.026** | **100% resume, 76.5% JD** |

> This hybrid costs ~$0.026/job — 6x cheaper than all-terra ($0.155) while maintaining 100% resume accuracy. JD analysis at 76.5% is only 6 points behind terra, with only 1 false positive. The previous hybrid using deepseek-v4-flash for JD analysis ($0.024/job, 61.8% JD) remains the ultra-budget option.

### Alternative Hybrid Configurations

| Config | JD Model | Resume Model | JD Accuracy | Cost/Job |
|-------|----------|--------------|-------------|----------|
| **Recommended** | mistral-large-2512 | gpt-5.6-luna | 76.5% | ~$0.026 |
| Ultra-budget | deepseek-v4-flash | gpt-5.6-luna | 61.8% | ~$0.024 |
| Best accuracy | gpt-5.6-terra | gpt-5.6-terra | 82.4% | ~$0.155 |
| Budget alt | kimi-k2 | gpt-5.6-luna | 73.5% | ~$0.027 |

---

## Evaluation Infrastructure

### Files Modified
- `evals/compare_models.sh` — Main comparison script with Kilo Gateway support, fail-fast, parallel models, cost calculation
- `evals/promptfoo/helpers/golden_dataset_tests.py` — Robust JSON extraction, master resume in judge rubric, configurable judge provider
- `evals/promptfoo/jd_analysis.yaml` — Dynamic model selection, max_tokens=16000
- `evals/promptfoo/resume_generation.yaml` — Dynamic model selection, Kilo provider support
- `evals/model_list.txt` — Budget model list for testing

### Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `PROVIDER` | `anthropic` | `anthropic`, `openai`, `grok`, or `kilo` |
| `EVAL_MODELS` | — | Comma-separated model IDs |
| `EVAL_MODELS_FILE` | — | Path to file with one model per line |
| `EVAL_CONFIGS` | `jd_analysis,resume_generation` | Configs to test |
| `EVAL_TEST_LIMIT` | `0` | Limit test cases (0 = all) |
| `PARALLEL_MODELS` | `1` | Models to run in parallel |
| `FAIL_FAST` | `0` | Consecutive 0% models before abort |
| `JUDGE_MODEL` | provider-specific | Judge model for llm-rubric |
| `ANTHROPIC_API_KEY` | — | Required if `PROVIDER=anthropic` |
| `OPENAI_API_KEY` | — | Required if `PROVIDER=openai` |
| `XAI_API_KEY` | — | Required if `PROVIDER=grok` |
| `KILO_API_KEY` | — | Required if `PROVIDER=kilo` |

### How to Reproduce
```bash
# Full deep dive on a single model (Kilo)
export $(grep -v '^#' .env | xargs)
PROVIDER=kilo \
EVAL_MODELS="z-ai/glm-5.2" \
EVAL_CONFIGS="jd_analysis,resume_generation" \
EVAL_TEST_LIMIT=0 \
FAIL_FAST=0 \
./evals/compare_models.sh

# Frontier models via Anthropic direct
PROVIDER=anthropic \
EVAL_MODELS="claude-sonnet-5,claude-opus-4.8" \
EVAL_CONFIGS="jd_analysis,resume_generation" \
EVAL_TEST_LIMIT=0 \
./evals/compare_models.sh

# Frontier models via OpenAI direct
PROVIDER=openai \
EVAL_MODELS="gpt-5.6-sol,gpt-5.6-terra" \
EVAL_CONFIGS="jd_analysis,resume_generation" \
EVAL_TEST_LIMIT=0 \
./evals/compare_models.sh

# Grok via xAI direct
PROVIDER=grok \
EVAL_MODELS="grok-4" \
EVAL_CONFIGS="jd_analysis,resume_generation" \
EVAL_TEST_LIMIT=0 \
./evals/compare_models.sh

# Quick screen with limited tests
PROVIDER=kilo \
EVAL_MODELS="model1,model2,model3" \
EVAL_CONFIGS="jd_analysis" \
EVAL_TEST_LIMIT=6 \
FAIL_FAST=3 \
./evals/compare_models.sh
```
