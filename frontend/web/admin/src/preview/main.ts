// 관리자 페이지 안의 작은 창(iframe) 시작점입니다.
// 이전 테스트 기록이 남지 않도록 비운 뒤 실제 사용자 화면을 불러옵니다.
try {
  localStorage.removeItem('kosis.history.live.v1');
  indexedDB.deleteDatabase('kosis-agent');
} catch {
  // 저장소를 쓸 수 없어도 화면은 동작합니다.
}

void import('./PreviewApp');
