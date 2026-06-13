#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CONFIG="${BTXPOOL_CONFIG:-config.yaml}"
BACKUP_DIR="${BTXPOOL_BACKUP_DIR:-$HOME/.local/share/btxpool/backups}"
RETENTION_DAYS="${BTXPOOL_BACKUP_RETENTION_DAYS:-14}"
mkdir -p "$BACKUP_DIR"

DB_PATH="$(
  .venv/bin/python -c \
    'from pool.config import load_config; print(load_config("'"$CONFIG"'")["database_path"])'
)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_DIR/pool-$STAMP.db"

.venv/bin/python - "$DB_PATH" "$DEST" <<'PY'
import sqlite3
import sys

source_path, destination_path = sys.argv[1:3]
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
destination = sqlite3.connect(destination_path)
with destination:
    source.backup(destination)
result = destination.execute("PRAGMA integrity_check").fetchone()[0]
if result != "ok":
    raise SystemExit(f"backup integrity check failed: {result}")
print(destination_path)
PY

chmod 600 "$DEST"
find "$BACKUP_DIR" -type f -name 'pool-*.db' -mtime "+$RETENTION_DAYS" -delete
