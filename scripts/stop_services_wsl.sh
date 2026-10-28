#!/usr/bin/env bash
# Stops the backend (38921) and the frontend (38920) running inside WSL, with their child processes.
# WSL counterpart of stop_services.ps1 + delayed_stop.ps1; called by POST /api/v1/system/shutdown.
set -u

PORTS=(38920 38921)
sleep "${STOP_DELAY:-1.5}"   # let FastAPI flush the HTTP response to the browser

descendants() {
  local child
  for child in $(pgrep -P "$1" 2>/dev/null); do
    [ "$child" = "$$" ] && continue   # the backend spawned this script: never kill ourselves
    descendants "$child"
    echo "$child"
  done
}

for port in "${PORTS[@]}"; do
  for pid in $(ss -ltnp 2>/dev/null | grep ":$port " | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u); do
    pids="$(descendants "$pid") $pid"
    echo "Stopping port $port (PID $pid and children)"
    kill $pids 2>/dev/null
    sleep 1
    kill -9 $pids 2>/dev/null
  done
done
echo "Ports ${PORTS[*]} released."
