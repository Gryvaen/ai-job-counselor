#!/usr/bin/env bash
# Backup JobMatch Agent local data for personal production use.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_ROOT="${BACKUP_ROOT:-$ROOT/backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
DEST="$BACKUP_ROOT/$STAMP"

mkdir -p "$DEST"

copy_if_exists() {
  local src="$1"
  if [ -e "$src" ]; then
    cp -a "$src" "$DEST/"
    echo "  + $(basename "$src")"
  fi
}

echo "[backup] Writing to $DEST"
copy_if_exists "$ROOT/data/jobmatch.db"
copy_if_exists "$ROOT/data/boss_state.json"
copy_if_exists "$ROOT/data/resume.json"
copy_if_exists "$ROOT/storage/vector_store"

if [ -d "$ROOT/data/task_screenshots" ]; then
  cp -a "$ROOT/data/task_screenshots" "$DEST/"
  echo "  + task_screenshots/"
fi

tar -czf "$DEST.tar.gz" -C "$BACKUP_ROOT" "$STAMP"
rm -rf "$DEST"
echo "[backup] Archive: $DEST.tar.gz"

# Keep last 14 daily archives
ls -1t "$BACKUP_ROOT"/*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
