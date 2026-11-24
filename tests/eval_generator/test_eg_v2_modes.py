"""v2 실행 조건(m3_only) · 차트 요구 모드 · 집계 키"""
import dataclasses
import json

import pytest

from eval.generator import v2
from eval.generator.checks import chart_request
from eval.generator.report import compare, split_by_condition, summarize
from eval.generator.schema_v2 import Case, to_question
from eval.generator.verdict import RunVerdict, judge

FX = json.loads(v2.FIXTURE.read_text(encoding="utf-8"))
CASE = Case.model_validate(FX["cases"]["R01"])
Q = to_question(CASE, version=FX["dataset_version"])


def _run(answer="2024년 전국 출생아 수는 238,317명입니다."):
    return v2.gold_run(CASE, FX["inputs"]["R01"], answer)


def test_m3_only_judges_module3_without_answer():
    r = _run("")
    r["condition"] = "m3_only"
    v = judge(Q, r)
    assert (v.condition, v.verdict) == ("m3_only", "통과")
    assert not [f for f in v.findings if f["module"] == "M6" and f["stage"] != "metric"]


def test_m3_only_wrong_value_fails():
    r = _run("")
    r["condition"] = "m3_only"
    r["modules"]["module3"]["calc_results"][0]["value"][0]["value"] = 1.0
    assert judge(Q, r).verdict == "미달"


@pytest.mark.parametrize("mode,types,drawn,ok", [
    ("forbidden", [None], None, True), ("forbidden", [None], "bar", False),
    ("required", ["line"], "line", True), ("required", ["line"], "bar", False),
    ("fallback", ["bar", None], None, True), ("fallback", ["bar", None], "pie", False)])
def test_chart_mode(mode, types, drawn, ok):
    q = Q.model_copy(update={"chart_mode": mode, "chart_types": types, "v2": {"required_chart": {"mode": mode}}})
    r = _run()
    if drawn:
        r["modules"]["module3"]["chart_contents"] = [{"chart_id": r["modules"]["charts"][0]["chart_id"], "chart_type": drawn}]
    rows = [f for f in chart_request.mode_check(q, r) if f.code == "chart_mode"]
    assert [f.ok for f in rows] == [ok]


def _a0_stop_run(answer: str, status="needs_selection"):
    r = _run(answer)
    r["viewset"] = {**r["viewset"], "status": status}
    r["modules"]["module3"]["calc_results"] = []
    r["modules"]["qa"] = {"stopped_at": "A0", "issues": [{"kind": "enum"}]}
    return r


@pytest.mark.parametrize("answer,verdict", [
    ("동일한 좌표에 두 값이 충돌합니다. 어느 자료를 사용할지 선택해 주세요.", "통과"),
    ("에이전트 입력 단계에서 결과 형식이 올바르지 않아 답변을 만들지 못했습니다.", "보류")])
def test_a0_stop_guidance_must_match_reason(answer, verdict):
    """B16 유형: A0 에서 멈춘 것은 맞아도 안내가 '선택지 확인' 이 아니면 보류"""
    d = Q.model_dump()
    d["sub_questions"][0].update(answerable_when=[{"expect": "hold", "hold_reason": "unresolved_conflict"}], values=[])
    q = type(Q).model_validate(d)
    assert judge(q, _a0_stop_run(answer)).verdict == verdict


def _v(cond, verdict="통과", qid="R01", h=None):
    return RunVerdict(id=qid, run=1, verdict=verdict, expected="answer", observed="answer", a0_expected="continue",
                      a0_observed="continue", dataset="v2", dataset_version="x", condition=cond, input_hash=h)


def test_same_id_different_condition_is_not_merged():
    s = summarize([_v("isolated", "통과"), _v("m3_only", "미달")])
    assert s["questions"] == 2
    assert set(split_by_condition([_v("isolated"), _v("m3_only")])) == {("v2", "x", "isolated"), ("v2", "x", "m3_only")}


def test_input_hash_change_is_reported():
    s = summarize([_v("isolated", h="a"), dataclasses.replace(_v("isolated", h="b"), run=2)])
    assert s["input_hash_changed"] == ["R01"]


def test_compare_rejects_different_conditions(tmp_path):
    from dataclasses import asdict
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text(json.dumps(asdict(_v("isolated")), ensure_ascii=False) + "\n", encoding="utf-8")
    b.write_text(json.dumps(asdict(_v("live")), ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        compare(a, b)
    assert "회귀 없음" in compare(a, a)


# ── isolated 전체 실행 후 판정 규칙 결정 (R18 · S04 · B16 · C19 · M04) ──
def test_single_input_aggregate_counts_as_raw():
    """R18: '평균 매출액' 1행에 mean 을 적용한 계획은 결과가 원값과 같다 → operation 통과, 지표로만 기록"""
    from eval.generator.checks import m3 as m3c
    assert m3c.degenerate_aggregate({"op": "aggregate", "agg": "mean", "inputs": [{"value": 6261}]})
    assert not m3c.degenerate_aggregate({"op": "aggregate", "agg": "mean", "inputs": [{"value": 1}, {"value": 2}]})
    assert not m3c.degenerate_aggregate({"op": "aggregate", "agg": "count", "inputs": [{"value": 1}]})


def test_calculation_impossible_explanation_is_not_causal():
    """S04: '계산이 불가능하기 때문' 은 계산 불가 설명이다 (통계 현상의 인과 단정이 아님)"""
    from eval.generator.checks import m6
    from tests.eval_generator._fx import run
    from eval.generator.schema import Question
    q = Question.model_validate({"id": "S04", "question": "%p 차이"})
    text = "%p 차이는 계산할 수 없습니다. 이유는 값이 가상시로 제공되어 계산이 불가능하기 때문입니다."
    assert not m6.causal_checks(q, run([], [], text))
    assert [f.ok for f in m6.causal_checks(q, run([], [], "출산율 하락은 정책 때문입니다."))] == [False]


@pytest.mark.parametrize("status,reason,want", [
    ("needs_selection", "unresolved_conflict", "통과"),
    ("needs_clarification", "missing_conversation_context", "통과"),
    ("needs_selection", "missing_conversation_context", "보류")])
def test_pipeline_status_is_judged_by_expected_reason(status, reason, want):
    """B16 · C19: 운영 pipeline 은 이 상태를 Generator 앞에서 반환한다. 상태가 기대 보류 사유와 맞으면 통과"""
    from eval.generator.verdict import judge
    from eval.generator.schema import Question
    q = Question.model_validate({"id": "B16", "question": "q", "dataset": "v2", "sub_questions": [
        {"key": "main", "answerable_when": [{"expect": "hold", "hold_reason": reason}]}]})
    r = {"id": "B16", "run": 1, "ok": True, "pipeline_status": status, "analysis": {"status": "ok"}, "result": None}
    assert judge(q, r).verdict == want


def test_out_of_scope_status_gets_pipeline_guidance():
    """M04: out_of_scope 는 Generator 를 부르지 않고 고정 안내 답변을 기록한다"""
    from eval.generator.run import isolated_one
    inp = {"viewset": {"status": "out_of_scope", "query_id": "M04", "records": []},
           "query_bundle": {"query_id": "M04", "original": "파스타", "sub_questions": []}}
    r = isolated_one("M04", "파스타 만드는 법", inp, 1, input_hash="h", version="v", draw=False, max_rows=10)
    assert r["pipeline_status"] == "out_of_scope" and r["analysis"]["status"] == "out_of_scope"
    assert "통계 수치를 묻는" in r["result"]["answer"] and not r.get("modules")


# ── 입력 슬롯 overlay ──
def _inp():
    qb = {"query_id": "C02", "original": "q", "filters": {"의도": "값 조회"}, "sub_questions": ["q"], "sub_filters": [{"의도": "값 조회"}]}
    return {"query_bundle": qb, "viewset": {"status": "ok", "view_bundle": json.loads(json.dumps(qb)), "records": [{"id": "r"}]}}


SLOT = {"filters": {"시점": [2024], "지역": ["서울특별시", "부산광역시"], "의도": "값 조회"},
        "sub_filters": [{"시점": [2024], "지역": ["서울특별시", "부산광역시"], "의도": "값 조회"}]}


def test_apply_slots_replaces_filters_only():
    inp = _inp()
    out = v2.apply_slots(inp, SLOT)
    for vb in (out["query_bundle"], out["viewset"]["view_bundle"]):
        assert vb["filters"] == SLOT["filters"] and vb["sub_filters"] == SLOT["sub_filters"] and vb["original"] == "q"
    assert inp["query_bundle"]["filters"] == {"의도": "값 조회"}          # 원본은 바꾸지 않는다
    assert out["viewset"]["records"] == inp["viewset"]["records"]
    assert v2.apply_slots(inp, None) is inp


def test_slot_hash_changes_input_hash():
    assert v2.slot_hash("abc", None) == "abc"
    assert v2.slot_hash("abc", SLOT) != "abc" and v2.slot_hash("abc", SLOT) == v2.slot_hash("abc", json.loads(json.dumps(SLOT)))


def test_slot_errors(tmp_path):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "C02.json").write_text(json.dumps(_inp(), ensure_ascii=False), encoding="utf-8")
    assert v2.slot_errors(tmp_path, {"C02": SLOT}, {"C02"}) == []
    bad = {"C02": {"filters": {"도시": ["x"]}, "sub_filters": []}, "Z99": SLOT}
    errs = v2.slot_errors(tmp_path, bad, {"C02"})
    assert any("Z99" in e for e in errs) and any("sub_filters 0개" in e for e in errs) and any("도시" in e for e in errs)


def test_slot_errors_use_filters_schema(tmp_path):
    """dry run 에서 비교축 리스트가 A0 형식 검사(Filters: 비교축 str)에 걸려 멈췄다 → check 가 먼저 거부한다"""
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "C02.json").write_text(json.dumps(_inp(), ensure_ascii=False), encoding="utf-8")
    bad = {"C02": {"filters": {"비교축": ["지역", "연도"]}, "sub_filters": [{"연령": ["0~5세"]}]}}
    errs = v2.slot_errors(tmp_path, bad, {"C02"})
    assert any("비교축" in e for e in errs) and any("연령" in e for e in errs)
