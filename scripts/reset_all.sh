#!/usr/bin/env bash
# Reset all Seeker OS data to a fresh-install state.
#
# Clears:
#   - SQLite database (jobs, dedup, pipeline runs, settings, resumes)
#   - Cache, checkpoints, generated resumes
#   - Master resume file
#   - OAuth tokens
#   - Config files (reset to example templates)
#   - API keys from .env (KILO_API_KEY, ANTHROPIC_API_KEY, etc.)
#
# Usage: ./scripts/reset_all.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Seeker OS — Full Reset ==="
echo ""

# 1. Database
if [ -f "data/seeker.db" ]; then
    echo "Clearing database..."
    if [ -d ".venv" ]; then source .venv/bin/activate; fi
    python3 -c "
from seeker_os.database import get_connection
db = get_connection()
for t in ['resumes', 'dedup_registry', 'jobs', 'pipeline_runs', 'settings']:
    n = db.execute(f'SELECT COUNT(*) as c FROM {t}').fetchone()['c']
    if n > 0:
        db.execute(f'DELETE FROM {t}')
        print(f'  Cleared {t}: {n} rows')
    else:
        print(f'  {t}: already empty')
db.commit()
db.close()
"
else
    echo "  No database file found"
fi
echo ""

# 2. Data files
echo "Clearing data files..."
rm -rf data/cache/* data/checkpoint.json data/resumes/* data/master_resume.* data/.anthropic_oauth.json 2>/dev/null || true
echo "  Cleared cache, checkpoints, resumes, master resume, OAuth tokens"
echo ""

# 3. Config files — reset to example templates
echo "Resetting config files to example templates..."
for cfg in profile filters providers queries scoring_rubric accuracy_rules sources; do
    if [ -f "config/${cfg}.example.yml" ] && [ -f "config/${cfg}.yml" ]; then
        cp "config/${cfg}.example.yml" "config/${cfg}.yml"
        echo "  Reset ${cfg}.yml"
    fi
done
echo ""

# 4. API keys in .env
if [ -f ".env" ]; then
    echo "Removing API keys from .env..."
    # Remove lines containing API key assignments
    sed -i '/^KILO_API_KEY=/d' .env
    sed -i '/^ANTHROPIC_API_KEY=/d' .env
    sed -i '/^OPENAI_API_KEY=/d' .env
    echo "  Removed KILO_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY"
fi
echo ""

echo "=== Reset complete ==="
echo "The app is now in a fresh-install state."
echo "Start the backend and navigate to http://localhost:3000 to begin onboarding."
