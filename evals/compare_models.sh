#!/usr/bin/env bash
#
# Local model comparison — runs promptfoo evals against multiple models
# and prints a summary table showing pass rates for each.
#
# Supports two backends:
#   1. Anthropic direct (ANTHROPIC_API_KEY)
#   2. Kilo Gateway (KILO_API_KEY) — OpenAI-compatible, access to Qwen, GLM, etc.
#
# Usage:
#   # Compare default model set (Anthropic + Kilo)
#   ./evals/compare_models.sh
#
#   # Compare specific models via Anthropic
#   EVAL_MODELS="claude-haiku-4-5,claude-sonnet-4-6" ./evals/compare_models.sh
#
#   # Compare models via Kilo Gateway
#   PROVIDER=kilo EVAL_MODELS="qwen-coder-32b,glm-4-flash" ./evals/compare_models.sh
#
#   # Only run JD analysis (skip resume generation)
#   EVAL_CONFIGS="jd_analysis" ./evals/compare_models.sh
#
#   # Only run resume generation
#   EVAL_CONFIGS="resume_generation" ./evals/compare_models.sh
#
# Environment:
#   PROVIDER          — "anthropic" (default) or "kilo"
#   EVAL_MODELS       — comma-separated model IDs (defaults below per provider)
#   EVAL_CONFIGS      — comma-separated eval configs to run (default: both)
#   ANTHROPIC_API_KEY — required if PROVIDER=anthropic
#   KILO_API_KEY      — required if PROVIDER=kilo
#   SEEKER_OS_CONFIG_DIR — path to config/ (default: config)
#
# Examples:
#   # Quick Anthropic comparison
#   EVAL_MODELS="claude-haiku-4-5,claude-sonnet-4-6" ./evals/compare_models.sh
#
#   # Kilo gateway — test cheap models
#   PROVIDER=kilo EVAL_MODELS="qwen-coder-32b,glm-4-flash,deepseek-chat" ./evals/compare_models.sh
#
#   # Full comparison across both providers
#   PROVIDER=anthropic EVAL_MODELS="claude-haiku-4-5,claude-sonnet-4-6" ./evals/compare_models.sh
#   PROVIDER=kilo EVAL_MODELS="qwen-coder-32b,glm-4-flash" ./evals/compare_models.sh
#   # Then check evals/results/comparison_*.json for the breakdown

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RESULTS_DIR="$REPO_ROOT/evals/results"

PROVIDER="${PROVIDER:-anthropic}"
EVAL_CONFIGS="${EVAL_CONFIGS:-jd_analysis}"
EVAL_TEST_LIMIT="${EVAL_TEST_LIMIT:-0}"
PARALLEL_MODELS="${PARALLEL_MODELS:-1}"
FAIL_FAST="${FAIL_FAST:-3}"
SEEKER_OS_CONFIG_DIR="${SEEKER_OS_CONFIG_DIR:-config}"

# Default model lists per provider
if [ "$PROVIDER" = "kilo" ]; then
  DEFAULT_MODELS="qwen/qwen3.7-plus,z-ai/glm-5.2,deepseek/deepseek-v4-flash"
  API_KEY_VAR="KILO_API_KEY"
  API_BASE_URL="https://api.kilo.ai/api/gateway"
  PROVIDER_PREFIX="openai:chat"
  PROMPTFOO_API_KEY_ENV="OPENAI_API_KEY"
else
  DEFAULT_MODELS="claude-haiku-4-5,claude-sonnet-4-6"
  API_KEY_VAR="ANTHROPIC_API_KEY"
  API_BASE_URL="https://api.anthropic.com"
  PROVIDER_PREFIX="anthropic:messages"
  PROMPTFOO_API_KEY_ENV="ANTHROPIC_API_KEY"
fi

# --- Resolve model list ---
if [ -n "${EVAL_MODELS:-}" ]; then
  MODEL_LIST="$EVAL_MODELS"
elif [ -n "${EVAL_MODELS_FILE:-}" ] && [ -f "$EVAL_MODELS_FILE" ]; then
  MODEL_LIST=$(grep -v '^#' "$EVAL_MODELS_FILE" | grep -v '^$' | tr '\n' ',' | sed 's/,$//')
else
  MODEL_LIST="$DEFAULT_MODELS"
fi

# --- Validate env ---
API_KEY="${!API_KEY_VAR:-}"
if [ -z "$API_KEY" ]; then
  echo "ERROR: $API_KEY_VAR is not set. Export it before running:"
  echo "  export $API_KEY_VAR=your-key-here"
  exit 1
fi

if ! command -v promptfoo &>/dev/null; then
  echo "ERROR: promptfoo is not installed. Install with: npm install -g promptfoo"
  exit 1
fi

mkdir -p "$RESULTS_DIR"

# Parse comma-separated lists
IFS=',' read -ra MODELS <<< "$MODEL_LIST"
IFS=',' read -ra CONFIGS <<< "$EVAL_CONFIGS"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          Model Comparison — promptfoo evals                  ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Provider:  $PROVIDER"
echo "║  API:       $API_BASE_URL"
echo "║  Models:    ${#MODELS[@]} models"
echo "║  Configs:   ${#CONFIGS[@]} → ${EVAL_CONFIGS}"
echo "║  Total runs: $((${#MODELS[@]} * ${#CONFIGS[@]}))"
if [ "$EVAL_TEST_LIMIT" -gt 0 ]; then
  echo "║  Tests:     ${EVAL_TEST_LIMIT} per model (subset)"
else
  echo "║  Tests:     all golden dataset cases"
fi
echo "║  Parallel:  $PARALLEL_MODELS models at a time"
if [ "$FAIL_FAST" -gt 0 ]; then
  echo "║  Fail fast: after $FAIL_FAST consecutive 0% models"
fi
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Models to test:"
for i in "${!MODELS[@]}"; do
  printf "  %2d. %s\n" $((i+1)) "${MODELS[$i]}"
done
echo ""

# Summary file
SUMMARY_FILE="$RESULTS_DIR/comparison_${PROVIDER}_$(date +%Y%m%d_%H%M%S).json"
echo "[" > "$SUMMARY_FILE"
FIRST_ENTRY=true
CONSECUTIVE_ZERO=0
ABORTED=false

for model in "${MODELS[@]}"; do
  if [ "$ABORTED" = true ]; then
    echo "⏭  Skipping $model (fail-fast triggered)"
    continue
  fi
  for config_name in "${CONFIGS[@]}"; do
    config_file="$REPO_ROOT/evals/promptfoo/${config_name}.yaml"
    if [ ! -f "$config_file" ]; then
      echo "WARNING: Config $config_file not found, skipping"
      continue
    fi

    safe_model="${model//\//_}"
    safe_model="${safe_model//:/_}"
    output_file="$RESULTS_DIR/${config_name}_${safe_model}.json"
    label="$config_name / $model"

    echo "── Running: $label ──"

    # Set env vars for promptfoo
    export EVAL_MODEL="$model"
    export "$PROMPTFOO_API_KEY_ENV"="$API_KEY"
    export EVAL_TEST_LIMIT="$EVAL_TEST_LIMIT"

    # For Kilo, override the provider prefix and judge to use Kilo gateway
    if [ "$PROVIDER" = "kilo" ]; then
      # Create a temp config with Kilo provider
      temp_config="$REPO_ROOT/evals/promptfoo/_tmp_${config_name}_${safe_model}.yaml"
      sed "s|anthropic:messages:|${PROVIDER_PREFIX}:|g; s|https://api.anthropic.com|${API_BASE_URL}|g; s|ANTHROPIC_API_KEY|OPENAI_API_KEY|g" "$config_file" > "$temp_config"
      # Also route the llm-rubric judge through Kilo
      export JUDGE_PROVIDER_ID="${PROVIDER_PREFIX}:${model}"
      export JUDGE_API_BASE_URL="$API_BASE_URL"
      export JUDGE_API_KEY="{{ env.OPENAI_API_KEY }}"
      run_config="$temp_config"
    else
      unset JUDGE_PROVIDER_ID JUDGE_API_BASE_URL JUDGE_API_KEY 2>/dev/null || true
      run_config="$config_file"
    fi

    # Run promptfoo eval
    start_time=$(date +%s)
    set +e
    promptfoo eval \
      --config "$run_config" \
      --no-cache \
      --output "$output_file" \
      --max-concurrency 3 \
      2>&1 | grep -E '^[[:space:]]*[✓✗]|Evaluation|passed|Error|error|FAIL|PASS|%' || true
    eval_exit=${PIPESTATUS[0]}
    set -e
    end_time=$(date +%s)
    duration=$((end_time - start_time))

    # Clean up temp config
    if [ "$PROVIDER" = "kilo" ] && [ -n "${temp_config:-}" ]; then
      rm -f "$temp_config"
    fi

    # Parse results
    if [ -f "$output_file" ]; then
      passed=$(python3 -c "
import json
with open('$output_file') as f:
    data = json.load(f)
tests = data.get('results', {}).get('results', [])
passed = sum(1 for t in tests if t.get('success'))
total = len(tests)
rate = (passed / total * 100) if total > 0 else 0
# Check for empty-output pattern (reasoning models hitting max_tokens)
empty_count = sum(1 for t in tests if not t.get('response', {}).get('output', ''))
if empty_count == total and total > 0:
    print(f'0/{total} (0.0%) EMPTY_OUTPUT')
else:
    print(f'{passed}/{total} ({rate:.1f}%)')
" 2>/dev/null || echo "parse error")

      tokens=$(python3 -c "
import json
with open('$output_file') as f:
    data = json.load(f)
usage = data.get('results', {}).get('usage', {})
total = usage.get('total', 0)
print(f'{total:,}')
" 2>/dev/null || echo "?")
    else
      passed="N/A"
      tokens="?"
    fi

    echo "   Result: $passed | Tokens: $tokens | Time: ${duration}s | Exit: $eval_exit"

    # --- Fail-fast checks ---
    if [ "$FAIL_FAST" -gt 0 ]; then
      # Check for auth/connection errors in the output
      if echo "$passed" | grep -qiE 'auth|401|403|connection|refused|timeout|ECONNREFUSED' || [ ! -f "$output_file" ]; then
        echo "❌ FAIL FAST: Infrastructure error detected — aborting remaining models"
        echo "   Check your API key and network connectivity."
        ABORTED=true
        echo ""
        continue
      fi
      # Check for 0% pass rate (systemic harness issue)
      if echo "$passed" | grep -qE '0/[0-9]+ \(0\.0%\)'; then
        CONSECUTIVE_ZERO=$((CONSECUTIVE_ZERO + 1))
        if echo "$passed" | grep -q 'EMPTY_OUTPUT'; then
          echo "   ⚠  All outputs empty (reasoning model hit max_tokens — increase max_tokens in config)"
        fi
        if [ "$CONSECUTIVE_ZERO" -ge "$FAIL_FAST" ]; then
          echo "❌ FAIL FAST: $CONSECUTIVE_ZERO consecutive models scored 0%"
          echo "   This likely indicates a harness/config issue, not model quality."
          echo "   Check evals/results/ for the last result file to debug."
          ABORTED=true
          echo ""
          continue
        fi
        echo "   ⚠  0% pass rate ($CONSECUTIVE_ZERO/$FAIL_FAST before abort)"
      else
        CONSECUTIVE_ZERO=0
      fi
    fi
    echo ""

    # Append to summary JSON
    if [ "$FIRST_ENTRY" = true ]; then
      FIRST_ENTRY=false
    else
      echo "," >> "$SUMMARY_FILE"
    fi
    python3 -c "
import json
entry = {
    'provider': '$PROVIDER',
    'model': '$model',
    'config': '$config_name',
    'result_file': '$output_file',
    'duration_seconds': $duration,
    'exit_code': $eval_exit,
}
print(json.dumps(entry, indent=2))
" >> "$SUMMARY_FILE"
  done
done

echo "]" >> "$SUMMARY_FILE"
export SUMMARY_FILE
export PROVIDER
export KILO_API_KEY="${KILO_API_KEY:-}"

# --- Print summary table ---
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "                    SUMMARY TABLE"
echo "═══════════════════════════════════════════════════════════════"
echo ""

python3 - <<'PYEOF'
import json, os, sys, urllib.request

summary_file = os.environ.get("SUMMARY_FILE")
provider = os.environ.get("PROVIDER", "anthropic")
kilo_api_key = os.environ.get("KILO_API_KEY", "")

with open(summary_file) as f:
    entries = json.load(f)

# Fetch pricing from Kilo API if using Kilo
kilo_pricing = {}
if provider == "kilo" and kilo_api_key:
    try:
        req = urllib.request.Request(
            "https://api.kilo.ai/api/gateway/models",
            headers={"Authorization": f"Bearer {kilo_api_key}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        for m in data.get("data", []):
            mid = m.get("id", "")
            p = m.get("pricing", {})
            kilo_pricing[mid] = {
                "in": float(p.get("prompt", 0)) * 1_000_000,
                "out": float(p.get("completion", 0)) * 1_000_000,
            }
    except Exception as e:
        print(f"  WARNING: Could not fetch Kilo pricing: {e}", file=sys.stderr)

# Anthropic direct pricing (per MTok)
anthropic_pricing = {
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "claude-sonnet-5": {"in": 2.00, "out": 10.00},
    "claude-opus-4-8": {"in": 5.00, "out": 25.00},
}

# Collect results from each entry's result file
results = []
for entry in entries:
    rf = entry["result_file"]
    model = entry["model"]
    config = entry["config"]
    duration = entry["duration_seconds"]

    if not os.path.exists(rf):
        results.append({
            "model": model, "config": config,
            "passed": 0, "total": 0, "rate": 0,
            "tokens": 0, "in_tokens": 0, "out_tokens": 0,
            "cost": 0, "duration": duration, "status": "NO RESULTS",
        })
        continue

    with open(rf) as f:
        data = json.load(f)
    tests = data.get("results", {}).get("results", [])
    passed = sum(1 for t in tests if t.get("success"))
    total = len(tests)
    rate = (passed / total * 100) if total > 0 else 0
    usage = data.get("results", {}).get("usage", {})
    tokens = usage.get("total", 0)
    in_tokens = usage.get("prompt", 0) or usage.get("input", 0)
    out_tokens = usage.get("completion", 0) or usage.get("output", 0)
    # If no aggregate usage, sum from individual test results
    if not tokens:
        for t in tests:
            tu = t.get("tokenUsage", {})
            tokens += tu.get("total", 0)
            in_tokens += tu.get("prompt", 0)
            out_tokens += tu.get("completion", 0)
    status = "PASS" if rate >= 85 else "FAIL"

    # Compute cost
    pricing = None
    if provider == "kilo":
        pricing = kilo_pricing.get(model)
    else:
        pricing = anthropic_pricing.get(model)

    cost = 0.0
    if pricing:
        cost = (in_tokens / 1_000_000 * pricing["in"]) + (out_tokens / 1_000_000 * pricing["out"])

    results.append({
        "model": model, "config": config,
        "passed": passed, "total": total, "rate": rate,
        "tokens": tokens, "in_tokens": in_tokens, "out_tokens": out_tokens,
        "cost": cost, "duration": duration, "status": status,
    })

# Group by config, print table
from collections import defaultdict
by_config = defaultdict(list)
for r in results:
    by_config[r["config"]].append(r)

for config, rows in sorted(by_config.items()):
    print(f"\n  ── {config} ──")
    print(f"  {'Model':<35} {'Pass Rate':>12} {'Tokens':>10} {'Cost':>8} {'Time':>7} {'Status':>7}")
    print(f"  {'─'*35} {'─'*12} {'─'*10} {'─'*8} {'─'*7} {'─'*7}")
    for r in sorted(rows, key=lambda x: -x["rate"]):
        rate_str = f"{r['passed']}/{r['total']} ({r['rate']:.1f}%)"
        tok_str = f"{r['tokens']:,}" if r["tokens"] else "—"
        cost_str = f"${r['cost']:.4f}" if r["cost"] > 0 else "—"
        time_str = f"{r['duration']}s"
        print(f"  {r['model']:<35} {rate_str:>12} {tok_str:>10} {cost_str:>8} {time_str:>7} {r['status']:>7}")

# Overall best model
print(f"\n  {'═'*82}")
all_rates = defaultdict(list)
all_costs = defaultdict(float)
for r in results:
    all_rates[r["model"]].append(r["rate"])
    all_costs[r["model"]] += r["cost"]
print(f"  Overall (avg across configs):")
print(f"  {'Model':<35} {'Avg Pass Rate':>15} {'Total Cost':>12}")
print(f"  {'─'*35} {'─'*15} {'─'*12}")
for model, rates in sorted(all_rates.items(), key=lambda x: -sum(x[1])/len(x[1])):
    avg = sum(rates) / len(rates)
    cost_str = f"${all_costs[model]:.4f}" if all_costs[model] > 0 else "—"
    print(f"  {model:<35} {avg:>14.1f}% {cost_str:>12}")

print(f"\n  Full results: {summary_file}")
PYEOF

echo ""
echo "Done. Individual result files in $RESULTS_DIR/"
