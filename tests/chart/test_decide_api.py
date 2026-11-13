"""POST /api/v1/chart/decide 시험 — 모듈 2 실제 실행 (use_llm=False 라 HCX 를 부르지 않는다)

입력은 module2_sample/ (모듈 2 를 실제로 돌려 얻은 chart_plan 과 그 입력 View), query_bundle 은 baseline/request.json 의 것.
"""
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app

HERE = Path(__file__).parent
client = TestClient(app)


def _load(rel):
    return json.loads((HERE / rel).read_text(encoding="utf-8"))


def _body(use_llm=False):
    """/views/detail 응답 모양(ViewResult)으로 맞춘 요청. 시험 자료에 없는 필수 필드만 채운다"""
    vi = _load("module2_sample/view_input.json")
    vi.update(original="최근 5년 혼인건수와 출생아수 추이", filters=None)
    for u in vi["units"]:
        u["candidates"] = []
        for v in u["views"]:
            v.update(notes=[], tbl_id="101_DT_1B8000G")
    return {"query_bundle": _load("baseline/request.json")["query_bundle"], "view_input": vi, "use_llm": use_llm}


def test_decide_runs_module2_and_returns_its_plan():
    r = client.post("/api/v1/chart/decide", json=_body())
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["errors"] == []
    assert res["chart_plan"] == _load("module2_sample/chart_plan.json")      # 모듈 2 원본 그대로


def test_decide_charts_are_adapted_for_module3():
    res = client.post("/api/v1/chart/decide", json=_body()).json()
    c1 = res["charts"][0]
    assert (c1["chart_id"], c1["chart_type"], c1["measure"]) == ("c1", "line", "raw")
    assert c1["fallback_chart"] == "bar"                      # fallback_charts[0]
    assert c1["sub_question_ids"] == ["27077dec-1"]


def test_decide_then_calc_matches_baseline():
    """/decide 응답의 charts 를 /calc 에 넣으면 0단계 기준값과 같은 결과가 나온다 (HTTP 로만 이어서)"""
    charts = client.post("/api/v1/chart/decide", json=_body()).json()["charts"]
    calc = _load("baseline/request.json")
    calc.update(charts=charts, decision=_load("baseline/decision.json"))
    r = client.post("/api/v1/chart/calc", json=calc)
    assert r.status_code == 200, r.text
    assert r.json() == _load("baseline/output.json")


def test_decide_warns_when_query_ids_differ():
    body = _body()
    body["query_bundle"] = copy.deepcopy(body["query_bundle"])
    body["query_bundle"]["query_id"] = "다른ID"
    errors = client.post("/api/v1/chart/decide", json=body).json()["errors"]
    assert any("query_id" in e.get("reason", "") for e in errors)


def test_decide_without_views_returns_empty_charts_with_reason():
    body = _body()
    body["view_input"]["units"] = []
    res = client.post("/api/v1/chart/decide", json=body).json()
    assert res["errors"]                                      # 왜 비었는지 사유가 남는다
    # 차트는 없고, 건너뛴 하위 질문이 'View 없는 세트'(x1, x2)로 남는다 → 모듈 3 이 그 질문을 다른 View 로 계산하지 않는다
    assert [(c["chart_id"], c["chart_type"], c["view_ids"]) for c in res["charts"]] == [("x1", None, []), ("x2", None, [])]  # units 가 비어 짝지을 View 도 없다
    assert all("모듈 2 가 건너뜀" in c["reason"] for c in res["charts"])


@pytest.mark.parametrize("missing", ["query_bundle", "view_input"])
def test_decide_rejects_missing_input(missing):
    body = _body()
    body.pop(missing)
    assert client.post("/api/v1/chart/decide", json=body).status_code == 422


def test_decide_maps_main_when_there_are_no_sub_questions():
    """하위 질문이 없으면 모듈 2 는 'main' 을 낸다. 모듈 3 입력에서는 '{query_id}-1' 로 바뀌고 원본은 chart_plan 에 그대로 있다"""
    body = _body()
    body["query_bundle"] = copy.deepcopy(body["query_bundle"])
    body["query_bundle"]["sub_questions"], body["query_bundle"]["sub_filters"] = [], []
    body["view_input"]["units"] = [u for u in body["view_input"]["units"] if u["unit_id"] == "main"]
    res = client.post("/api/v1/chart/decide", json=body).json()
    assert res["chart_plan"]["charts"][0]["sub_question_ids"] == ["main"]       # 모듈 2 원본
    assert res["charts"][0]["sub_question_ids"] == ["27077dec-1"]               # 모듈 3 입력


def test_decide_passes_module2_view_ids_through_as_the_set():
    res = client.post("/api/v1/chart/decide", json=_body()).json()
    assert [c["view_ids"] for c in res["charts"]] == [c["view_ids"] for c in res["chart_plan"]["charts"]]
    assert res["charts"][0]["view_ids"] == ["view::101_DT_1B8000G::Y::27077dec-1-1::trend"]
    assert res["errors"] == []                                  # 세트의 View 가 모두 records 에 있다


def test_swagger_example_carries_a_set_and_the_schema_documents_view_ids():
    from backend.api.v1_chart import EX_CALC
    assert EX_CALC["charts"][0]["view_ids"] == [EX_CALC["records"][0]["id"]]
    props = client.get("/openapi.json").json()["components"]["schemas"]["ChartRequest"]["properties"]
    assert "view_ids" in props and "combo" in props["view_ids"]["description"]


def test_decide_returns_records_that_contain_every_set_view():
    res = client.post("/api/v1/chart/decide", json=_body()).json()
    ids = {r["id"] for r in res["records"]}
    assert {v for c in res["charts"] for v in c["view_ids"]} <= ids
    assert res["errors"] == []
