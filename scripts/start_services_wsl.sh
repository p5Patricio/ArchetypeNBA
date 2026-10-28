#!/usr/bin/env bash
# Starts the backend (38921) and the frontend (38920) inside WSL, detached, and waits for the health check.
# WSL counterpart of start_services.ps1; Windows launches it at logon through scripts/windows/NBAAnalyticsWSL.vbs.
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS_DIR="$PROJECT_DIR/logs"
BACKEND_PORT="${BACKEND_PORT:-38921}"
FRONTEND_PORT="${FRONTEND_PORT:-38920}"
mkdir -p "$LOGS_DIR"

listening() { ss -ltn 2>/dev/null | grep -q ":$1 "; }

if listening "$BACKEND_PORT"; then
  echo "Backend already listening on $BACKEND_PORT."
else
  cd "$PROJECT_DIR/backend" || exit 1
  setsid nohup "$PROJECT_DIR/.venv/bin/python" -u -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" \
    >> "$LOGS_DIR/backend.log" 2>&1 < /dev/null &
fi

if listening "$FRONTEND_PORT"; then
  echo "Frontend already listening on $FRONTEND_PORT."
else
  cd "$PROJECT_DIR/frontend" || exit 1
  setsid nohup node node_modules/next/dist/bin/next start -p "$FRONTEND_PORT" -H 127.0.0.1 \
    >> "$LOGS_DIR/frontend.log" 2>&1 < /dev/null &
fi

for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$BACKEND_PORT/api/v1/health" | grep -q '"db_connected":true' \
     && curl -sf -o /dev/null "http://127.0.0.1:$FRONTEND_PORT/"; then
    echo "OK: backend :$BACKEND_PORT and frontend :$FRONTEND_PORT are up."
    exit 0
  fi
  sleep 1
done
echo "WARN: services did not become healthy within 60 s; see $LOGS_DIR." >&2
exit 1
