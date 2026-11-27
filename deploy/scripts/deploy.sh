#!/usr/bin/env bash
# [NEW] KOS-57 역할별 배포 — CD(GitHub Actions)와 사람이 같은 경로를 쓴다.
#
#   bash deploy/scripts/deploy.sh <db|backend|front> [sha] [force]
#
#   sha   배포할 커밋 (생략하면 origin/develop). origin/develop 이력에 있는 커밋만 허용
#   force 1 이면 변경 파일과 무관하게 다시 기동
#
# 동작: SHA 고정 checkout → 마지막 배포 SHA 이후 이 역할의 경로가 바뀌었을 때만 기동 → 헬스 확인
#       → 실패하면 이전 SHA 로 되돌려 다시 기동하고 비정상 종료.
# 출력은 public 저장소의 Actions 로그에 그대로 남는다: compose config · .env · /health 본문은 출력하지 않는다.
set -euo pipefail

ROLE="${1:-}"
SHA_IN="${2:-}"
FORCE="${3:-0}"

# [CHANGED] 이전: REPO="${T4_REPO_DIR:-$HOME/t4core}" — 서버는 git clone 기본 폴더 이름으로 받아 둔 상태
REPO="${T4_REPO_DIR:-$HOME/t4core-stat-agent}"
BRANCH="${T4_DEPLOY_BRANCH:-develop}"
HEALTH_TIMEOUT="${T4_HEALTH_TIMEOUT:-180}"

log() { printf '[deploy:%s] %s\n' "${ROLE:-?}" "$*"; }
die() { log "오류: $*" >&2; exit 1; }

case "$ROLE" in
  db)      PATHS=(deploy/db) ;;
  backend) PATHS=(backend configs "requirements*.txt" Dockerfile .dockerignore deploy/backend) ;;
  front)   PATHS=(frontend/web deploy/frontend) ;;
  *)       die "역할은 db | backend | front 중 하나 (받은 값: '${ROLE}')" ;;
esac
[[ "$SHA_IN" =~ ^([0-9a-f]{7,40})?$ ]] || die "sha 형식이 아님: ${SHA_IN}"
[[ "$FORCE" =~ ^[01]$ ]] || die "force 는 0 또는 1"

cd "$REPO" || die "작업 트리 없음: $REPO"
git rev-parse --git-dir >/dev/null 2>&1 || die "git 저장소가 아님: $REPO"

GIT_DIR_ABS="$(git rev-parse --absolute-git-dir)"
STATE_FILE="$GIT_DIR_ABS/t4core-deployed-$ROLE"   # .git 안: 작업 트리 상태(porcelain)에 잡히지 않음
ENV_FILE="deploy/$ROLE/.env"
[[ "$ROLE" == front ]] && ENV_FILE="deploy/frontend/.env"
COMPOSE_FILE="${ENV_FILE%/.env}/compose.yml"
dc() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

# 사람이 같은 서버에서 동시에 돌리거나 CD 가 겹쳐도 한 번에 하나만
exec 9>"$GIT_DIR_ABS/t4core-deploy.lock"
flock -w 600 9 || die "다른 배포가 10분 넘게 진행 중"

# 사전 조건: 추적 파일 수정이 있으면 checkout 이 그 수정을 지우거나 실패한다 → 건드리지 않고 중단
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  git status --short --untracked-files=no >&2
  die "작업 트리에 커밋하지 않은 수정이 있음 (위 목록). 정리한 뒤 다시 실행"
fi
[[ -f "$ENV_FILE" ]] || die "$ENV_FILE 없음 (deploy/README.md 참고)"

git fetch --quiet origin "$BRANCH"
if [[ -z "$SHA_IN" ]]; then
  SHA="$(git rev-parse "origin/$BRANCH")"
else
  SHA="$(git rev-parse --verify --quiet "${SHA_IN}^{commit}")" || die "커밋을 찾지 못함: $SHA_IN"
fi
git merge-base --is-ancestor "$SHA" "origin/$BRANCH" || die "$SHA 는 origin/$BRANCH 이력에 없음"

PREV=""
[[ -s "$STATE_FILE" ]] && PREV="$(<"$STATE_FILE")"
if [[ -n "$PREV" ]] && ! git cat-file -e "${PREV}^{commit}" 2>/dev/null; then
  log "기록된 이전 배포 $PREV 를 찾지 못함 → 처음 배포처럼 진행"
  PREV=""
fi
ORIG_HEAD="$(git rev-parse HEAD)"
ROLLBACK_TO="${PREV:-$ORIG_HEAD}"

if [[ "$FORCE" == 0 && -n "$PREV" ]]; then
  if [[ "$PREV" == "$SHA" ]] || git diff --quiet "$PREV" "$SHA" -- "${PATHS[@]}"; then
    git checkout --quiet --detach "$SHA"
    printf '%s\n' "$SHA" >"$STATE_FILE"
    log "skip: ${PREV:0:9}..${SHA:0:9} 사이에 이 역할의 변경 없음"
    exit 0
  fi
fi

start() {
  case "$ROLE" in
    db)      dc up -d ;;
    backend) dc build backend && dc up -d backend ;;
    front)   dc up -d --build ;;
  esac
}

healthy_once() {
  case "$ROLE" in
    db)
      local cid
      cid="$(dc ps -q vector)"
      [[ -n "$cid" && "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$cid")" == healthy ]] ;;
    backend) curl -fsS --max-time 5 -o /dev/null http://localhost:8000/health ;;
    front)   curl -fsS --max-time 5 -o /dev/null http://localhost/health ;;
  esac
}

wait_healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT))
  until healthy_once 2>/dev/null; do
    (( SECONDS < deadline )) || return 1
    sleep 5
  done
}

deploy_at() {
  git checkout --quiet --detach "$1"
  start && wait_healthy
}

log "배포: ${PREV:-(기록 없음)} → $SHA"
if deploy_at "$SHA"; then
  printf '%s\n' "$SHA" >"$STATE_FILE"
  docker image prune -f >/dev/null || true
  log "완료: $SHA"
  exit 0
fi

# 컨테이너 로그는 사용자 질문·내부 주소를 담을 수 있어 public Actions 로그로 내보내지 않는다
log "헬스 확인 실패 (${HEALTH_TIMEOUT}초) → $ROLLBACK_TO 로 되돌림. 원인은 서버에서 'docker compose ... logs' 로 확인" >&2
if deploy_at "$ROLLBACK_TO"; then
  log "롤백 완료: $ROLLBACK_TO (배포 기록은 바꾸지 않음)" >&2
  exit 1
fi
log "롤백도 실패: 서버에서 직접 확인 필요 (dc ps · dc logs)" >&2
exit 2
