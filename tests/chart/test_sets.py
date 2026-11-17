"""세트(질문 · 차트 유형 · View) 전달 시험 — HCX 없이 돈다"""
import copy
import json
from pathlib import Path

import pytest

from backend.agent.chart_calculate.decide import build_prompt
from backend.agent.chart_calculate.from_module2 import skipped_sets, to_module3_request
from backend.agent.chart_calculate.planner import AnswerDecision, ChartDecision, Decision, _Planner, make_plan
from backend.schemas.chart import ChartRequest
from backend.schemas.query import QueryBundle

HERE = Path(__file__).parent
V1 = "view::101_DT_1B8000G::Y::27077dec-1-1::trend"
V2 = "view::101_DT_1B8000G::Y::27077dec-2-1::trend"


def _load(rel):
    return json.loads((HERE / rel).read_text(encoding="utf-8"))


@pytest.fixture()
def req():
    return to_module3_request(_load("module2_sample/chart_plan.json"), _load("module2_sample/view_input.json"),
                              _load("baseline/request.json")["query_bundle"])


def test_prompt_without_view_ids_is_byte_identical_to_golden(req):
    charts = [c.model_copy(update={"view_ids": []}) for c in req.charts]
    gold = (HERE / "golden/prompt_without_view_ids.txt").read_text(encoding="utf-8")
    assert build_prompt(req.query_bundle, req.records, charts) == gold


def test_set_prompt_shows_each_set_with_only_its_view(req):
    text = build_prompt(req.query_bundle, req.records, req.charts)
    c1, c2 = text.split("[세트 c2]")
    assert "[세트 c1]" in c1 and V1 in c1 and V2 not in c1
    assert V2 in c2 and V1 not in c2
    assert "[하위 질문]" not in text and "[자료]" not in text


def test_set_prompt_chart_none_and_skipped_and_missing(req):
    charts = [req.charts[0].model_copy(update={"chart_type": None}),
              ChartRequest(chart_id="x1", sub_question_ids=["27077dec-2"], reason="모듈 2 가 건너뜀: 필터 결과 0행"),
              req.charts[1].model_copy(update={"chart_id": "c9", "view_ids": ["view::없음"]})]
    text = build_prompt(req.query_bundle, req.records, charts)
    assert "차트: 없음 (질문용 계산만)" in text
    assert "자료: (없음 — 모듈 2 가 건너뜀: 필터 결과 0행) → 이 세트는 계산하지 않는다" in text
    assert "자료 없음: record_id=view::없음 가 records 에 없음" in text


def test_set_prompt_combo_lists_every_view(req):
    combo = req.charts[0].model_copy(update={"chart_type": "combo", "view_ids": [V1, V2, V1]})
    text = build_prompt(req.query_bundle, req.records, [combo])
    assert text.count(f"- record_id={V1}") == 2 and text.count(f"- record_id={V2}") == 1


# ── planner: 세트 밖 View 경고 ───────────────────────────────────────────
def _chart_dec(rid):
    return ChartDecision(chart_id="c1", record_id=rid, select={"행정구역별": ["전국"]})


def test_pick_outside_set_warns_but_plan_is_kept(req):
    charts = [req.charts[0]]
    plan, _ = make_plan(charts, req.records, Decision(charts=[_chart_dec(V2)], answers=[]), req.query_bundle)
    assert plan.plans and plan.plans[0].record_id == V2
    assert any("view_ids" in n and V2 in n for n in plan.notes)


def test_pick_inside_set_has_no_warning(req):
    plan, _ = make_plan([req.charts[0]], req.records, Decision(charts=[_chart_dec(V1)], answers=[]), req.query_bundle)
    assert not any("view_ids" in n for n in plan.notes)


def test_no_view_ids_means_no_check(req):
    charts = [req.charts[0].model_copy(update={"view_ids": []})]
    plan, _ = make_plan(charts, req.records, Decision(charts=[_chart_dec(V2)], answers=[]), req.query_bundle)
    assert not any("view_ids" in n for n in plan.notes)


def _ans(sid, rid):
    return AnswerDecision.model_validate({"sub_question_id": sid, "op": "raw",
                                          "operands": [{"record_id": rid, "item": "혼인건수(건)", "select": {}}]})


def test_answer_outside_set_warns(req):
    plan, _ = make_plan(req.charts, req.records, Decision(charts=[], answers=[_ans("27077dec-1", V2)]), req.query_bundle)
    assert any("27077dec-1" in n and "view_ids" in n for n in plan.notes)


def test_answer_of_skipped_set_is_dropped_with_reason(req):
    skipped = ChartRequest(chart_id="x1", sub_question_ids=["27077dec-2"], reason="모듈 2 가 건너뜀: 필터 결과 0행")
    charts = [req.charts[0], skipped]
    plan, _ = make_plan(charts, req.records, Decision(charts=[], answers=[_ans("27077dec-2", V2)]), req.query_bundle)
    assert plan.answer_steps == []
    assert any("필터 결과 0행" in n and "질문용 계산을 만들지 않음" in n for n in plan.notes)


# ── 어댑터: 건너뛴 하위 질문 → x1, x2 ──────────────────────────────────────
def test_skipped_sets_by_unit_id_and_by_text(req):
    b = req.query_bundle
    errs = [{"chart_id": "c2", "unit_id": "27077dec-2", "reason": "필터 결과 0행"}]
    out = skipped_sets(errs, b, [req.charts[0]])
    assert [(c.chart_id, c.sub_question_ids, c.view_ids, c.chart_type) for c in out] == [("x1", ["27077dec-2"], [], None)]
    assert "필터 결과 0행" in out[0].reason
    by_text = [{"sub_question": b.sub_questions[1], "reason": "짝 없음"}]
    assert skipped_sets(by_text, b, [req.charts[0]])[0].sub_question_ids == ["27077dec-2"]


def test_skipped_sets_ignores_warnings_unmappable_and_covered(req):
    errs = [{"level": "warning", "unit_id": "27077dec-2", "reason": "경고"},
            {"node": "load_input", "reason": "입력 문제"},
            {"unit_id": "27077dec-1", "reason": "이미 차트 있음"}]
    assert skipped_sets(errs, req.query_bundle, req.charts[:1]) == []


def test_skipped_set_gets_the_same_index_view_when_the_unit_has_one(req):
    views = _load("module2_sample/view_input.json")
    errs = [{"chart_id": "c2", "unit_id": "27077dec-2", "reason": "필터 결과 0행"}]
    out = skipped_sets(errs, req.query_bundle, [req.charts[0]], views)
    assert out[0].view_ids == [V2] and out[0].chart_type is None
    assert "질문용 계산만" in out[0].reason
    views = copy.deepcopy(views)
    next(u for u in views["units"] if u["unit_id"] == "27077dec-2")["views"] = []
    assert skipped_sets(errs, req.query_bundle, [req.charts[0]], views)[0].view_ids == []
