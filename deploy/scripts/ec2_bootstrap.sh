#!/usr/bin/env bash
# EC2 한 대를 처음 준비 — Docker · Compose · 저장 폴더 · (메모리 4 GiB 서버) 스왑
#
#   sudo bash deploy/scripts/ec2_bootstrap.sh backend   # backend-server
#   sudo bash deploy/scripts/ec2_bootstrap.sh db        # db-server
#   sudo bash deploy/scripts/ec2_bootstrap.sh front     # front-server
#
# Ubuntu · Debian · Amazon Linux 2023 에서 동작. 여러 번 실행해도 안전하다.
set -euo pipefail

ROLE="${1:?역할을 주세요: backend | db | front}"
APP_UID=1000                       # backend 컨테이너의 app 사용자 (Dockerfile useradd --uid 1000)
LOGIN_USER="${SUDO_USER:-$(logname 2>/dev/null || echo ubuntu)}"
. /etc/os-release

if ! command -v docker >/dev/null 2>&1; then
  echo "[bootstrap] Docker 설치 ($ID)"
  case "$ID" in
    ubuntu|debian)
      apt-get update -y
      apt-get install -y ca-certificates curl git
      install -m 0755 -d /etc/apt/keyrings
      curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
      chmod a+r /etc/apt/keyrings/docker.asc
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
      apt-get update -y
      apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
      ;;
    amzn)
      dnf install -y docker git
      ARCH="$(uname -m)"
      mkdir -p /usr/local/lib/docker/cli-plugins
      curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose
      BX="$(curl -fsSL https://api.github.com/repos/docker/buildx/releases/latest | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)"
      BARCH="$([ "$ARCH" = "x86_64" ] && echo amd64 || echo arm64)"
      curl -fsSL "https://github.com/docker/buildx/releases/download/${BX}/buildx-${BX}.linux-${BARCH}" \
        -o /usr/local/lib/docker/cli-plugins/docker-buildx
      chmod +x /usr/local/lib/docker/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/docker-buildx
      ;;
    *) echo "지원하지 않는 OS: $ID — Docker 를 직접 설치하세요"; exit 1 ;;
  esac
fi
systemctl enable --now docker            # EC2 를 다시 켜면 Docker 와 restart: unless-stopped 컨테이너가 자동으로 뜸
usermod -aG docker "$LOGIN_USER" || true

# 메모리 4 GiB 서버는 이미지 빌드(npm) 중 메모리가 모자랄 수 있어 스왑 2 GiB
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$MEM_MB" -lt 8000 ] && ! swapon --show | grep -q /swapfile; then
  echo "[bootstrap] 스왑 2 GiB"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

mkdir -p /srv/t4core
case "$ROLE" in
  backend)
    mkdir -p /srv/t4core/storage /srv/t4core/kosis_data /srv/t4core/pgdata /srv/t4core/redis
    chown -R "$APP_UID:$APP_UID" /srv/t4core/storage
    chown "$LOGIN_USER" /srv/t4core /srv/t4core/kosis_data   # 묶음(tar)을 scp 로 올려 풀 곳
    ;;
  db)
    mkdir -p /srv/t4core/vectordata
    ;;
  front) ;;
  *) echo "역할은 backend | db | front"; exit 1 ;;
esac

docker --version && docker compose version
df -h / | tail -1
echo "[bootstrap] 완료 ($ROLE). docker 그룹 적용을 위해 SSH 를 한 번 끊었다가 다시 접속하세요."
