#!/usr/bin/env sh
set -eu

PROJECT_DIR="${PROJECT_DIR:-/opt/codemao}"
BACKUP_DIR="${BACKUP_DIR:-/opt/codemao-backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$BACKUP_DIR"
cp "$PROJECT_DIR/data/codemao.sqlite3" "$BACKUP_DIR/codemao-$STAMP.sqlite3"
find "$BACKUP_DIR" -type f -name 'codemao-*.sqlite3' -mtime +30 -delete
echo "$BACKUP_DIR/codemao-$STAMP.sqlite3"
