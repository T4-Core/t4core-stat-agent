#!/usr/bin/env bash
# [NEW] KOS-57 실행 단위 배포 · 롤백 — GitHub Actions runner 에서 실행 (ci.yml deploy job)
#
#   bash deploy/scripts/deploy_all.sh <sha>
#
# ssh 별칭 db · backend · front 가 ~/.ssh/config 에 있어야 한다 (ci.yml 이 만든다).
# 1) 세 서버의 롤백 기준 SHA 수집 → 2) db → backend → front 배포
# 3) 한 역할이라도 실패하면, 이번 실행에서 이미 끝낸 역할을 역순으로 기준 SHA 에 다시 배포해 버전을 맞춘다.
#    (실패한 역할은 deploy.sh 가 스스로 되돌린다. 변경이 없던 역할은 checkout 만 되돌리고 재기동하지 않는다)
# 종료 코드: 0 성공 · 1 실패 후 롤백 완료 · 2 롤백 중 실패 또는 상태 미확인 역할 있음
set -uo pipefail

SHA="${1:-}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "::error::sha 는 40자리 커밋 해시여야 함: '${SHA}'"; exit 2; }

SCRIPT="$(cd "$(dirname "$0")" && pwd)/deploy.sh"
ROLES=(db backend front)

# 이 커밋의 deploy.sh 를 stdin 으로 보내 서버에서 실행 (서버 작업 트리에 스크립트가 없어도 동작).
# 인자는 고정 역할 이름과 검증한 16진수 SHA 뿐이라 원격 셸에서 그대로 펼쳐도 안전하다.
remote() {
  local host="$1"; shift
  # shellcheck disable=SC2029
  ssh "$host" "f=\$(mktemp) && cat > \"\$f\" && bash \"\$f\" $* </dev/null; rc=\$?; rm -f \"\$f\"; exit \$rc" <"$SCRIPT"
}

describe() {
  case "$1" in
    1)   echo "실패 (변경 없이 중단했거나 자체 롤백 완료)" ;;
    2)   echo "자체 롤백도 실패 — 서버에서 직접 확인" ;;
    255) echo "SSH 실패 — 상태 미확인" ;;
    *)   echo "종료 코드 $1 — 상태 미확인" ;;
  esac
}

declare -A BASE
echo "::group::롤백 기준 SHA 수집"
for role in "${ROLES[@]}"; do
  if ! out="$(remote "$role" current "$role")" || [[ ! "$out" =~ ^[0-9a-f]{40}$ ]]; then
    echo "::endgroup::"
    echo "::error::$role 의 현재 배포 SHA 를 읽지 못함 → 아무것도 배포하지 않고 종료"
    exit 1
  fi
  BASE[$role]="$out"
  echo "$role: ${out:0:9}"
done
echo "::endgroup::"

done_roles=()
failed=""
failed_rc=0
for role in "${ROLES[@]}"; do
  echo "::group::배포 $role → ${SHA:0:9}"
  remote "$role" "$role" "$SHA" 0
  rc=$?
  echo "::endgroup::"
  if (( rc == 0 )); then
    done_roles+=("$role")
  else
    failed="$role"
    failed_rc=$rc
    break
  fi
done

if [[ -z "$failed" ]]; then
  echo "배포 완료: ${ROLES[*]} → ${SHA:0:9}"
  exit 0
fi

echo "::error::$failed 배포 $(describe "$failed_rc") → 이번 실행에서 끝낸 역할을 실행 전 SHA 로 되돌림"
final=1
(( failed_rc == 1 )) || final=2
summary=("$failed: $(describe "$failed_rc")")

for (( i=${#done_roles[@]}-1; i>=0; i-- )); do
  role="${done_roles[$i]}"
  echo "::group::롤백 $role → ${BASE[$role]:0:9}"
  remote "$role" "$role" "${BASE[$role]}" 0
  rc=$?
  echo "::endgroup::"
  if (( rc == 0 )); then
    summary+=("$role: ${BASE[$role]:0:9} 로 롤백 완료")
  else
    summary+=("$role: 롤백 $(describe "$rc")")
    final=2
  fi
done

echo "── 결과 (${SHA:0:9} 배포 실패) ──"
printf '%s\n' "${summary[@]}"
(( final == 2 )) && echo "::error::롤백이 끝나지 않은 역할이 있음 — 위 결과를 보고 서버에서 확인"
exit "$final"
