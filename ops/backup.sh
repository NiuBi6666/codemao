#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/opt/codemao-backups}"

exec "$PROJECT_DIR/ops/migration-export.sh" "$BACKUP_DIR"
