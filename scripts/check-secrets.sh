#!/usr/bin/env bash
# Seeker OS — Pre-commit secret guard
# Blocks a commit if:
#   (a) .env or any gitignored config file is staged
#   (b) a staged YAML or Python file contains a literal in a key/token/secret
#       field that is not a ${VAR} reference
#
# Install: see README.md "Pre-commit hook" section.
# Requires: bash, grep. No other dependencies.

set -euo pipefail

# Files that must never be committed
FORBIDDEN_FILES=(
  ".env"
  "config/profile.yml"
  "config/scoring_rubric.yml"
  "config/accuracy_rules.yml"
  "config/identity_rules.yml"
  "config/channel_rules.yml"
  "config/queries.yml"
  "config/providers.yml"
  "config/filters.yml"
  "config/company_research.yml"
  "config/blacklist.txt"
)

# Credential-like field names (lowercase, matched as YAML keys or Python identifiers)
CRED_FIELDS="api_key|apikey|token|secret|password"

errors=0

# Check (a): forbidden files staged
for forbidden in "${FORBIDDEN_FILES[@]}"; do
  if git diff --cached --name-only --full-index | grep -qxF "$forbidden"; then
    echo "ERROR: $forbidden is staged — this file is gitignored and must not be committed." >&2
    errors=$((errors + 1))
  fi
done

# Check (b): literal secrets in staged YAML/Python files
# Get staged YAML and Python files (exclude example configs and this script)
staged_files=$(git diff --cached --name-only --full-index | grep -E '\.(yml|yaml|py)$' | grep -v '\.example\.' || true)

for f in $staged_files; do
  # Skip the secret-check script itself
  [[ "$f" == "scripts/check-secrets.sh" ]] && continue

  # For YAML files: look for credential fields with a literal value (not ${...})
  # Match lines like:  api_key: sk-ant-...  (but NOT  api_key: ${VAR_NAME})
  if [[ "$f" =~ \.(yml|yaml)$ ]]; then
    while IFS= read -r line; do
      # Extract the key and value
      key=$(echo "$line" | sed -n 's/^\s*\([a-zA-Z_][a-zA-Z0-9_]*\)\s*:.*/\1/p')
      value=$(echo "$line" | sed -n 's/^\s*[a-zA-Z_][a-zA-Z0-9_]*\s*:\s*\(.*\)$/\1/p' | sed 's/^["'\'']//;s/["'\'']$//')
      if [[ -n "$key" && -n "$value" ]]; then
        # Check if key is a credential field
        if echo "$key" | grep -qiE "^($CRED_FIELDS)$"; then
          # Allow ${VAR} references, empty values, and safe path fields
          if [[ "$value" != \$\{* && "$value" != "" ]]; then
            # Skip known safe fields
            if [[ "$key" != "oauth_token_path" && "$key" != "token_path" ]]; then
              echo "ERROR: $f has literal value in credential field '$key' — use a \${VAR} reference instead. Put the literal in .env." >&2
              errors=$((errors + 1))
            fi
          fi
        fi
      fi
    done < <(git show ":$f" 2>/dev/null || true)
  fi

  # For Python files: look for assignments to credential-like variables with a literal string
  # Match lines like:  api_key = "sk-ant-..."  (but NOT  api_key = os.environ.get(...))
  if [[ "$f" =~ \.py$ ]]; then
    while IFS= read -r line; do
      # Check for: var = "literal" or var = 'literal' where var is a credential field
      if echo "$line" | grep -qE "^\s*($CRED_FIELDS)\s*=\s*[\"'][^\"']{8,}[\"']"; then
        # Exclude os.environ, os.getenv, ${...}, and test fixtures
        if ! echo "$line" | grep -qE "os\.environ|os\.getenv|test_|mock|fake|example|your-"; then
          echo "ERROR: $f has literal assigned to credential-like variable — use os.environ.get() or a \${VAR} reference." >&2
          errors=$((errors + 1))
        fi
      fi
    done < <(git show ":$f" 2>/dev/null || true)
  fi
done

if [ $errors -gt 0 ]; then
  echo "" >&2
  echo "Secret guard found $errors problem(s). Fix above or use 'git commit --no-verify' to bypass (not recommended)." >&2
  exit 1
fi

exit 0
