import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent           # 저장소 루트
# [CHANGED] 이전: ROOT = Path(__file__).resolve().parent.parent  (Rewritten_fastapi) — 'rewriter' 패키지를 찾기 위함
sys.path.insert(0, str(ROOT))


# [NEW 11-17] 모듈 3 의 run_steps 는 한 단계의 예기치 못한 예외를 사유("내부 오류로 계산하지 못함")로 바꿔 요청 전체가 멈추지 않게 한다.
# 그러면 버그가 사유 문구 뒤로 숨으므로, 테스트에서는 그 로그가 남으면 실패시킨다 (일부러 일으키는 테스트는 @pytest.mark.internal_error_ok)
import pytest  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "internal_error_ok: run_steps 의 내부 오류 처리를 일부러 확인하는 테스트")


@pytest.fixture(autouse=True)
def _no_hidden_internal_errors(request, caplog):
    yield
    if request.node.get_closest_marker("internal_error_ok"):
        return
    hidden = [r.getMessage() for r in caplog.records if "내부 오류로 계산하지 못함" in r.getMessage()]
    assert not hidden, f"계산 중 예기치 못한 예외가 사유 뒤에 숨었다: {hidden}"
