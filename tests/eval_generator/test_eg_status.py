"""판정 절차: 0단계 범위 · 1단계 출력 정확성 · 2단계 완전성 (계획 2.3.1, D-10 · D-14)"""
from eval.generator.schema import Question
from eval.generator.verdict import judge
from tests.eval_generator._fx import births, run, share_calc

Q05 = Question.model_validate({
    "id": "Q05", "question": "2024년 전국 대비 서울 출생아 비중은?", "scope": "in",
    "sub_questions": [{"key": "share", "match": {"item_any": ["출생아수"], "op_any": ["share"]},
                       "answerable_when": [
                           {"when": {"operands_valid": {"operands": [{"region": "서울", "period": "2024", "item": "출생아수"}],
                                                        "denominator": {"region": "전국", "period": "2024", "item": "출생아수"}}},
                            "expect": "answer"},
                           {"expect": "hold", "hold_reason": "from_predicate"}],
                       "m3": {"op": "share"},
                       "values": [{"role": "FINAL", "value": 0.17458, "unit": "ratio", "binding": {"region": "서울", "period": "2024"},
                                   "atol": 0.0001}]}]})
Q29 = Question.model_validate({"id": "Q29", "question": "오늘 날씨 어때?", "scope": "out"})
Q27 = Question.model_validate({
    "id": "Q27", "question": "최근 5년 혼인건수와 출생아수 추이", "scope": "in",
    "sub_questions": [
        {"key": "marriage", "match": {"item_any": ["혼인건수"]}, "m3": {"op": "raw"},
         "values": [{"role": "FINAL", "value": 192507, "unit": "건", "key": {"시점": "2021"}}]},
        {"key": "births", "match": {"item_any": ["출생아수"]}, "m3": {"op": "raw"}}]})


def test_q05_answer_passes():
    v = judge(Q05, run([births()], [share_calc()], "2024년 서울의 출생아 비중은 전국 대비 17.5%입니다."))
    assert (v.expected, v.verdict) == ("answer", "통과"), v.findings


def test_q05_national_only_hold_is_correct():
    """전국 행만 있음 → 기대 hold(missing_operand). 사유를 밝히고 보류하면 False-hold 가 아니라 충족"""
    calc = {**share_calc(), "value": None, "note": "조건에 맞는 값이 없음"}
    r = run([births(seoul=False)], [calc], "서울 자료가 없어 비중을 계산하지 못했습니다.",
            withheld=[{"sub_question_id": "q1-1", "text": "서울 자료가 없어 계산하지 못했습니다"}], insufficient=True)
    v = judge(Q05, r)
    assert v.expected == "hold" and v.subs[0]["hold_reason"] == "missing_operand"
    assert v.verdict == "통과"


def test_q05_hold_expected_but_ungrounded_100_percent_fails():
    """기대 hold(전국 행 없음)인데 분모 = 부분과 같은 행으로 100.0% (기준선 Q05 1회차) → 1단계 미달"""
    r = run([births(national=False)], [share_calc(same_row=True)], "2024년 서울의 출생아 비중은 전국 대비 100.0%입니다.")
    v = judge(Q05, r)
    assert v.expected == "hold" and v.verdict == "미달"
    assert any(f["code"] == "hold_but_value" and f["ok"] is False for f in v.findings)


def test_q29_out_of_scope_passes_and_skips_module_metrics():
    r = {"id": "Q29", "run": 1, "ok": True, "analysis": {"status": "out_of_scope"}, "modules": None,
         "result": {"answer": "통계 수치를 묻는 질문이 아니어서 …"}}
    v = judge(Q29, r)
    assert v.verdict == "통과" and v.subs == [] and "no_viewset" in v.tags


def test_in_scope_question_sent_out_of_scope_is_scope_error_not_pass():
    r = {"id": "Q27", "run": 1, "ok": True, "analysis": {"status": "out_of_scope"}, "modules": None,
         "result": {"answer": "이 질문은 통계 수치를 묻는 질문이 아니어서 …"}}
    v = judge(Q27, r)
    assert v.verdict == "보류" and "scope_error:false_out" in v.tags and v.first_failure == ["M1+R"]


def test_wrong_value_with_notified_omission_is_fail_not_hold():
    """Q27: 혼인건수 값이 틀리고 출생아수 누락을 고지 → 상태 조합과 관계없이 1단계 미달 (0.6장 #2)"""
    rec = {"id": "r", "table": {"columns": ["시점", "항목", "값"], "rows": [["2021", "혼인건수(건)", 192507.0]]},
           "metadata": {"unit": "건"}}
    calc = {"step_id": "a1", "sub_question_id": "q1-1", "op": "raw", "value": [{"key": {"시점": "2021"}, "value": 99999.0}],
            "unit": "건", "display_ref": "d1", "inputs": [{"role": "value", "record_id": "r", "item": "혼인건수(건)",
                                                         "key": {"시점": "2021"}, "value": 99999.0}], "record_ids": ["r"]}
    r = run([rec], [calc], "2021년 혼인건수는 99,999건입니다. 출생아수 자료는 찾지 못했습니다.",
            question=Q27.question, subs=["최근 5년 혼인건수", "최근 5년 출생아수"])
    v = judge(Q27, r)
    assert v.verdict == "미달"
    assert any(f["code"] == "execution" and f["ok"] is False for f in v.findings)
