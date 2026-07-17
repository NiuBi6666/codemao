#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/opt/codemao-backups}"
TARGET_USER="${TARGET_USER:-${SUDO_USER:-$USER}}"

id "$TARGET_USER" >/dev/null 2>&1 || {
  echo "用户不存在: $TARGET_USER" >&2
  exit 1
}
getent group docker >/dev/null 2>&1 || {
  echo "docker 用户组不存在" >&2
  exit 1
}

sudo install -d -m 700 -o "$TARGET_USER" -g docker "$BACKUP_DIR"

sudo tee /etc/systemd/system/codemao-migration-backup.service >/dev/null <<EOF
[Unit]
Description=Create codemao migration backup
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
User=$TARGET_USER
Group=docker
UMask=0077
Environment=PROJECT_DIR=$PROJECT_DIR
Environment=BACKUP_DIR=$BACKUP_DIR
Environment=RETENTION_DAYS=30
ExecStart=$PROJECT_DIR/ops/migration-export.sh $BACKUP_DIR
EOF

sudo tee /etc/systemd/system/codemao-migration-backup.timer >/dev/null <<'EOF'
[Unit]
Description=Daily codemao migration backup

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true
RandomizedDelaySec=10m
Unit=codemao-migration-backup.service

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now codemao-migration-backup.timer
sudo systemctl start codemao-migration-backup.service
git -C "$PROJECT_DIR" config core.hooksPath .githooks

sudo systemctl --no-pager status codemao-migration-backup.timer
echo "GIT_HOOKS=enabled"
echo "每次 commit 或 pull/merge 后会异步排队迁移备份。"
