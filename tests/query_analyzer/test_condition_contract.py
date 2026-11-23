"""[NEW 11-20] KOS-26 — 조건식이 역할 단위 분리(split_roles)와 모듈 3 까지 보존되는가 (HCX 없음)

  어댑터(rag/query_analyzer)가 조건식 을 만드는 부분은 검색 모듈 담당 범위라 이 저장소에 반영하지 않았다.
  그 부분의 테스트는 docs/modules/KOS-26-query-analyzer-handoff/tests/ 에 있다. 여기서는 어댑터가 만든 것과 같은 모양의 입력을 직접 만들어 쓴다.
"""
from backend.agent.chart_calculate.planner import Decision, fixed_conditions, make_plan
from backend.agent.modules import split_roles, split_roles_linked
from backend.schemas.query import QueryBundle
from tests.chart_calculate._views import VID, view

THRESHOLD = {"field": "가구원수", "op": ">=", "value": "99000", "unit": "명", "text": "가구원수 99,000명 이상", "source": "threshold"}


def _bundle_with_role_unit():
    """어댑터가 만들 모양: 조건식 은 상위 filters 와 역할이 없는 본 질문에만 있고, 조건 조회 단위(역할=조건)에는 없다"""
    return {"query_id": "q1", "original": "q", "rewritten": "r", "intent": "값 조회",
            "filters": {"시점": [2000], "지표": ["가구수"], "조건식": [THRESHOLD]},
            "sub_questions": ["2000년 2인 가구수", "가구원수"],
            "sub_filters": [{"시점": [2000], "지표": ["가구수"], "조건식": [THRESHOLD]},
                            {"시점": [2000], "지표": ["가구원수"], "역할": "조건"}]}


def _units(qid):
    def unit(uid, rid):
        return {"unit_id": uid, "views": [{"record": {"id": rid}, "rank": 1}]}
    return {"query_id": qid, "units": [unit(f"{qid}-1", "view::main"), unit(f"{qid}-2", "view::cond")]}


def test_condition_survives_split_roles_and_the_link_records_what_the_unit_supported():
    vb = _bundle_with_role_unit()
    b, vi, extra, links = split_roles_linked(vb, _units("q1"))
    assert b["sub_questions"] == ["2000년 2인 가구수"] and [u["unit_id"] for u in vi["units"]] == ["q1-1"]
    assert b["sub_filters"][0]["조건식"][0]["field"] == "가구원수"          # 조건 조회 단위가 지워져도 본 질문에 남는다
    (link,) = links
    assert (link.unit_id, link.role, link.supports, link.record_ids) == ("q1-2", "조건", ["q1-1"], ["view::cond"])
    assert split_roles(vb, _units("q1"))[:2] == (b, vi)                     # 예전 3개 반환 함수는 그대로


def test_end_to_end_the_main_question_is_withheld_after_the_condition_unit_is_removed():
    """종단: split_roles → fixed_conditions → make_plan. 필터 연산이 없는 동안 제한받는 본 질문도 계산하지 않는다"""
    b, _, _, _ = split_roles_linked(_bundle_with_role_unit(), _units("q1"))
    bundle = QueryBundle.model_validate(b)
    assert fixed_conditions(bundle)["q1-1"]["조건식"][0]["op"] == ">="
    rec = view([["2000", "서울특별시", "가구수(가구)", 10.0]], ["시점", "행정구역별", "항목", "값"], unit="가구")
    dec = Decision.model_validate({"answers": [{"sub_question_id": "q1-1", "op": "raw", "operands": [
        {"record_id": VID, "item": "가구수(가구)", "select": {"시점": ["2000"]}}]}]})
    cp, _ = make_plan([], [rec], dec, bundle)
    assert cp.answer_steps == [] and cp.withheld and cp.withheld[0].sub_question_id == "q1-1"
    assert "조건부 집계는 아직 지원하지 않아" in cp.warnings[0]
