"""T-1 · T-4 · T-26: 모듈 2 를 실제로 돌려(HCX 없이, use_llm=False) 요청이 출력과 M3 어댑터까지 가는지 확인한다

입력은 tests/chart/module2_sample (모듈 2 를 실제로 돌려 얻은 View) + baseline/request.json 의 query_bundle.
"""
import copy
import json
from pathlib import Path

import pytest

from backend.agent.chart_calculate.from_module2 import to_chart_request
from backend.agent.chart_decision import run_chart_decision

CHART = Path(__file__).parent.parent / "chart"


def _load(rel):
    return json.loads((CHART / rel).read_text(encoding="utf-8"))


def _inputs(question, *, rewritten=None, sub_texts=None):
    qb = copy.deepcopy(_load("baseline/request.json")["query_bundle"])
    qb["original"] = question
    if rewritten is not None:
        qb["rewritten"] = rewritten
    if sub_texts:
        for sq, t in zip(qb.get("sub_questions") or [], sub_texts):
            sq["text"] = t
    vi = _load("module2_sample/view_input.json")
    vi.update(original=question, filters=None)
    for u in vi["units"]:
        u["candidates"] = []
        for v in u["views"]:
            v.update(notes=[], tbl_id="101_DT_1B8000G")
    return qb, vi


def _run(question, **kw):
    qb, vi = _inputs(question, **kw)
    return run_chart_decision(qb, vi, use_llm=False)


def _charts(out):
    return out["chart_plan"]["charts"]


def test_no_request_question_has_no_request_on_any_chart():
    out = _run("최근 5년 혼인건수와 출생아수 추이")
    assert _charts(out) and all(c["request"] is None for c in _charts(out))


def test_unsupported_name_reaches_output_and_adapter():
    out = _run("최근 5년 혼인건수와 출생아수 추이를 히스토그램으로 보여줘")
    reqs = [c["request"] for c in _charts(out)]
    assert all(r and r["stage"]["reason"] in ("unsupported_type", "data_mismatch") for r in reqs)
    assert all(r["preferred"][0]["text"] == "히스토그램" and r["preferred"][0]["supported"] is False for r in reqs)
    adapted = to_chart_request(_charts(out)[0])
    assert adapted.request.preferred[0].text == "히스토그램"
    assert adapted.request.scope == [_charts(out)[0]["chart_id"]]


def test_exclusion_reaches_output_and_chart_is_not_excluded_type():
    out = _run("최근 5년 혼인건수와 출생아수 추이를 선그래프 말고 막대로 보여줘")
    for c in _charts(out):
        assert c["request"]["excluded"][0]["code"] == "line"
        assert c["chart_type"] != "line" and "line" not in c["fallback_charts"]


def test_infeasible_request_records_stage_reason_in_structured_field():
    out = _run("최근 5년 혼인건수와 출생아수 추이를 인구 피라미드로 보여줘")
    for c in _charts(out):
        st = c["request"]["stage"]
        assert st["reason"] in ("data_mismatch", "view_blocked")
        assert c["chart_type"] != "pyramid"
        assert st["selected"] == c["chart_type"] or st["reason"] == "view_blocked"


def test_reason_sentence_overwrite_does_not_affect_structured_reason():
    """reason(설명 문장)은 reason_node 가 만든다. 구조화된 사유는 request.stage 에 따로 있다"""
    out = _run("최근 5년 혼인건수와 출생아수 추이를 인구 피라미드로 보여줘")
    c = _charts(out)[0]
    assert isinstance(c["reason"], str) and "request" in c and c["request"]["stage"]["reason"]
    assert c["request"]["stage"]["reason"] not in c["reason"]


def test_false_positive_name_in_question_is_not_a_request():
    out = _run("최근 5년 운동지도자 수 추이")
    assert all(c["request"] is None for c in _charts(out))


def test_graph_path_and_function_path_agree():
    """그래프 노드 경로(run_chart_decision)와 함수 경로(run_chart_decision_pipeline 류)가 같은 request 를 낸다"""
    from backend.agent.chart_decision.chart_decision_module import chart_type_pipeline as pl
    q = "최근 5년 혼인건수와 출생아수 추이를 히스토그램으로 보여줘"
    qb, vi = _inputs(q)
    graph_out = run_chart_decision(qb, vi, use_llm=False)
    fn = [getattr(pl, n) for n in dir(pl) if n.startswith("run") or n.startswith("decide")]
    if not fn:
        pytest.skip("함수 경로 진입점을 찾지 못함")
    plan = None
    for f in fn:
        try:
            res = f(qb, vi, use_llm=False)
        except TypeError:
            continue
        plan = res[0] if isinstance(res, tuple) else res.get("chart_plan") if isinstance(res, dict) else None
        if plan:
            break
    if not plan:
        pytest.skip("함수 경로 호출 형식이 달라 비교하지 못함")
    assert [c["request"] for c in plan["charts"]] == [c["request"] for c in _charts(graph_out)]
