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
EVAL_CONFIGS="${EVAL_CONFIGS:-jd_analysis,resume_generation}"
SEEKER_OS_CONFIG_DIR="${SEEKER_OS_CONFIG_DIR:-config}"

# Default model lists per provider
if [ "$PROVIDER" = "kilo" ]; then
  DEFAULT_MODELS="qwen-coder-32b,glm-4-flash,deepseek-chat"
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

EVAL_MODELS="${EVAL_MODELS:-$DEFAULT_MODELS}"

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
IFS=',' read -ra MODELS <<< "$EVAL_MODELS"
IFS=',' read -ra CONFIGS <<< "$EVAL_CONFIGS"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          Model Comparison — promptfoo evals                  ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Provider:  $PROVIDER"
echo "║  API:       $API_BASE_URL"
echo "║  Models:    ${#MODELS[@]} → ${EVAL_MODELS}"
echo "║  Configs:   ${#CONFIGS[@]} → ${EVAL_CONFIGS}"
echo "║  Total runs: $((${#MODELS[@]} * ${#CONFIGS[@]}))"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Summary file
SUMMARY_FILE="$RESULTS_DIR/comparison_${PROVIDER}_$(date +%Y%m%d_%H%M%S).json"
echo "[" > "$SUMMARY_FILE"
FIRST_ENTRY=true

for model in "${MODELS[@]}"; do
  for config_name in "${CONFIGS[@]}"; do
    config_file="$REPO_ROOT/evals/promptfoo/${config_name}.yaml"
    if [ ! -f "$config_file" ]; then
      echo "WARNING: Config $config_file not found, skipping"
      continue
    fi

    output_file="$RESULTS_DIR/${config_name}_${model//\//_}.json"
    label="$config_name / $model"

    echo "── Running: $label ──"

    # Set env vars for promptfoo
    export EVAL_MODEL="$model"
    export "$PROMPTFOO_API_KEY_ENV"="$API_KEY"

    # For Kilo, override the provider prefix and judge to use Kilo gateway
    if [ "$PROVIDER" = "kilo" ]; then
      # Create a temp config with Kilo provider
      temp_config=$(mktemp /tmp/promptfoo_${config_name}_XXXXXX.yaml)
      sed "s|anthropic:messages:|${PROVIDER_PREFIX}:|g; s|api.anthropic.com|${API_BASE_URL}|g" "$config_file" > "$temp_config"
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
      2>&1 | tail -5
    eval_exit=$?
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

# --- Print summary table ---
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "                    SUMMARY TABLE"
echo "═══════════════════════════════════════════════════════════════"
echo ""

python3 - <<'PYEOF'
import json, os, sys

summary_file = os.environ.get("SUMMARY_FILE")
with open(summary_file) as f:
    entries = json.load(f)

# Collect results from each entry's result file
results = []
for entry in entries:
    rf = entry["result_file"]
    model = entry["model"]
    config = entry["config"]
    provider = entry["provider"]
    duration = entry["duration_seconds"]

    if not os.path.exists(rf):
        results.append({
            "model": model, "config": config, "provider": provider,
            "passed": 0, "total": 0, "rate": 0, "tokens": 0, "duration": duration,
            "status": "NO RESULTS",
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
    status = "PASS" if rate >= 85 else "FAIL"

    results.append({
        "model": model, "config": config, "provider": provider,
        "passed": passed, "total": total, "rate": rate,
        "tokens": tokens, "duration": duration, "status": status,
    })

# Group by config, print table
from collections import defaultdict
by_config = defaultdict(list)
for r in results:
    by_config[r["config"]].append(r)

for config, rows in sorted(by_config.items()):
    print(f"\n  ── {config} ──")
    print(f"  {'Model':<30} {'Pass Rate':>12} {'Tokens':>10} {'Time':>8} {'Status':>8}")
    print(f"  {'─'*30} {'─'*12} {'─'*10} {'─'*8} {'─'*8}")
    for r in sorted(rows, key=lambda x: -x["rate"]):
        rate_str = f"{r['passed']}/{r['total']} ({r['rate']:.1f}%)"
        tok_str = f"{r['tokens']:,}" if r["tokens"] else "—"
        time_str = f"{r['duration']}s"
        print(f"  {r['model']:<30} {rate_str:>12} {tok_str:>10} {time_str:>8} {r['status']:>8}")

# Overall best model
print(f"\n  {'═'*72}")
all_rates = defaultdict(list)
for r in results:
    all_rates[r["model"]].append(r["rate"])
print(f"  Overall (avg across configs):")
print(f"  {'Model':<30} {'Avg Pass Rate':>15}")
print(f"  {'─'*30} {'─'*15}")
for model, rates in sorted(all_rates.items(), key=lambda x: -sum(x[1])/len(x[1])):
    avg = sum(rates) / len(rates)
    print(f"  {model:<30} {avg:>14.1f}%")

print(f"\n  Full results: {summary_file}")
PYEOF

echo ""
echo "Done. Individual result files in $RESULTS_DIR/"
