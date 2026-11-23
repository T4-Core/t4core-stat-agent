"""QA Fault Injection (형식) · FI-SEM (내용 경고) · FI-CONTRA (계획 2.7, D-20)"""
from eval.generator.faults import contra_injection, fault_injection, mutants, semantic_injection
from eval.generator.verdict import judge
from tests.eval_generator._fx import births, run, share_calc
from tests.eval_generator.test_eg_status import Q05


def _run():
    r = run([births()], [share_calc()], "2024년 서울의 출생아 비중은 전국 대비 17.5%입니다.")
    r["modules"]["charts"] = [{"chart_id": "c1", "sub_question_ids": ["q1-1"], "chart_type": "bar", "measure": "share",
                               "view_ids": [births()["id"]]}]
    r["modules"]["chart_plan"] = {"query_id": "q1", "charts": r["modules"]["charts"], "overlays": []}
    return r


def test_clean_has_no_error_and_mutants_detected():
    res = fault_injection([_run()])["summary"]
    assert res["false_alarm_rate"] == 0.0
    assert res["detection_recall"] == 1.0, res["misses"]
    assert res["severity_correct"] == 1.0, res["misses"]


def test_new_ref_mutants_created_when_fields_exist():
    r = _run()
    r["modules"]["module3"]["chart_plan"]["withheld"] = [{"sub_question_id": "q1-1", "text": "x"}]
    codes = {(m.code, m.path) for m in mutants(r)}
    assert ("F-NEWREF", "calc_results.0.sub_question_id") in codes
    assert ("F-NEWREF", "chart_plan.withheld.0.sub_question_id") in codes


def test_semantic_injection_is_deterministic_and_detected():
    s = semantic_injection([_run()])["summary"]
    for kind in ("chart_answer_mismatch", "value_list", "answer_caveat_conflict"):
        assert s[kind]["recall"] == 1.0, (kind, s[kind])


def test_contra_not_in_qa_format_recall():
    """비중 > 100% 같은 값 의미 모순은 형식 검사 범위 밖이다 → 형식 검사 지표가 아니라 별도 기록"""
    rows = contra_injection([_run()])["rows"]
    assert rows and all(r["qa_format"] == "none" for r in rows)


def test_semantic_warning_and_stage1_fail_is_known_but_shipped():
    r = run([births(national=False)], [share_calc(same_row=True)], "2024년 서울의 출생아 비중은 전국 대비 100.0%입니다.",
            qa={"status": "warned", "issues": [{"kind": "answer_caveat_conflict", "severity": "warning"}]})
    v = judge(Q05, r, {"tags": "held_value_asserted"})
    row = next(d for d in v.detectors if d["kind"] == "answer_caveat_conflict")
    assert row == {"kind": "answer_caveat_conflict", "warned": True, "label": True, "known_but_shipped": True}
