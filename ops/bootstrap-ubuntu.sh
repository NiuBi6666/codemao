#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_USER="${TARGET_USER:-${SUDO_USER:-$USER}}"
DOCKER_REGISTRY_MIRROR="${DOCKER_REGISTRY_MIRROR:-}"

if ! command -v apt-get >/dev/null 2>&1; then
  echo "此脚本仅支持 Ubuntu/Debian apt 系统" >&2
  exit 1
fi

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y   ca-certificates curl git python3 docker.io docker-compose-v2
sudo systemctl enable --now docker

if [ -n "$DOCKER_REGISTRY_MIRROR" ]; then
  printf '{"registry-mirrors":["%s"]}\n' "$DOCKER_REGISTRY_MIRROR" |
    sudo tee /etc/docker/daemon.json >/dev/null
  sudo chmod 644 /etc/docker/daemon.json
  sudo systemctl restart docker
fi

if id "$TARGET_USER" >/dev/null 2>&1; then
  sudo usermod -aG docker "$TARGET_USER"
fi

echo "BOOTSTRAP=ok"
echo "TARGET_USER=$TARGET_USER"
echo "重新登录 SSH 后，docker 组权限才会在交互会话中生效。"
