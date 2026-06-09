#!/usr/bin/env bash
# Восстановление БД из бэкапа (.backup-файл от scripts/backup.sh).
# КРИТИЧНО: сервер должен быть ОСТАНОВЛЕН (иначе WAL текущего процесса перетрёт восстановленный файл).
#
# Использование:
#   ./scripts/restore.sh backups/toursearch-20260609T143000Z.db
#   ./scripts/restore.sh backups/toursearch-...db /path/to/target.db
set -euo pipefail

BACKUP="${1:-}"
TARGET="${2:-toursearch.db}"

if [[ -z "$BACKUP" ]]; then
  echo "Использование: $0 <backup.db> [target.db]" >&2
  exit 1
fi
if [[ ! -f "$BACKUP" ]]; then
  echo "[!] Бэкап не найден: $BACKUP" >&2
  exit 1
fi

# Предупреждение про живой процесс
if pgrep -f "toursearch web" >/dev/null 2>&1; then
  echo "[!] Найден запущенный процесс 'toursearch web'. Остановите его перед restore:" >&2
  echo "    pkill -f 'toursearch web'   # или docker compose stop" >&2
  exit 1
fi

# Сохраняем текущую БД (если есть) в .pre-restore — чтобы можно было откатиться.
if [[ -f "$TARGET" ]]; then
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  PRE="${TARGET}.pre-restore-${STAMP}"
  mv -- "$TARGET" "$PRE"
  # WAL/SHM текущей БД тоже сохраняем
  [[ -f "${TARGET}-wal" ]] && mv -- "${TARGET}-wal" "${PRE}-wal"
  [[ -f "${TARGET}-shm" ]] && mv -- "${TARGET}-shm" "${PRE}-shm"
  echo "[backup] текущая БД сохранена как $PRE"
fi

cp -- "$BACKUP" "$TARGET"
echo "[ok] восстановлено: $TARGET ← $BACKUP"
echo "[note] retention запустится через ~60с при старте сервера и может удалить runs"
echo "       старше TOURSEARCH_RETENTION_DAYS. Если бэкап старый — временно поставьте"
echo "       TOURSEARCH_RETENTION_DAYS=0 для разбора, перед стартом."
