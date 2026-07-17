#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
OUTPUT_DIR="${1:-${BACKUP_DIR:-/opt/codemao-backups}}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE_NAME="codemao-migration-${STAMP}.tar.gz"
SNAPSHOT_NAME=".migration-${STAMP}.sqlite3"
WORK_DIR="$(mktemp -d)"

umask 077

cleanup() {
  rm -rf "$WORK_DIR"
  rm -f "$PROJECT_DIR/data/$SNAPSHOT_NAME"
}
trap cleanup EXIT

for command in docker git tar sha256sum python3; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "缺少命令: $command" >&2
    exit 1
  }
done

cd "$PROJECT_DIR"
[ -f .env ] || { echo "缺少 $PROJECT_DIR/.env" >&2; exit 1; }
[ -f data/codemao.sqlite3 ] || { echo "缺少学生数据库" >&2; exit 1; }
docker compose ps --status running app | grep -q codemao-app || {
  echo "应用容器未运行，无法创建一致性快照" >&2
  exit 1
}

mkdir -p "$OUTPUT_DIR" "$WORK_DIR/data" "$WORK_DIR/imports"

docker compose exec -T -e SNAPSHOT_PATH="/data/$SNAPSHOT_NAME" app python -c '
import os
import sqlite3
source = sqlite3.connect("/data/codemao.sqlite3")
target = sqlite3.connect(os.environ["SNAPSHOT_PATH"])
with target:
    source.backup(target)
result = target.execute("PRAGMA integrity_check").fetchone()[0]
source.close()
target.close()
if result != "ok":
    raise SystemExit("database integrity check failed: " + result)
'

install -m 600 "data/$SNAPSHOT_NAME" "$WORK_DIR/data/codemao.sqlite3"
install -m 600 .env "$WORK_DIR/.env"

for file in imports/*; do
  [ -f "$file" ] || continue
  [ "$(basename "$file")" = ".gitkeep" ] && continue
  install -m 600 "$file" "$WORK_DIR/imports/$(basename "$file")"
done

git bundle create "$WORK_DIR/codemao.git.bundle" --all
install -m 755 ops/bootstrap-ubuntu.sh "$WORK_DIR/bootstrap-ubuntu.sh"
install -m 755 ops/migration-restore.sh "$WORK_DIR/migration-restore.sh"

STUDENT_COUNT="$(python3 - "$WORK_DIR/data/codemao.sqlite3" <<'PY'
import sqlite3
import sys
connection = sqlite3.connect(sys.argv[1])
print(connection.execute("SELECT COUNT(*) FROM students").fetchone()[0])
PY
)"

cat > "$WORK_DIR/MANIFEST" <<EOF
FORMAT_VERSION=1
CREATED_AT=$STAMP
GIT_COMMIT=$(git rev-parse HEAD)
GIT_BRANCH=$(git branch --show-current || true)
SOURCE_HOST=$(hostname)
SOURCE_ARCH=$(uname -m)
STUDENT_COUNT=$STUDENT_COUNT
APP_IMAGE=$(docker compose images -q app | head -n 1)
EOF

(
  cd "$WORK_DIR"
  find . -type f ! -name SHA256SUMS -print0 |
    sort -z |
    while IFS= read -r -d '' file; do
      sha256sum "$file"
    done > SHA256SUMS
)

tar -C "$WORK_DIR" -czf "$OUTPUT_DIR/$ARCHIVE_NAME" .
chmod 600 "$OUTPUT_DIR/$ARCHIVE_NAME"
(
  cd "$OUTPUT_DIR"
  sha256sum "$ARCHIVE_NAME" > "$ARCHIVE_NAME.sha256"
)
chmod 600 "$OUTPUT_DIR/$ARCHIVE_NAME.sha256"

find "$OUTPUT_DIR" -maxdepth 1 -type f -name 'codemao-migration-*.tar.gz' -mtime "+$RETENTION_DAYS" -delete
find "$OUTPUT_DIR" -maxdepth 1 -type f -name 'codemao-migration-*.tar.gz.sha256' -mtime "+$RETENTION_DAYS" -delete

echo "ARCHIVE=$OUTPUT_DIR/$ARCHIVE_NAME"
echo "CHECKSUM=$OUTPUT_DIR/$ARCHIVE_NAME.sha256"
echo "STUDENTS=$STUDENT_COUNT"
