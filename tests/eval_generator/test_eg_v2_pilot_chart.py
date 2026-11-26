"""pilot100 차트 요청 · 부분 답변 판정 (데이터셋 없이 도는 최소 fixture)

G0235-A(도넛 요구) · G0007-H(꺾은선 요청, 부분 차트 허용) · G0235-H(도넛 요청, 부분 차트도 불허) 와 같은 모양의 문항을 인라인으로 만든다.
"""
import json

import pytest

from eval.generator import v2
from eval.generator.checks import chart_request
from eval.generator.schema import Rule
from eval.generator.schema_v2 import Case, chart_request_of, requested_charts, to_question
from eval.generator.verdict import judge

FX = json.loads(v2.FIXTURE.read_text(encoding="utf-8"))
R01 = Case.model_validate(FX["cases"]["R01"])


def _case(question, mode, types, *, partial=None, notice=False, coverage=("chart_request",), points=None, target=None):
    spec = {"status": "withheld" if mode == "forbidden" else "required"}
    if partial is not None:
        spec["partial_allowed"] = partial
    return Case.model_validate({
        "id": "T1", "group": "boundary", "question": question, "coverage": list(coverage),
        "required_chart": {"mode": mode, "acceptable_types": types, "notice_required": notice},
        "chart_spec": spec,
        "expected_answer": {"allowed_statuses": ["hold", "partial"], "missing_target": target,
                            "points": [{"label": k, "value": str(v)} for k, v in (points or {}).items()]}})


G0235A = _case("2024년 서울·부산·대전의 출생아수 분포를 도넛 그래프로 보여줘.", "required", ["donut"])
G0007H = _case("2021년·2022년·2023년·2024년·2025년의 상륙허가자를 꺾은선그래프로 비교해줘.", "forbidden", [None], partial=True, notice=True,
               points={"2021년": 860859, "2022년": 1003085, "2023년": 1424869, "2024년": 2121106}, target="2025")
G0235H = _case("2024년 서울·부산·대전의 출생아수 분포를 도넛 그래프로 보여줘.", "forbidden", [None], partial=False, notice=True,
               points={"서울특별시": 41605, "부산광역시": 13063}, target="대전광역시")


# ── 변환 ─────────────────────────────────────────────────────────
def test_required_becomes_honored_request():
    cr = chart_request_of(G0235A)
    assert [(p.code, p.supported) for p in cr.preferred] == [("donut", True)]
    assert (cr.expected_outcome.outcome, cr.expected_outcome.final_chart, cr.notice_required) == ("honored", "donut", False)
    assert cr.allowed_outcomes == []


def test_forbidden_partial_allowed_accepts_partial_chart_or_table():
    cr = chart_request_of(G0007H)
    assert [p.code for p in cr.preferred] == ["line"]
    assert [o.outcome for o in cr.allowed_outcomes] == ["honored", "table_only"] and cr.notice_required


def test_forbidden_partial_not_allowed_accepts_table_only():
    cr = chart_request_of(G0235H)
    assert cr.expected_outcome.outcome == "table_only" and cr.allowed_outcomes == []


def test_no_chart_request_coverage_keeps_none():
    """기존 v2(gapset)는 coverage 에 chart_request 가 없다 → '요청 없음이 정답' 검사를 그대로 받는다"""
    c = _case("2024년 출생아 수는?", "optional", [None], coverage=("raw",))
    assert chart_request_of(c) is None and to_question(c, version="x").chart_request is None


@pytest.mark.parametrize("q,codes,unknown", [
    ("상륙허가자를 꺾은선그래프로 비교해줘.", ["line"], []),
    ("출생아수 분포를 도넛 그래프로 보여줘.", ["donut"], []),
    ("지역별 인구를 막대그래프로 비교해줘.", ["bar"], []),
    ("지역별 인구를 히트맵 그래프로 보여줘.", [], ["히트맵"])])
def test_requested_charts(q, codes, unknown):
    named, unk = requested_charts(q)
    assert [c for _, c in named] == codes and unk == unknown


def test_chart_name_errors():
    ok = _case("인구를 막대그래프로 보여줘.", "required", ["bar"])
    wrong = _case("인구를 막대그래프로 보여줘.", "required", ["line"])
    unk = _case("인구를 히트맵 그래프로 보여줘.", "forbidden", [None])
    assert v2.chart_name_errors([ok]) == []
    assert len(v2.chart_name_errors([wrong, unk])) == 2


# ── 요청 판정 (check) ────────────────────────────────────────────
def _run(outcome, final=None, rows=None, reason=None, notices=None, request=None, ctype="line"):
    r = v2.gold_run(R01, FX["inputs"]["R01"], "2024년 전국 출생아 수는 238,317명입니다.")
    cid = r["modules"]["charts"][0]["chart_id"]
    r["modules"]["charts"][0]["request"] = request or {"preferred": [{"text": "꺾은선", "code": "line", "supported": True}], "excluded": [],
                                                       "scope": [cid], "stage": {}}
    r["modules"]["request_outcomes"] = [{"chart_id": cid, "outcome": outcome, "reason": reason, "final_chart": final}]
    r["modules"]["render_status"] = {cid: {"state": "drawn"}}
    r["modules"]["chart_notices"] = notices or []
    if rows is not None:
        r["modules"]["module3"]["chart_contents"] = [{"chart_id": cid, "chart_type": ctype, "rows": rows}]
    return r


def _codes(fs):
    return {f.code: f.ok for f in fs}


def test_request_not_misparsed_when_expected():
    q = to_question(G0235A, version="x")
    r = _run("honored", "donut", request={"preferred": [{"text": "도넛", "code": "donut", "supported": True}], "excluded": [], "scope": [], "stage": {}})
    c = _codes(chart_request.check(q, r))
    assert c["request_parse"] and c["request_outcome"] and c["notice"] and "request_misparse" not in c


@pytest.mark.parametrize("outcome,reason,final,notices,ok_outcome,ok_notice", [
    ("honored", None, "line", [], True, True),                       # 부분 차트: 안내 불필요
    ("honored", None, "line", ["부분 차트입니다"], True, False),      # 안내가 있으면 need=False 와 어긋남
    ("table_only", "data_mismatch", None, ["표로 보여 드립니다"], True, True),
    ("table_only", "data_mismatch", None, [], True, False),           # 표만인데 안내 없음
    ("substituted", "data_mismatch", "bar", ["막대로 대체"], False, True)])
def test_partial_allowed_outcomes(outcome, reason, final, notices, ok_outcome, ok_notice):
    q = to_question(G0007H, version="x")
    c = _codes(chart_request.check(q, _run(outcome, final, reason=reason, notices=notices)))
    assert (c["request_outcome"], c["notice"]) == (ok_outcome, ok_notice)


def test_single_outcome_set_unchanged():
    """allowed_outcomes 가 없는 문항(ext-chart-request 등)은 기존대로 expected_outcome 하나로 판정"""
    q = to_question(G0235H, version="x")
    assert _codes(chart_request.check(q, _run("honored", "donut")))["request_outcome"] is False
    assert _codes(chart_request.check(q, _run("table_only", None, reason="data_mismatch", notices=["x"])))["request_outcome"] is True


# ── 부분 차트 (mode_check) ───────────────────────────────────────
LINE_OK = [["2021", "총계", "상륙허가자", 860859], ["2022", "총계", "상륙허가자", 1003085], ["2023", "총계", "상륙허가자", 1424869]]


def _mode(case, rows):
    q = to_question(case, version="x")
    return chart_request.mode_check(q, _run("honored", "line", rows=rows))


def test_partial_chart_with_confirmed_points_passes():
    fs = _mode(G0007H, LINE_OK)
    assert [(f.code, f.ok) for f in fs] == [("chart_mode", True)]


def test_partial_chart_drawing_missing_target_fails():
    fs = _mode(G0007H, LINE_OK + [["2025", "총계", "상륙허가자", 0]])
    assert fs[0].ok is False and "누락 대상" in fs[0].message


def test_partial_chart_with_unsupported_point_fails():
    fs = _mode(G0007H, LINE_OK[:2] + [["2023", "총계", "상륙허가자", 999]])          # 값이 근거 점과 다르다
    assert fs[0].ok is False and "근거 점이 아닌" in fs[0].message


def test_partial_not_allowed_drawn_fails_chart_mode():
    fs = _mode(G0235H, [["2024", "서울특별시", "출생아수", 41605], ["2024", "부산광역시", "출생아수", 13063]])
    assert [(f.code, f.ok) for f in fs] == [("chart_mode", False)]


def test_forbidden_without_chart_spec_stays_metric_only():
    """chart_spec 에 partial_allowed 가 없는 기존 forbidden 문항: chart_mode 지표만, 보류로 세지 않는다"""
    case = _case("인구를 막대그래프로 보여줘.", "forbidden", [None])
    fs = _mode(case, [["2024", "전국", "인구", 1.0]])
    assert [(f.code, f.ok) for f in fs] == [("chart_mode", False)]


# ── 판정 (judge) ─────────────────────────────────────────────────
def _hold_question(allowed=True, target="2025"):
    """R01 의 값 하나를 '기대 hold' 로 바꾼 문항 (모듈이 값을 냈다 = 부분 답변)"""
    base = to_question(R01, version="x")
    sub = base.sub_questions[0].model_copy(update={"answerable_when": [Rule(expect="hold", hold_reason="missing_operand")], "values": []})
    ans = {"allowed_statuses": ["hold", "partial"] if allowed else ["hold"], "missing_target": target}
    return base.model_copy(update={"sub_questions": [sub], "v2": {**base.v2, "expected_answer": ans}})


def _answer_run(text):
    return v2.gold_run(R01, FX["inputs"]["R01"], text)


@pytest.mark.parametrize("allowed,text,tags_in,tags_out", [
    (True, "2024년 전국 출생아 수는 238,317명입니다. 2025년 자료는 확인할 수 없습니다.", {"partial_answer"}, {"needs_review", "rule_review"}),
    (True, "2024년 전국 출생아 수는 238,317명입니다. 일부 자료는 없습니다.", {"needs_review", "rule_review"}, {"partial_answer"}),   # 누락 대상을 말하지 않음
    (False, "2024년 전국 출생아 수는 238,317명입니다. 2025년 자료는 확인할 수 없습니다.", {"needs_review", "rule_review"}, {"partial_answer"})])  # partial 불허
def test_partial_answer_is_judged_automatically(allowed, text, tags_in, tags_out):
    v = judge(_hold_question(allowed), _answer_run(text))
    assert tags_in <= set(v.tags) and not (tags_out & set(v.tags))
    assert not [f for f in v.findings if f["code"] == "hold_but_value" and f["ok"] is False]


def _forbidden(partial, rows, rules=3, points=None, target="2025"):
    """R01 답변(통과 조건)에 forbidden 차트를 붙인 판정. chart_structure ⑤b 는 judge_rules >= 3 에만 적용된다"""
    q = to_question(R01, version="x").model_copy(update={"chart_mode": "forbidden", "chart_types": [None]})
    spec = {} if partial is None else {"partial_allowed": partial}
    ans = {"allowed_statuses": ["hold", "partial"], "missing_target": target,
           "points": [{"label": k, "value": str(v)} for k, v in (points or {}).items()]}
    q = q.model_copy(update={"v2": {**q.v2, "required_chart": {"mode": "forbidden"}, "chart_spec": spec, "expected_answer": ans}})
    r = _answer_run("2024년 전국 출생아 수는 238,317명입니다.")
    r["judge_rules"] = rules
    cid = r["modules"]["charts"][0]["chart_id"]
    r["modules"]["module3"]["chart_contents"] = [{"chart_id": cid, "chart_type": "bar", "rows": rows}]
    r["modules"]["drawn"] = [{"chart_id": cid, "status": "drawn"}]
    return judge(q, r)


PTS = {"2024": 238317}


def test_forbidden_chart_drawn_holds_verdict():
    v = _forbidden(False, [["2024", "전국", "출생아수", 238317]])
    assert v.verdict == "보류" and "chart_unmet" in v.tags


def test_forbidden_without_partial_flag_keeps_existing_rule():
    """partial_allowed 명시가 없는 기존 forbidden 문항은 ⑤b 그대로 (차트가 있으면 보류) · 판정 규칙 3 미만 실행은 적용하지 않는다"""
    assert "chart_unmet" in _forbidden(None, [["2024", "전국", "출생아수", 238317]]).tags
    assert "chart_unmet" not in _forbidden(False, [["2024", "전국", "출생아수", 238317]], rules=2).tags


def test_partial_allowed_chart_with_confirmed_points_is_not_held():
    v = _forbidden(True, [["2024", "전국", "출생아수", 238317]], points=PTS)
    assert "chart_unmet" not in v.tags and v.verdict == "통과"


def test_partial_allowed_chart_with_missing_target_is_held():
    v = _forbidden(True, [["2024", "전국", "출생아수", 238317], ["2025", "전국", "출생아수", 0]], points=PTS)
    assert v.verdict == "보류" and "chart_unmet" in v.tags
