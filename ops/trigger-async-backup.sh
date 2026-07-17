#!/usr/bin/env bash
set -Eeuo pipefail

REASON="${1:-manual}"
SERVICE="${BACKUP_SERVICE:-codemao-migration-backup.service}"

if ! systemctl cat "$SERVICE" >/dev/null 2>&1; then
  echo "异步备份服务尚未安装: $SERVICE" >&2
  exit 1
fi

sudo -n systemctl start --no-block "$SERVICE"
logger -t codemao-backup "queued async migration backup: reason=$REASON commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "BACKUP_QUEUED=ok"
echo "REASON=$REASON"
