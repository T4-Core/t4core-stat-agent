"""[NEW] run_module3_trace · POST /api/v1/chart/calc/trace — 테스트 화면이 보는 단계별 중간 결과"""
import pytest

from backend.agent.chart_calculate.pipeline import run_module3, run_module3_trace
from backend.agent.chart_calculate.planner import Decision
from backend.schemas.chart import ChartRequest, Module3Request
from tests.chart_calculate._views import view
from tests.chart_calculate.test_content import REGION_COLS
from tests.chart_calculate.test_decide import BUNDLE, CHARTS, REPLY, fake


def request(charts=CHARTS, records=None):
    return Module3Request(records=records or [view()], query_bundle=BUNDLE, charts=charts)


def test_trace_output_equals_run_module3():
    t = run_module3_trace(request(), chat=fake(REPLY))
    assert t.output == run_module3(request(), chat=fake(REPLY))
    assert t.chart_plan == t.output.chart_plan and t.displays == t.output.displays


def test_trace_keeps_prompt_raw_reply_and_display_text():
    t = run_module3_trace(request(), chat=fake(REPLY))
    assert not t.decide.skipped and [m["role"] for m in t.decide.messages] == ["system", "user"]
    assert t.decide.raw == REPLY and t.decide.decision.charts[0].chart_id == "c1"
    c1 = t.charts["c1"]
    assert c1.requirements == ["time_axis_required", "min_points_3"]
    assert [(a.content.chart_type, a.check.passed) for a in c1.attempts] == [("line", True)]
    assert [c.display_text for c in t.calcs] == [["-0.4%", "1.0%", "14.8%", "8.1%"], ["-4.4%", "-7.7%", "3.6%", "6.7%"]]


def test_trace_records_failed_original_and_fallback():
    rows = [["2025", f"지역{i:02d}", "인구수(명)", 10.0 + i] for i in range(17)]
    rec = view(rows, REGION_COLS)
    charts = [ChartRequest(chart_id="c4", chart_type="pie", fallback_chart="bar")]
    decision = Decision.model_validate({"charts": [{"chart_id": "c4", "record_id": rec.id, "select": {}}]})
    t = run_module3_trace(request(charts, [rec]), decision=decision)
    assert t.decide.skipped and t.decide.messages == []
    tried = t.charts["c4"].attempts
    assert [(a.content.chart_type, a.check.passed) for a in tried] == [("pie", False), ("bar", True)]
    assert tried[0].check.failed == ["max_categories_5"] and len(tried[0].content.rows) == 17
    assert t.output.validation["c4"].final_chart_type == "bar"


def test_trace_list_values_are_formatted_one_by_one():
    rec = view([["2025", n, "인구수(명)", v] for n, v in [("가", 1234.0), ("나", 50.0)]], REGION_COLS)
    decision = Decision.model_validate({"answers": [{"op": "rank", "operands": [
        {"record_id": rec.id, "item": "인구수(명)", "select": {}}]}]})
    t = run_module3_trace(request([], [rec]), decision=decision)
    assert t.calcs[0].display_text == ["1,234명", "50명"]


pytest.importorskip("fastapi")

from fastapi.testclient import TestClient   # noqa: E402

from backend.api.v1_chart import EX_CALC    # noqa: E402
from backend.main import app                 # noqa: E402


def test_api_trace_example():
    r = TestClient(app).post("/api/v1/chart/calc/trace", json=EX_CALC)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decide"]["skipped"] is True and body["calcs"][0]["display_text"] == ["-0.4%", "1.0%", "14.8%", "8.1%"]
    assert body["charts"]["c1"]["attempts"][0]["check"]["passed"] is True
    assert body["output"]["chart_plan"]["answer_steps"][0]["base"] == "prev"
