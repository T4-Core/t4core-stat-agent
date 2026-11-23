"""A0 기대 라벨은 하위 질문 보류 사유와 분리해 입력 스냅샷으로 정한다 (criteria.md 2.3)"""
from eval.generator.status import a0_label, expectations
from eval.generator.verdict import judge
from tests.eval_generator._fx import births, run, share_calc
from tests.eval_generator.test_eg_status import Q05

QA_NO_DATA = {"status": "stopped", "stopped_at": "A0", "issues": [{"point": "A0", "kind": "no_data", "severity": "error"}]}


def test_empty_records_share_question_is_stop_no_data_and_tp():
    r = run([], [], "요청한 지표를 찾지 못했습니다.", qa=QA_NO_DATA)
    r["modules"]["module3"]["calc_results"] = []
    label, subs = expectations(Q05, r)
    assert label == "stop_no_data"
    assert [(s.expect, s.hold_reason, s.source) for s in subs] == [("hold", "no_data", "a0")]   # missing_operand 가 아니다
    v = judge(Q05, r)
    assert (v.a0_expected, v.a0_observed) == ("stop_no_data", "stop_no_data")
    assert v.verdict == "통과"


def test_denominator_missing_is_continue_and_m3_hold():
    r = run([births(national=False)], [{**share_calc(), "value": None}], "전국 자료가 없어 비중을 계산하지 못했습니다.",
            withheld=[{"sub_question_id": "q1-1", "text": "분모로 쓸 총계 값이 없습니다"}], insufficient=True)
    assert a0_label(r) == "continue"
    v = judge(Q05, r)
    assert v.subs[0]["hold_reason"] == "missing_denominator" and v.subs[0]["completeness"] == "met"


def test_a0_stop_on_answerable_is_flagged():
    r = run([births()], [], "요청한 지표를 찾지 못했습니다.", qa=QA_NO_DATA)
    v = judge(Q05, r)
    assert v.a0_expected == "continue" and v.a0_observed == "stop_no_data" and "QA" in v.first_failure


def test_unknown_indicator_but_item_in_record_is_continue():
    r = run([births()], [share_calc()], "…", notes=["[지표] '출생아수' 를 CSV·사전에서 찾지 못함"])
    r["viewset"]["units"] = [{"filters": {"지표": ["출생아수"]}}]
    assert a0_label(r) == "continue"


def test_unknown_indicator_absent_everywhere_is_stop():
    r = run([births()], [], "…", notes=["[지표] '등록대수' 를 CSV·사전에서 찾지 못함"])
    r["viewset"]["units"] = [{"filters": {"지표": ["등록대수"]}}]
    assert a0_label(r) == "stop_indicator_not_found"


def test_status_not_ok_is_stop_status():
    r = run([births()], [], "…")
    r["viewset"]["status"] = "needs_selection"
    assert a0_label(r) == "stop_status"
