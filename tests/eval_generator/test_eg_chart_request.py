"""차트 지정 요청 (KOS-41)"""
from eval.generator.checks.chart_request import check
from eval.generator.schema import Question
from tests.eval_generator._fx import births, run, share_calc

CR02 = Question.model_validate({"id": "CR02", "question": "시도별 혼인건수를 히스토그램으로 보여줘", "chart_request": {
    "preferred": [{"text": "히스토그램", "supported": False}],
    "expected_outcome": {"outcome": "substituted", "reason": "unsupported_type"}, "notice_required": True}})
CR06 = Question.model_validate({"id": "CR06", "question": "2024년 운동지도자 수는?"})


def _run(request, outcome, render=None, notices=None):
    r = run([births()], [share_calc()], "…")
    r["modules"]["charts"] = [{"chart_id": "c1", "sub_question_ids": ["q1-1"], "chart_type": "bar", "request": request}]
    r["modules"]["request_outcomes"] = [outcome] if outcome else []
    r["modules"]["render_status"] = render or {"c1": {"state": "drawn"}}
    r["modules"]["chart_notices"] = notices or []
    return r


REQ = {"preferred": [{"text": "히스토그램", "code": None, "supported": False}], "excluded": [], "scope": "all", "stage": {}}


def codes(fs):
    return {f.code: f.ok for f in fs}


def test_substituted_matches():
    c = codes(check(CR02, _run(REQ, {"chart_id": "c1", "outcome": "substituted", "reason": "unsupported_type", "final_chart": "bar"},
                               notices=["히스토그램은 지원하지 않아 막대 그래프로 보여 드립니다"])))
    assert c["request_parse"] and c["request_outcome"] and c["outcome_combo"] and c["notice"]


def test_invalid_combo_flagged():
    c = codes(check(CR02, _run(REQ, {"chart_id": "c1", "outcome": "honored", "reason": "unsupported_type", "final_chart": "bar"})))
    assert c["outcome_combo"] is False


def test_render_stage_outcome_comes_from_render_status():
    r = _run(REQ, {"chart_id": "c1", "outcome": "not_rendered", "reason": "draw_disabled"},
             render={"c1": {"state": "skipped", "reason": "draw_disabled"}})
    assert codes(check(CR02, r))["request_outcome"] is True


def test_misparse_on_question_without_request():
    c = codes(check(CR06, _run({"preferred": [{"text": "지도", "code": "map", "supported": True}]}, None)))
    assert c["request_misparse"] is False
    assert codes(check(CR06, _run(None, None)))["request_misparse"] is True
