// 실행 중 로그아웃이나 새로고침으로 결과를 잃지 않도록 현재 상태를 기억합니다.
let busy = false;

function warn(event: BeforeUnloadEvent) {
  event.preventDefault();
}

export function setRunBusy(next: boolean) {
  if (busy === next) return;
  busy = next;
  if (next) window.addEventListener('beforeunload', warn);
  else window.removeEventListener('beforeunload', warn);
}

export function isRunBusy() {
  return busy;
}
