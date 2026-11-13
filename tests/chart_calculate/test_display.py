"""[NEW] display.py — 단위·digits 기본값·표시 문자열 (명세 4장 "표시 설정")"""
import pytest

from backend.agent.chart_calculate.display import (default_digits, format_value, make_display, register, result_unit, strip_unit,
                                         unit_of)
from backend.schemas.chart import Display


@pytest.mark.parametrize("item, fallback, want", [
    ("혼인건수(건)", None, "건"), ("조혼인율(천명당)", None, "천명당"), ("총인구수", "명", "명"),
    ("총인구수", "명 건", None),            # metadata.unit 에 단위가 여러 개면 믿지 않는다
    ("인구(추계)수(명)", None, "명"), (None, None, None)])
def test_unit_of(item, fallback, want):
    assert unit_of(item, fallback) == want


def test_strip_unit():
    assert strip_unit("혼인건수(건)") == "혼인건수" and strip_unit("총인구수") == "총인구수"


@pytest.mark.parametrize("op, want", [("growth_rate", "%"), ("share", "%"), ("index", "index"), ("change", "건"),
                                      ("raw", "건"), ("diff", "건")])
def test_result_unit(op, want):
    assert result_unit(op, "건") == want


@pytest.mark.parametrize("unit, scale, want", [
    ("건", 1, 0), ("명", 1, 0), ("%", 1, 1), ("천명당", 1, 1), ("index", 1, 1), ("천원", 1, 0),
    ("건", 10000, 1), ("㎢", 1, 1), (None, 1, 1)])
def test_default_digits(unit, scale, want):
    assert default_digits(unit, scale) == want


@pytest.mark.parametrize("value, display, want", [
    (192507, {"source_unit": "건", "display_unit": "만 건", "unit_scale": 10000, "digits": 1}, "19.3만 건"),  # 명세 예
    (192507.0, {"source_unit": "건", "display_unit": "건"}, "192,507건"),
    (24.84013568337775, {"source_unit": "%", "display_unit": "%"}, "24.8%"),
    (-2.3875315663834327, {"source_unit": "%", "display_unit": "%"}, "-2.4%"),
    (4.7, {"source_unit": "천명당", "display_unit": "천명당"}, "4.7"),
    (115.45, {"source_unit": "index", "display_unit": "index"}, "115.5"),      # 사사오입 (round() 면 115.4)
    (3250, {"source_unit": "천원", "display_unit": "천원"}, "3,250천원"),
    (2.5, {"source_unit": "명", "display_unit": "명"}, "3명"),                  # round(2.5) == 2 를 피한다
])
def test_format_value(value, display, want):
    assert format_value(value, Display(**display)) == want


def test_format_value_none():
    assert format_value(None, make_display("건")) is None


def test_register_reuses_same_setting():
    displays = {}
    d1 = register(displays, make_display("건"))
    d2 = register(displays, make_display("명"))
    assert (d1, d2) == ("d1", "d2")
    assert register(displays, make_display("건")) == "d1" and len(displays) == 2
    assert register(displays, make_display("건", "만 건", 10000, 1)) == "d3"   # 같은 단위라도 환산이 다르면 다른 설정


def test_unknown_unit_integer_has_no_decimals():
    """단위를 모르면 기본 1자리지만, 값이 정수면 소수 자리를 붙이지 않는다 (44,565.0 → 44,565)"""
    assert format_value(44565.0, make_display(None)) == "44,565"
    assert format_value(0.581, make_display(None)) == "0.6"
