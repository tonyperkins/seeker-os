#!/bin/bash
# Seeker OS — Development script
# Starts both the FastAPI backend and Next.js frontend
#
# Usage: ./dev.sh

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

# Check if venv exists
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
  source .venv/bin/activate
  cd backend && pip install -e ".[dev]" && cd ..
else
  source .venv/bin/activate
fi

# Start backend
echo "Starting FastAPI backend on :8000..."
uvicorn seeker_os.api.app:app --reload --port 8000 --app-dir backend &
BACKEND_PID=$!

# Start frontend
echo "Starting Next.js frontend on :3000..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

# Trap exit to kill both processes
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" EXIT INT TERM

echo ""
echo "Seeker OS is running:"
echo "  Backend:  http://localhost:8000"
echo "  API docs: http://localhost:8000/docs"
echo "  Frontend: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both."

wait
