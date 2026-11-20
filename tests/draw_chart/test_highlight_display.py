"""[KOS-36 M5-1] 모듈 5 강조 문구의 표시 설정 — 차트 점 값 그대로면 차트 설정, 새로 만든 계산 값이면 계산 설정 (HCX 없이 돈다)"""
from types import SimpleNamespace

import plotly.graph_objects as go

from backend.agent.draw_chart.draw_chart_module.draw_chart_highlight import highlight
from backend.schemas.chart import AxisSpec, CalcInput, CalcResult, ChartContent, Display

YEARS = ["2022", "2023", "2024"]


def _job(calcs, displays, values=(190000, 191000, 220000), unit="건"):
    content = ChartContent(chart_id="c1", chart_type="bar", measure="raw", title="t", encoding={"x": "시점", "y": "값"},
                           axis={"y": AxisSpec(display_ref="d_chart")}, columns=["시점", "값"],
                           rows=[[y, v] for y, v in zip(YEARS, values)], record_ids=["r1"])
    fig = go.Figure(go.Bar(x=YEARS, y=list(values)))
    return fig, SimpleNamespace(content=content, calcs=calcs, displays=displays, chart_type="bar")


def _texts(fig):
    return [a.text for a in fig.layout.annotations]


def _result(op, value, ref, step="a1", inputs=()):
    return CalcResult(step_id=step, op=op, value=value, display_ref=ref, record_ids=["r1"], inputs=list(inputs))


def test_growth_rate_list_uses_the_calculation_display_not_the_chart_unit():
    """증감률 목록(%)이 차트 y축 설정(건 · 0자리)으로 나오던 오류: '가장 크게 감소 2022 0건' (실제 -0.42%)"""
    displays = {"d_chart": Display(source_unit="건", display_unit="건", digits=0),
                "d_rate": Display(source_unit="%", display_unit="%", digits=2)}
    calc = _result("growth_rate", [{"key": {"시점": "2022"}, "value": -0.42}, {"key": {"시점": "2024"}, "value": 14.85}], "d_rate")
    fig, job = _job([calc], displays)
    highlight(fig, job)
    assert sorted(_texts(fig)) == ["가장 크게 감소 2022 -0.42%", "가장 크게 증가 2024 +14.85%"]


def test_separate_calculation_is_not_shown_in_the_chart_scale_even_when_source_unit_matches():
    """차트가 '명 → 만명, 0자리'여도 1,000명 증감은 '0만명' 이 아니라 계산의 설정(명)으로 (원 단위가 같다고 같은 값이 아니다)"""
    displays = {"d_chart": Display(source_unit="명", display_unit="만명", unit_scale=10000, digits=0),
                "d_chg": Display(source_unit="명", display_unit="명", digits=0)}
    ins = [CalcInput(role="a", record_id="r1", key={"시점": "2022"}, value=190000, unit="명"),
           CalcInput(role="b", record_id="r1", key={"시점": "2024"}, value=191000, unit="명")]
    fig, job = _job([_result("change", 1000, "d_chg", inputs=ins)], displays)
    highlight(fig, job)
    assert any("+1,000명" in t and "0만명" not in t for t in _texts(fig)), _texts(fig)


def test_rank_value_is_a_chart_point_so_it_shares_the_chart_display():
    """순위 · 극값의 값은 차트 점 그대로 → 막대 라벨과 같은 숫자 모양(만명 환산)"""
    displays = {"d_chart": Display(source_unit="명", display_unit="만명", unit_scale=10000, digits=1),
                "d_rank": Display(source_unit="명", display_unit="명", digits=0)}
    calc = _result("rank", [{"key": {"시점": "2024"}, "value": 220000, "rank": 1}], "d_rank")
    fig, job = _job([calc], displays)
    highlight(fig, job)
    assert _texts(fig) == ["1위 2024 22.0만명"]


def test_rank_with_a_different_source_unit_uses_its_own_display():
    displays = {"d_chart": Display(source_unit="천명", display_unit="만명", unit_scale=10, digits=1),
                "d_rank": Display(source_unit="명", display_unit="명", digits=0)}
    calc = _result("rank", [{"key": {"시점": "2024"}, "value": 220000, "rank": 1}], "d_rank")
    fig, job = _job([calc], displays)
    highlight(fig, job)
    assert _texts(fig) == ["1위 2024 220,000명"]
