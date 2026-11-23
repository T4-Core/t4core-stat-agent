"""허용오차 3층 · 평가 정규형 · 기대 표시값 (criteria.md 4장)"""
import pytest

from backend.agent.chart_calculate.display import format_value
from backend.schemas.chart import Display
from eval.generator.checks.normalize import close, comparable, convertible, normalize
from eval.generator.display_ref import display_tolerance, expected_display

# 경계값: (값, source_unit, display_unit, unit_scale, digits, 기대)
EDGES = [
    (0.25, "%", "%", 1, 1, "0.3%"),        # Python round(0.25, 1) == 0.2 (은행가 반올림) 와 다르다
    (-0.25, "%", "%", 1, 1, "-0.3%"),
    (-0.04, "%", "%", 1, 1, "0.0%"),       # 음수 0 정규화
    (2.5, "건", "건", 1, 0, "3건"),
    (155996, "명", "만 명", 10000, 1, "15.6만 명"),
    (9340, "천명", "만 명", 10, None, "934만 명"),    # 천명 → 만 명: 100 이상이면 소수 없음
    (379, "천명", "만 명", 10, None, "37.9만 명"),
    (0, "천명", "만 명", 10, None, "0만 명"),
]


def test_python_round_differs():
    assert round(0.25, 1) == 0.2


@pytest.mark.parametrize("v,su,du,scale,dg,want", EDGES)
def test_display_ref(v, su, du, scale, dg, want):
    assert expected_display(v, su, du, scale, dg) == want


@pytest.mark.parametrize("v,su,du,scale,dg,want", EDGES)
def test_team_format_value_matches_spec(v, su, du, scale, dg, want):
    """같은 경계값을 팀 구현에도 건다. 다르면 명세 불일치 (평가기 · 모듈 3 중 어느 쪽이 틀렸는지 확인)"""
    assert format_value(v, Display(source_unit=su, display_unit=du, unit_scale=scale, digits=dg)) == want


def test_normalize_share_percent_to_ratio():
    n = normalize(17.45783976804005, "%")
    assert n.unit == "ratio" and close(n.value, 0.17458, atol=1e-5)
    assert not comparable(normalize(2.6, "%p"), "ratio")          # %p 와 ratio 는 비교하지 않는다
    assert normalize(9340, "천명").value == 9_340_000


def test_display_tolerance_in_raw_units():
    d = {"source_unit": "명", "display_unit": "만 명", "unit_scale": 10000, "digits": 1}
    tol = display_tolerance(d)
    assert tol == pytest.approx(500)
    assert close(156000, 155996, atol=tol)                         # '15.6만 명' 은 155,996 을 허용
    assert not close(156000, 156600, atol=tol)                     # 156,600 은 거부


def test_convertible():
    assert convertible("천명", "명")
    assert not convertible("%", "%p")
    assert not convertible("명", "건")
