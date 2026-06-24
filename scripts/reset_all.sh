#!/usr/bin/env bash
# Reset all Seeker OS data to a fresh-install state.
#
# Safely stops running backend/frontend processes, clears all data and config,
# then restarts both services.
#
# Clears:
#   - SQLite database (jobs, dedup, pipeline runs, settings, resumes)
#   - Cache, checkpoints, generated resumes
#   - Master resume file
#   - OAuth tokens
#   - Config files (reset to example templates)
#   - API keys from .env (KILO_API_KEY, ANTHROPIC_API_KEY, etc.)
#
# Usage: ./scripts/reset_all.sh [--no-restart]
#   --no-restart  Skip restarting backend/frontend after reset

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

RESTART=true
if [[ "${1:-}" == "--no-restart" ]]; then
    RESTART=false
fi

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

# Kill processes matching a pattern, waiting briefly for them to exit.
kill_pattern() {
    local label="$1"
    local pattern="$2"
    local pids
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [[ -z "$pids" ]]; then
        echo "  $label: not running"
        return 0
    fi
    echo "  $label: stopping (pids: $(echo "$pids" | tr '\n' ' '))"
    # Try graceful SIGTERM first
    echo "$pids" | xargs kill 2>/dev/null || true
    # Wait up to 5 seconds for processes to exit
    for _ in 1 2 3 4 5; do
        sleep 1
        pids=$(pgrep -f "$pattern" 2>/dev/null || true)
        if [[ -z "$pids" ]]; then
            echo "  $label: stopped"
            return 0
        fi
    done
    # Force kill if still running
    echo "  $label: force killing (pids: $(echo "$pids" | tr '\n' ' '))"
    echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 1
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [[ -z "$pids" ]]; then
        echo "  $label: stopped"
    else
        echo "  $label: WARNING — still running (pids: $(echo "$pids" | tr '\n' ' '))"
    fi
}

start_backend() {
    echo "Starting backend (uvicorn on :8000)..."
    if [[ ! -d ".venv" ]]; then
        echo "  ERROR: .venv not found. Create it with: python3 -m venv .venv && source .venv/bin/activate && cd backend && pip install -e ."
        return 1
    fi
    source .venv/bin/activate
    cd backend
    # Start uvicorn in background, redirect output to log file
    nohup uvicorn seeker_os.api.app:app --port 8000 > "$PROJECT_ROOT/data/backend.log" 2>&1 &
    local uvicorn_pid=$!
    cd "$PROJECT_ROOT"
    echo "  uvicorn started (pid: $uvicorn_pid), logs: data/backend.log"
    # Wait for backend to be ready (up to 15s)
    echo "  Waiting for backend to be ready..."
    for i in $(seq 1 15); do
        if curl -sf http://localhost:8000/api/settings > /dev/null 2>&1; then
            echo "  Backend ready (took ${i}s)"
            return 0
        fi
        sleep 1
    done
    echo "  WARNING: backend did not respond within 15s — check data/backend.log"
    return 0
}

start_frontend() {
    echo "Starting frontend (next dev on :3000)..."
    cd frontend
    if [[ ! -d "node_modules" ]]; then
        echo "  Installing dependencies..."
        npm install > /dev/null 2>&1
    fi
    # Start next dev in background, redirect output to log file
    nohup npm run dev > "$PROJECT_ROOT/data/frontend.log" 2>&1 &
    local next_pid=$!
    cd "$PROJECT_ROOT"
    echo "  next dev started (pid: $next_pid), logs: data/frontend.log"
    # Wait for frontend to be ready (up to 30s — Next.js takes a while)
    echo "  Waiting for frontend to be ready..."
    for i in $(seq 1 30); do
        if curl -sf http://localhost:3000 > /dev/null 2>&1; then
            echo "  Frontend ready (took ${i}s)"
            return 0
        fi
        sleep 1
    done
    echo "  WARNING: frontend did not respond within 30s — check data/frontend.log"
    return 0
}

# -----------------------------------------------------------------------------
# 1. Stop running processes
# -----------------------------------------------------------------------------

echo "=== Seeker OS — Full Reset ==="
echo ""
echo "Step 1: Stopping running processes..."
kill_pattern "Backend (uvicorn)" "uvicorn seeker_os"
kill_pattern "Frontend (next dev)" "next dev"
kill_pattern "Frontend (next-server)" "next-server"
echo ""

# -----------------------------------------------------------------------------
# 2. Database
# -----------------------------------------------------------------------------

echo "Step 2: Clearing database..."
if [[ -f "data/seeker.db" ]]; then
    if [[ -d ".venv" ]]; then source .venv/bin/activate; fi
    python3 -c "
from seeker_os.database import get_connection
db = get_connection()
for t in ['resumes', 'dedup_registry', 'jobs', 'pipeline_runs', 'settings']:
    try:
        n = db.execute(f'SELECT COUNT(*) as c FROM {t}').fetchone()['c']
        if n > 0:
            db.execute(f'DELETE FROM {t}')
            print(f'  Cleared {t}: {n} rows')
        else:
            print(f'  {t}: already empty')
    except Exception as e:
        print(f'  {t}: skipped ({e})')
db.commit()
db.close()
"
else
    echo "  No database file found"
fi
echo ""

# -----------------------------------------------------------------------------
# 3. Data files
# -----------------------------------------------------------------------------

echo "Step 3: Clearing data files..."
rm -rf data/cache/* data/checkpoint.json data/resumes/* data/master_resume.* data/.anthropic_oauth.json 2>/dev/null || true
echo "  Cleared cache, checkpoints, resumes, master resume, OAuth tokens"
echo ""

# -----------------------------------------------------------------------------
# 4. Config files — reset to example templates
# -----------------------------------------------------------------------------

echo "Step 4: Resetting config files to example templates..."
for cfg in profile filters providers queries scoring_rubric accuracy_rules sources; do
    if [[ -f "config/${cfg}.example.yml" ]] && [[ -f "config/${cfg}.yml" ]]; then
        cp "config/${cfg}.example.yml" "config/${cfg}.yml"
        echo "  Reset ${cfg}.yml"
    fi
done
echo ""

# -----------------------------------------------------------------------------
# 5. API keys in .env
# -----------------------------------------------------------------------------

echo "Step 5: Removing API keys from .env..."
if [[ -f ".env" ]]; then
    sed -i '/^KILO_API_KEY=/d' .env
    sed -i '/^ANTHROPIC_API_KEY=/d' .env
    sed -i '/^OPENAI_API_KEY=/d' .env
    echo "  Removed KILO_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY"
else
    echo "  No .env file found"
fi
echo ""

# -----------------------------------------------------------------------------
# 6. Restart processes
# -----------------------------------------------------------------------------

if [[ "$RESTART" == "true" ]]; then
    echo "Step 6: Restarting services..."
    echo ""
    start_backend
    echo ""
    start_frontend
    echo ""
    echo "=== Reset complete — services running ==="
    echo "  Backend:  http://localhost:8000  (logs: data/backend.log)"
    echo "  Frontend: http://localhost:3000  (logs: data/frontend.log)"
    echo ""
    echo "Navigate to http://localhost:3000 to begin onboarding."
else
    echo "=== Reset complete (--no-restart) ==="
    echo "The app is now in a fresh-install state."
    echo "Start the backend and frontend manually to begin onboarding."
fi
