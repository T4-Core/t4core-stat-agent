"""[NEW 11-24] 모듈 2 reason 문구 — 비교축이 이미 '별' 로 끝나면 '별' 을 또 붙이지 않는다 (이전: '지역별별')"""
import pytest

from backend.agent.chart_decision.chart_decision_module.chart_type_reason import make_reason


@pytest.mark.parametrize("axes, want", [
    (["지역별"], "인구수 지역별 비교"),
    (["지역"], "인구수 지역별 비교"),
    (["시도별"], "인구수 시도별 비교"),
    (["성별"], "인구수 성별 비교"),
    (["연령", "성"], "인구수 연령·성별 비교"),
    (["성", "성별"], "인구수 성별 비교"),          # 떼고 나면 같은 축 → 한 번만
])
def test_axis_suffix_is_not_repeated(axes, want):
    assert make_reason([{"지표": "인구수", "비교축": axes}], {"intent": "비교"}) == want


def test_no_axis_keeps_short_form():
    assert make_reason([{"지표": "인구수"}], {"intent": "추이"}) == "인구수 추이"
