#!/usr/bin/env bash
# Daily database backup for the WSL install: exports nba_platform with db_transfer.py, verifies the new dump
# and keeps only the newest $BACKUP_KEEP automatic dumps (named nba_platform_YYYYmmdd_HHMM; hand-named ones stay).
# Run by nba-backup.timer. The export takes one consistent snapshot, so it is safe while the tick writes.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${BACKUP_DIR:-$HOME/ArchetypeNBA-backups}"
KEEP="${BACKUP_KEEP:-7}"
PYTHON="$PROJECT_DIR/.venv/bin/python"
DUMPS="$OUT_DIR/nba_platform_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9].dump"

cd "$PROJECT_DIR/backend"
"$PYTHON" scripts/db_transfer.py export --out-dir "$OUT_DIR"

newest="$(ls -1t $DUMPS | head -n 1)"
"$PYTHON" scripts/db_transfer.py verify "$newest"

ls -1t $DUMPS | tail -n +"$((KEEP + 1))" | while read -r old; do
  echo "Pruning $old"
  rm -f -- "$old" "${old%.dump}.manifest.json"
done
