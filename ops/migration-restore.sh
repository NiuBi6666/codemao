#!/usr/bin/env bash
set -Eeuo pipefail

VERIFY_ONLY=false
if [ "${1:-}" = "--verify-only" ]; then
  VERIFY_ONLY=true
  shift
fi

ARCHIVE="${1:-}"
PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"

if [ -z "$ARCHIVE" ]; then
  echo "用法: $0 [--verify-only] /path/codemao-migration-*.tar.gz" >&2
  exit 1
fi

ARCHIVE="$(cd "$(dirname "$ARCHIVE")" && pwd)/$(basename "$ARCHIVE")"
[ -f "$ARCHIVE" ] || { echo "迁移归档不存在: $ARCHIVE" >&2; exit 1; }

for command in tar sha256sum python3 git; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "缺少命令: $command" >&2
    exit 1
  }
done

umask 077
WORK_DIR="$(mktemp -d)"
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT

if [ -f "$ARCHIVE.sha256" ]; then
  (
    cd "$(dirname "$ARCHIVE")"
    sha256sum -c "$(basename "$ARCHIVE").sha256"
  )
else
  echo "警告: 未找到归档外部校验文件 $ARCHIVE.sha256" >&2
fi

if tar -tzf "$ARCHIVE" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  echo "归档包含不安全路径，拒绝恢复" >&2
  exit 1
fi

tar -xzf "$ARCHIVE" -C "$WORK_DIR"
for required in MANIFEST SHA256SUMS .env data/codemao.sqlite3 codemao.git.bundle; do
  [ -e "$WORK_DIR/$required" ] || {
    echo "归档缺少: $required" >&2
    exit 1
  }
done

(
  cd "$WORK_DIR"
  sha256sum -c SHA256SUMS
)

ACTUAL_STUDENTS="$(python3 - "$WORK_DIR/data/codemao.sqlite3" <<'PY'
import sqlite3
import sys
connection = sqlite3.connect(sys.argv[1])
integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
if integrity != "ok":
    raise SystemExit("database integrity check failed: " + integrity)
print(connection.execute("SELECT COUNT(*) FROM students").fetchone()[0])
PY
)"
EXPECTED_STUDENTS="$(sed -n 's/^STUDENT_COUNT=//p' "$WORK_DIR/MANIFEST")"
[ "$ACTUAL_STUDENTS" = "$EXPECTED_STUDENTS" ] || {
  echo "学生数量校验失败: expected=$EXPECTED_STUDENTS actual=$ACTUAL_STUDENTS" >&2
  exit 1
}

git bundle verify "$WORK_DIR/codemao.git.bundle" >/dev/null
echo "VERIFY=ok"
echo "STUDENTS=$ACTUAL_STUDENTS"
echo "SOURCE_COMMIT=$(sed -n 's/^GIT_COMMIT=//p' "$WORK_DIR/MANIFEST")"

if [ "$VERIFY_ONLY" = true ]; then
  exit 0
fi

command -v docker >/dev/null 2>&1 || {
  echo "缺少 docker；请先运行 bootstrap-ubuntu.sh" >&2
  exit 1
}

cd "$PROJECT_DIR"
[ -f compose.yaml ] || { echo "PROJECT_DIR 不是 codemao 项目: $PROJECT_DIR" >&2; exit 1; }

echo "先构建应用镜像，构建失败不会中断当前服务。"
docker compose build app

ROLLBACK_DIR="$PROJECT_DIR/data/pre-restore-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ROLLBACK_DIR"
[ -f .env ] && install -m 600 .env "$ROLLBACK_DIR/.env"
[ -f data/codemao.sqlite3 ] && install -m 600 data/codemao.sqlite3 "$ROLLBACK_DIR/codemao.sqlite3"

docker compose down

install -m 600 "$WORK_DIR/.env" .env
install -m 600 "$WORK_DIR/data/codemao.sqlite3" data/codemao.sqlite3
mkdir -p imports
find imports -maxdepth 1 -type f ! -name '.gitkeep' -delete
for file in "$WORK_DIR"/imports/*; do
  [ -f "$file" ] || continue
  install -m 600 "$file" "imports/$(basename "$file")"
done

docker compose up -d --no-build
APP_CONTAINER="$(docker compose ps -q app)"
status="starting"
for _ in $(seq 1 30); do
  status="$(docker inspect -f '{{.State.Health.Status}}' "$APP_CONTAINER")"
  [ "$status" = "healthy" ] && break
  sleep 2
done

if [ "$status" != "healthy" ]; then
  echo "恢复后的应用未通过健康检查。旧文件保存在 $ROLLBACK_DIR" >&2
  docker compose logs --tail=100 app >&2
  exit 1
fi

echo "RESTORE=ok"
echo "ROLLBACK_DIR=$ROLLBACK_DIR"
echo "URL=http://$(hostname -I | awk '{print $1}')"
