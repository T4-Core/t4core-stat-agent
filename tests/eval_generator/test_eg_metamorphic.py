"""MT-3a: 입력 · 결과 · displays · 원본 Record 행을 함께 바꾼 정합 사례"""
import copy

from backend.agent.answer_compose.facts import Facts
from backend.agent.answer_compose.tables import build_tables
from backend.schemas.answer import Module6Request
from eval.generator.metamorphic import consistency, mt3a_request, recompute

REC = {"id": "r", "lexical_text": "", "parent_id": "table::x", "metadata": {"unit": "건"},
       "table": {"columns": ["시점", "항목", "값"], "rows": [["2021", "혼인건수(건)", 100.0], ["2025", "혼인건수(건)", 120.0]]}}


def request():
    calc = {"step_id": "a1", "op": "growth_rate", "value": 20.0, "unit": "%", "display_ref": "d1", "record_ids": ["r"],
            "inputs": [{"role": "value", "record_id": "r", "item": "혼인건수(건)", "key": {"시점": "2021"}, "value": 100.0, "unit": "건"},
                       {"role": "value", "record_id": "r", "item": "혼인건수(건)", "key": {"시점": "2025"}, "value": 120.0, "unit": "건"}]}
    return {"query_bundle": {"query_id": "q", "original": "혼인건수 증감률", "rewritten": "혼인건수 증감률"}, "records": [REC],
            "calc_results": [calc], "displays": {"d1": {"source_unit": "%", "display_unit": "%", "unit_scale": 1, "digits": 1}},
            "answer_steps": [{"step_id": "a1", "op": "growth_rate", "operands": [{"record_id": "r", "item": "혼인건수(건)",
                                                                                 "measure": "raw", "select": {}}]}]}


def test_recompute_is_not_symmetric():
    assert recompute("growth_rate", 100, 120) == 20.0
    assert round(recompute("growth_rate", 120, 100), 4) == -16.6667      # 절댓값이 같다고 기대하지 않는다


def test_variant_updates_inputs_result_and_record_rows():
    orig = request()
    snapshot = copy.deepcopy(orig)
    var, why = mt3a_request(orig)
    assert why == "ok" and orig == snapshot                               # 원본 요청은 그대로 (깊은 복사)
    c = var["calc_results"][0]
    assert [i["value"] for i in c["inputs"]] == [120.0, 100.0]
    assert round(c["value"], 2) == -16.67
    assert [r[2] for r in var["records"][0]["table"]["rows"]] == [120.0, 100.0]   # 근거 행도 같이 바뀐다
    assert consistency(var) == []


def test_tables_follow_variant_direction():
    """변형 요청으로 만든 계산 요약 표와 원본 View 표가 같은 방향(120 → 100)이다"""
    var, _ = mt3a_request(request())
    tables = build_tables(Facts(Module6Request.model_validate(var)))
    view = next(t for t in tables if t.kind == "view")
    summary = next(t for t in tables if t.kind == "calc_summary")
    assert [r[-1] for r in view.raw_rows] == [120.0, 100.0]
    assert summary.raw_rows[0][2] == [120.0, 100.0]                    # 계산 요약의 입력값도 같은 방향


def test_consistency_detects_result_only_flip():
    """결과만 바꾼 모순 입력 (FI-CONTRA 와 같은 변이) 은 정합성 검사에서 걸린다"""
    req = request()
    req["calc_results"][0]["value"] = -20.0
    assert consistency(req)


def test_unresolved_row_is_skipped():
    req = request()
    req["records"][0]["table"]["rows"].append(["2021", "혼인건수(건)", 100.0])   # 같은 값 행이 둘 → 특정 불가
    var, why = mt3a_request(req)
    assert var is None and why == "unresolved_row"
