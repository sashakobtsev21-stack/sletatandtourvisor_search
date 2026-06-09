#!/usr/bin/env bash
# Online-backup SQLite (через .backup) — безопасно во время работы сервера: WAL-режим
# позволяет читать без блокировки writer'а. Артефакт — .db файл (без -wal/-shm).
#
# Использование:
#   ./scripts/backup.sh                                # → backups/toursearch-<date>.db
#   ./scripts/backup.sh /path/to/source.db /backups    # явные source + destination dir
set -euo pipefail

SRC="${1:-toursearch.db}"
DEST_DIR="${2:-backups}"

if [[ ! -f "$SRC" ]]; then
  echo "[!] Источник БД не найден: $SRC" >&2
  exit 1
fi
mkdir -p "$DEST_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$DEST_DIR/toursearch-${STAMP}.db"

# .backup корректно сделает онлайн-копию (не голый cp — он не консистентен с WAL).
sqlite3 "$SRC" ".backup '$DEST'"
SIZE_MB=$(du -m "$DEST" | cut -f1)
echo "[ok] $DEST (${SIZE_MB} MB)"

# Ротация: оставить последние 14 бэкапов.
KEEP=14
COUNT=$(ls -1 "$DEST_DIR"/toursearch-*.db 2>/dev/null | wc -l)
if (( COUNT > KEEP )); then
  ls -1t "$DEST_DIR"/toursearch-*.db | tail -n +$((KEEP + 1)) | while read -r OLD; do
    rm -f -- "$OLD"
    echo "[rotate] удалён $OLD"
  done
fi
