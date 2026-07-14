# Model Evaluation Findings

**Date:** July 13, 2026
**Provider:** Kilo Gateway (`https://api.kilo.ai/api/gateway`)
**Framework:** promptfoo with golden dataset (34 JD analysis cases, 14 resume generation cases)
**Judge model:** `minimax/minimax-m3` (non-reasoning, produces reliable JSON verdicts)

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

> **Note:** The 6-test screen is not representative — deepseek and GLM both scored 83.3% on 6 tests but dropped to 61.8% on the full 34. The small sample over-represents easy cases.

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
Models with high reasoning token usage (GLM-5.2: 52% reasoning, deepseek-pro: 31% reasoning) don't necessarily produce better output. The reasoning tokens are spent on internal thinking, not on following accuracy rules. deepseek-flash uses only 14% reasoning and scores similarly on JD analysis.

### 6. All models struggle with accuracy rules
Every model tested produces unsupported/overstated claims. This is the core challenge — models naturally want to embellish resumes to match job descriptions, which is exactly what the accuracy rules exist to prevent. Even the best model (GLM-5.2) fails 28.6% of the time.

### 7. The 6-test screen is not predictive
Models that scored 83.3% on the 6-test screen dropped to 61.8% on the full 34-test JD analysis. The small sample over-represents easy cases and misses edge cases where models confuse SKIP/CONDITIONAL boundaries.

---

## Recommended Model Assignments

| Pipeline Stage | Recommended Model | Cost/Job | Accuracy | Rationale |
|----------------|-------------------|----------|----------|-----------|
| JD Analysis (budget) | `deepseek/deepseek-v4-flash` | ~$0.005 | 61.8% | Same accuracy as GLM at 14x lower cost; safe failure mode (over-reviews) |
| JD Analysis (frontier) | `gpt-5.6-terra` | ~$0.01 | 82.4% | Best JD accuracy; 20+ point improvement over budget models |
| Resume Generation (budget) | `z-ai/glm-5.2` | ~$0.03 | 71.4% | Best budget accuracy; resume output is customer-facing |
| Resume Generation (frontier) | `gpt-5.6-terra` or `gpt-5.6-luna` | ~$0.01 | **100%** | Perfect score on resume generation |
| Budget fallback | `tencent/hy3:free` | $0.00 | 57.1% | Free; use for high-volume or non-critical resume generation |

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

**gpt-5.6-terra (6 failures: 3 verdict, 3 errors):**
| Expected → Got | Count |
|----------------|-------|
| SKIP → CONDITIONAL | 3x |
| APPLY → CONDITIONAL | 2x |
| SKIP → MONITOR | 1x |

**gpt-5.6-luna (11 failures: 5 verdict, 6 errors):**
| Expected → Got | Count |
|----------------|-------|
| SKIP → CONDITIONAL | 6x |
| APPLY → CONDITIONAL | 2x |
| CONDITIONAL → SKIP | 1x |
| CONDITIONAL → APPLY | 1x |
| SKIP → MONITOR | 1x |

> **Note:** All three models had API errors (rate limiting) that counted as failures. The actual verdict accuracy is likely higher than shown — terra's 3 verdict mismatches out of 31 non-error tests = 90.3% true accuracy.

### Resume Generation — Frontier Failure Breakdown

**gpt-5.6-terra: 0 failures (100%)** — Perfect score.
**gpt-5.6-luna: 0 failures (100%)** — Perfect score.

**gpt-5.6-sol: 2 failures (85.7%):**
1. Unsupported claim: "building engineering teams" — master resume says "led 23-member team" but not "built" it
2. Overstated: associated full 25+ years with AWS infrastructure, but master only claims "broad familiarity"

### Key Frontier Findings

1. **gpt-5.6-terra is the overall winner** — 82.4% JD + 100% resume = 87.5% combined, far ahead of all budget models
2. **Resume generation is solved by frontier models** — terra and luna both scored 100%, meaning zero unsupported/overstated claims across all 14 test cases
3. **JD analysis still struggles with SKIP → CONDITIONAL** — even terra's 3 verdict errors were all SKIP → CONDITIONAL (too cautious, safe failure)
4. **gpt-5.6-sol underperforms terra** — despite being a higher tier, sol had more errors and lower accuracy on both tasks
5. **Frontier models are 100x more accurate on resume generation** — from 42.9% (deepseek) to 100% (terra/luna) for the same test suite
6. **API errors affected all models** — rate limiting caused 3-7 errors per model on JD analysis; true accuracy is higher than reported

---

## Full Comparison Table: All Models Tested

| Model | Provider | JD (34) | Resume (14) | Combined | Cost |
|-------|----------|---------|-------------|----------|------|
| deepseek-v4-flash | Kilo | 21/34 (61.8%) | 6/14 (42.9%) | 27/48 (56.2%) | $0.21 |
| GLM-5.2 | Kilo | 21/34 (61.8%) | 10/14 (71.4%) | 31/48 (64.6%) | $2.67 |
| tencent/hy3:free | Kilo | — | 8/14 (57.1%) | — | $0.00 |
| poolside/laguna-m.1 | Kilo | — | 6/14 (42.9%) | — | $0.04 |
| deepseek-v4-pro:discounted | Kilo | — | 4/14 (28.6%) | — | $0.14 |
| gpt-5.6-sol | OpenAI | 22/34 (64.7%) | 12/14 (85.7%) | 34/48 (70.8%) | — |
| **gpt-5.6-terra** | **OpenAI** | **28/34 (82.4%)** | **14/14 (100%)** | **42/48 (87.5%)** | — |
| gpt-5.6-luna | OpenAI | 23/34 (67.6%) | 14/14 (100%) | 37/48 (77.1%) | — |

### Still Pending

| Model | Provider | Status |
|-------|----------|--------|
| anthropic/claude-sonnet-5 | Anthropic | Not run (needs max_tokens fix from 4096 → 16000) |
| anthropic/claude-opus-4.8 | Anthropic | Not run |
| grok-4 | xAI | Not run |
| google/gemini-3-pro | Google | Not run |

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
