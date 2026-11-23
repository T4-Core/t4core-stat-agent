"""기대 하위 질문 ↔ 출력 하위 질문 대응 · 지표 분모 (계획 2.4.1, D-11)"""
from eval.generator.report import summarize
from eval.generator.schema import Question
from eval.generator.subq import match
from eval.generator.verdict import judge
from tests.eval_generator._fx import record, run

Q27 = Question.model_validate({
    "id": "Q27", "question": "최근 5년 혼인건수와 출생아수 추이",
    "sub_questions": [
        {"key": "marriage", "match": {"item_any": ["혼인건수"]}, "m3": {"op": "raw"},
         "answerable_when": [{"when": {"view_has_rows": {"item": "혼인건수", "min_periods": 2}}, "expect": "answer"},
                             {"expect": "hold", "hold_reason": "from_predicate"}]},
        {"key": "births", "match": {"item_any": ["출생아수"]}, "m3": {"op": "raw"},
         "answerable_when": [{"when": {"view_has_rows": {"item": "출생아수", "min_periods": 2}}, "expect": "answer"},
                             {"expect": "hold", "hold_reason": "from_predicate"}]}]})
SUBS = ["최근 5년 혼인건수", "최근 5년 출생아수"]
MARR = record("m", ["시점", "항목", "값"], [["2021", "혼인건수(건)", 1.0], ["2022", "혼인건수(건)", 2.0]], "건")
BIRTH = record("b", ["시점", "항목", "값"], [["2021", "출생아수(명)", 3.0], ["2022", "출생아수(명)", 4.0]], "명")


def calc(sid, sub, rid, item, vals):
    return {"step_id": sid, "sub_question_id": sub, "op": "raw", "unit": None,
            "value": [{"key": {"시점": p}, "value": v} for p, v in vals],
            "inputs": [{"role": "value", "record_id": rid, "item": item, "key": {"시점": p}, "value": v} for p, v in vals],
            "record_ids": [rid]}


C1 = calc("a1", "q1-1", "m", "혼인건수(건)", [("2021", 1.0), ("2022", 2.0)])
C2 = calc("a2", "q1-2", "b", "출생아수(명)", [("2021", 3.0), ("2022", 4.0)])


def test_both_matched():
    res, extra = match(Q27, run([MARR, BIRTH], [C1, C2], "…", question=Q27.question, subs=SUBS))
    assert [(r.status, r.observed) for r in res] == [("matched", "value"), ("matched", "value")] and not extra


def test_missing_births_counts_in_denominator():
    v = judge(Q27, run([MARR, BIRTH], [C1], "혼인건수는 …", question=Q27.question, subs=SUBS))
    births = next(s for s in v.subs if s["key"] == "births")
    assert births["expect"] == "answer" and births["observed"] == "missing"
    s = summarize([v])
    assert s["m2"]["coverage"]["n"] == 2                     # 기대 하위 질문 단위 분모 (missing 포함)


def test_expected_hold_births_is_not_operation_failure():
    """ViewSet 에 출생아수 행이 없음 → births 기대 hold. 보류 · 고지하면 Coverage 분모 제외, Operation · Execution N/A"""
    v = judge(Q27, run([MARR], [C1], "혼인건수는 … 출생아수 자료는 찾지 못했습니다.", question=Q27.question, subs=SUBS))
    births = next(s for s in v.subs if s["key"] == "births")
    assert births["expect"] == "hold" and births["completeness"] == "met"
    assert not [f for f in v.findings if f["sub_key"] == "births" and f["code"] in ("operation", "execution")]
    s = summarize([v])
    assert s["m2"]["coverage"]["n"] == 1 and s["m3"]["hold_recall"] == {"ok": 1, "n": 1, "rate": 1.0}
    assert v.verdict == "통과"


def test_extra_output_subquestion():
    q = Question.model_validate({**Q27.model_dump(), "sub_questions": [Q27.sub_questions[0].model_dump()]})
    res, extra = match(q, run([MARR, BIRTH], [C1, C2], "…", question=Q27.question, subs=SUBS))
    assert res[0].status == "matched" and len(extra) == 1


def test_ambiguous_match():
    q = Question.model_validate({**Q27.model_dump(), "sub_questions": [
        {"key": "x", "match": {"item_any": ["최근"]}, "m3": {"op": "raw"}}]})
    res, _ = match(q, run([MARR, BIRTH], [C1, C2], "…", question=Q27.question, subs=SUBS))
    assert res[0].status == "ambiguous_match"
