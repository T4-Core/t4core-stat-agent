"""[NEW] pipeline.py · v1_chart.py — 모듈 3 전체 흐름 (HCX 는 가짜 함수 또는 decision 직접 입력)"""
import pytest

from backend.agent.chart_calculate.pipeline import run_module3
from backend.agent.chart_calculate.planner import Decision
from backend.schemas.chart import Module3Request
from tests.chart_calculate._views import view
from tests.chart_calculate.test_decide import BUNDLE, CHARTS, REPLY, fake


def request(charts=CHARTS, records=None):
    return Module3Request(records=[view()] if records is None else records, query_bundle=BUNDLE, charts=charts)


def test_whole_output_shape_like_spec():
    """명세 2장 '전체 출력 모양'"""
    out = run_module3(request(), chat=fake(REPLY))
    assert out.query_id == "27077dec"
    assert [c.chart_id for c in out.chart_contents] == ["c1"] and out.chart_contents[0].chart_type == "line"
    assert [(r.step_id, r.display_ref) for r in out.calc_results] == [("a1", "d2"), ("a2", "d2")]
    assert [v["key"]["시점"] for v in out.calc_results[0].value] == ["2022", "2023", "2024", "2025"]   # 시점마다 직전 대비
    assert out.calc_results[0].value[-1]["value"] == pytest.approx((240326 - 222412) / 222412 * 100)
    assert {k: d.source_unit for k, d in out.displays.items()} == {"d1": "건", "d2": "%"}
    assert set(out.validation) == {"c1"} and out.validation["c1"].content_built      # 차트 없음(c9)은 validation 에 없다
    assert out.chart_contents[0].axis["y"].display_ref in out.displays


def test_decision_given_skips_hcx():
    def boom(*a, **k):
        raise AssertionError("HCX 를 부르면 안 된다")
    out = run_module3(request(), decision=Decision(), chat=boom)
    assert out.chart_contents == [] and out.calc_results == []


def test_hcx_failure_keeps_going_and_explains():
    out = run_module3(request(), chat=fake(RuntimeError("HTTP 500 / 50000: boom")))
    assert out.chart_plan.notes[0] == "HCX 호출 실패: HTTP 500 / 50000: boom"
    v = out.validation["c1"]
    assert (v.content_built, v.final_chart_type, v.original.failed) == (False, None, ["plan_present"])
    assert v.original.reasons == ["계획 결정이 없어 차트 계획을 만들지 않음"]


def test_answers_survive_chart_failure():
    """차트가 검증에서 떨어져도 질문용 계산은 전달된다 (명세 7장)"""
    reply = {**REPLY, "charts": [{**REPLY["charts"][0],
                                  "conditions": [{"column": "시점", "values": ["2025"]},
                                                 {"column": "항목", "values": ["혼인건수(건)"]},
                                                 {"column": "행정구역별", "values": ["전국"]}]}]}
    charts = [CHARTS[0].model_copy(update={"fallback_chart": None})]
    out = run_module3(request(charts), chat=fake(reply))
    assert out.chart_contents == [] and out.validation["c1"].original.failed == ["min_points_3"]
    assert len(out.calc_results) == 2 and out.calc_results[0].value is not None


# ── HTTP ─────────────────────────────────────────────────────────
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient   # noqa: E402

from backend.api.v1_chart import EX_CALC    # noqa: E402
from backend.main import app                 # noqa: E402

client = TestClient(app)


def test_api_swagger_example_runs_without_hcx():
    r = client.post("/api/v1/chart/calc", json=EX_CALC)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chart_contents"][0]["title"] == "2021~2025 혼인건수 연도별 추이"
    assert body["chart_contents"][0]["rows"][0] == ["2021", "혼인건수", 192507]
    assert [v["value"] for v in body["calc_results"][0]["value"]] == pytest.approx(
        [(b - a) / a * 100 for a, b in zip([192507, 191690, 193657, 222412], [191690, 193657, 222412, 240326])])
    step = body["chart_plan"]["answer_steps"][0]
    assert step["base"] == "prev" and step.get("from") is None      # 응답은 alias("from")로 나가고, 빈 값은 null
    assert body["validation"]["c1"]["final_chart_type"] == "line"
    assert body["displays"] == {"d1": {"source_unit": "건", "display_unit": "건", "unit_scale": 1.0, "digits": None},
                                "d2": {"source_unit": "%", "display_unit": "%", "unit_scale": 1.0, "digits": None}}


def test_api_rejects_unknown_chart_type():
    bad = {**EX_CALC, "charts": [{**EX_CALC["charts"][0], "chart_type": "sankey"}]}
    assert client.post("/api/v1/chart/calc", json=bad).status_code == 422


def test_api_specs():
    body = client.get("/api/v1/chart/specs").json()
    assert len(body) == 15 and body["pie"]["required"] == ["label", "value"]
