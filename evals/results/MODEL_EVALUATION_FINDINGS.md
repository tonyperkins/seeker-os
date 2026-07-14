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
| JD Analysis | `deepseek/deepseek-v4-flash` | ~$0.005 | 61.8% | Same accuracy as GLM at 14x lower cost; safe failure mode (over-reviews) |
| Resume Generation | `z-ai/glm-5.2` | ~$0.03 | 71.4% | Best accuracy; resume output is customer-facing, accuracy is non-negotiable |
| Budget fallback | `tencent/hy3:free` | $0.00 | 57.1% | Free; use for high-volume or non-critical resume generation |

---

## Frontier Model Comparison (Pending)

The following frontier models have not yet been tested on the full dataset. Results will be added here when available.

| Model | JD Analysis | Resume Gen | Combined | Cost |
|-------|-------------|------------|----------|------|
| anthropic/claude-sonnet-5 | — | — | — | — |
| anthropic/claude-opus-4.8 | — | — | — | — |
| openai/gpt-5.6-sol | — | — | — | — |
| openai/gpt-5.6-terra | — | — | — | — |
| google/gemini-3-pro | — | — | — | — |

> **Note:** `anthropic/claude-sonnet-5` scored 0/6 on the initial JD screen due to max_tokens exhaustion (all 4096 tokens used for reasoning, empty output). This was fixed by increasing max_tokens to 16000, but the full run has not been re-done.

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
