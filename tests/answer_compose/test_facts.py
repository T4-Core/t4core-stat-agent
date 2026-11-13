"""[NEW] facts.py — 조사, 값 꺼내기"""
import pytest

from backend.agent.answer_compose.facts import Facts, josa, key_label, points
from tests.answer_compose._data import growth, request


@pytest.mark.parametrize("word,kind,want", [
    ("혼인건수", "은", "혼인건수는"), ("출생아수", "은", "출생아수는"), ("인구", "은", "인구는"), ("인구수", "이", "인구수가"),
    ("서울", "을", "서울을"), ("부산", "으로", "부산으로"), ("서울특별시 2021", "으로", "서울특별시 2021로"),
    ("240,326건", "으로", "240,326건으로"), ("24.8%", "은", "24.8%는"), ("대전", "과", "대전과"), ("2025", "은", "2025는")])
def test_josa(word, kind, want):
    assert josa(word, kind) == want


def test_points_shapes():
    assert points(growth()) == [{"key": {}, "value": 24.84013568337775}]
    assert points(growth(value=None)) == []
    lst = growth().model_copy(update={"value": [{"key": {"시점": "2022"}, "value": 1.0}, {"key": {"시점": "2023"}, "value": 2.0}]})
    assert [key_label(p["key"]) for p in points(lst)] == ["2022", "2023"]


def test_formatting_uses_module3_displays():
    f = Facts(request())
    r = f.results["a1"]
    assert f.fmt_result(r, r.value) == "24.8%" and f.fmt_result(r, -2.38, absolute=True) == "2.4%"
    assert [f.fmt_input(i) for i in r.inputs] == ["192,507건", "240,326건"]
    assert f.label(r) == "혼인건수 증감률"
