"""Oracle 요청 (계획 2.4.2, D-13 · D-24) · 실행 기록 (D-19)"""
import copy

from eval.generator.run import M3_FIELDS_FOR_M6, Recorder, assemble_result, oracle_request, run_generator
from eval.generator.subq import has_value
from tests.eval_generator._fx import births, share_calc

M6_REQ = {"query_bundle": {"query_id": "q1", "original": "x"}, "records": [births()], "calc_results": [share_calc(same_row=True)],
          "displays": {"d1": {"source_unit": "%", "display_unit": "%", "unit_scale": 1, "digits": None}}, "answer_steps": [],
          "plan_warnings": ["w"], "withheld": [], "role_links": [{"unit_id": "q1-2", "role": "분모", "supports": ["q1-1"]}], "max_rows": 40}
VERIFIED = {"calc_results": [share_calc()], "displays": {"d1": {"source_unit": "%", "display_unit": "%", "unit_scale": 1, "digits": 1}},
            "chart_plan": {"answer_steps": [{"step_id": "a1", "op": "share", "from_": "2024"}], "warnings": [], "withheld": []}}


def test_oracle_swaps_only_m3_fields():
    orig = copy.deepcopy(M6_REQ)
    out = oracle_request(M6_REQ, VERIFIED)
    assert M6_REQ == orig                                            # 원본 그대로
    changed = {k for k in out if out[k] != M6_REQ.get(k)}
    assert changed <= set(M3_FIELDS_FOR_M6)
    for k in ("query_bundle", "records", "role_links", "max_rows"):
        assert out[k] == M6_REQ[k]
    assert out["calc_results"][0]["unit"] == "%" and out["calc_results"][0]["value"] > 1   # 평가 정규형(ratio)을 넣지 않는다
    assert out["answer_steps"][0]["from"] == "2024" and "from_" not in out["answer_steps"][0]   # Module6Request 와 같은 별칭


def test_a0_stop_does_not_call_modules():
    """records 가 빈 ViewSet → QA A0 no_data 중단. 기록 래퍼의 모듈 2~6 호출 0회, 최종 result 는 qa.message"""
    vs = {"status": "ok", "query_id": "q1", "original": "2024년 서울 출생아 비중", "units": [], "records": [],
          "view_bundle": {"query_id": "q1", "original": "2024년 서울 출생아 비중"}}
    rec = Recorder()
    mods = run_generator(vs, {"status": "ok", "notes": []}, qa=True, draw=False, max_rows=40, rec=rec)
    assert mods["qa"]["stopped_at"] == "A0" and not rec.attempts
    result = assemble_result(mods, vs)
    assert result["answer"] == mods["qa"]["message"]


def test_has_value():
    assert has_value(share_calc()) and not has_value({**share_calc(), "value": None})
