"""[NEW 11-20] KOS-26 A-0 — 조건의 열·연산자·값이 질의 분석 → 모듈 3 까지 보존되는가 (HCX 없음)

  이전: '가구원수>=5' 가 어댑터에서 검색어 '5' 가 되어 연산자와 열 이름이 사라졌고, thresholds 는 QueryBundle 에 오지 않았다.
"""
from backend.agent.chart_calculate.planner import Decision, fixed_conditions, make_plan
from backend.agent.modules import split_roles, split_roles_linked
from backend.rag.query_analyzer.adapter import parse_condition, threshold_conditions, to_view_bundle, to_view_filters
from backend.schemas.query import QueryBundle
from tests.chart_calculate._views import VID, view

THRESHOLD = {"말": "가구원수", "값": 99000, "단위": "명", "비교": "이상", "op": ">=", "표기": "99,000명 이상", "지역_고르기": True}


def test_condition_strings_keep_field_operator_value_and_unit():
    assert parse_condition("혼인상태=미혼") == {"field": "혼인상태", "op": "=", "value": "미혼", "unit": None, "text": "혼인상태=미혼", "source": "slot"}
    c = parse_condition("가구원수 >= 99,000명")
    assert (c["field"], c["op"], c["value"], c["unit"]) == ("가구원수", ">=", "99000", "명")
    assert parse_condition("보증부월세")["field"] is None and parse_condition("보증부월세")["value"] == "보증부월세"


def test_comparison_value_is_not_sent_to_search_as_a_word():
    out = to_view_filters({"조건": ["가구원수>=5", "혼인상태=미혼"]})
    assert out["조건"] == ["미혼"]                              # 이전: ['5', '미혼']
    assert [(c["field"], c["op"], c["value"]) for c in out["조건식"]] == [("가구원수", ">=", "5"), ("혼인상태", "=", "미혼")]


def test_cohort_condition_still_becomes_birth_years():
    out = to_view_filters({"조건": ["출생연도=1983년생"]})
    assert out["출생연도"] == [1983] and "조건식" not in out


def test_thresholds_become_conditions_and_only_comparisons_are_kept():
    assert threshold_conditions([THRESHOLD, {"말": "x", "값": 1, "op": "초과"}]) == [
        {"field": "가구원수", "op": ">=", "value": "99000", "unit": "명", "text": "가구원수 99,000명 이상", "source": "threshold"}]


def _bundle_with_role_unit():
    rb = {"original": "q", "rewritten": "r", "intent": "값 조회", "filters": {"시점": ["2000년"], "지표": ["가구수"]},
          "sub_questions": ["2000년 2인 가구수"], "sub_filters": [{"시점": ["2000년"], "지표": ["가구수"]}]}
    vb, _ = to_view_bundle(rb, "q1", thresholds=[THRESHOLD])
    # roles.add_role_units 가 맨 뒤에 붙이는 조건 조회 단위와 같은 모양
    vb["sub_questions"].append("가구원수")
    vb["sub_filters"].append({"시점": [2000], "지표": ["가구원수"], "역할": "조건"})
    return vb


def test_threshold_goes_to_the_main_question_not_to_the_condition_lookup_unit():
    vb = _bundle_with_role_unit()
    assert vb["filters"]["조건식"][0]["value"] == "99000" and vb["sub_filters"][0]["조건식"][0]["op"] == ">="
    assert "조건식" not in vb["sub_filters"][1]


def _units(qid):
    def unit(uid, rid):
        return {"unit_id": uid, "views": [{"record": {"id": rid}, "rank": 1}]}
    return {"query_id": qid, "units": [unit(f"{qid}-1", "view::main"), unit(f"{qid}-2", "view::cond")]}


def test_condition_survives_split_roles_and_the_link_records_what_the_unit_supported():
    vb = _bundle_with_role_unit()
    vb["query_id"] = "q1"
    b, vi, extra, links = split_roles_linked(vb, _units("q1"))
    assert b["sub_questions"] == ["2000년 2인 가구수"] and [u["unit_id"] for u in vi["units"]] == ["q1-1"]
    assert b["sub_filters"][0]["조건식"][0]["field"] == "가구원수"          # 조건 조회 단위가 지워져도 본 질문에 남는다
    (link,) = links
    assert (link.unit_id, link.role, link.supports, link.record_ids) == ("q1-2", "조건", ["q1-1"], ["view::cond"])
    assert split_roles(vb, _units("q1"))[:2] == (b, vi)                     # 예전 3개 반환 함수는 그대로


def test_end_to_end_the_main_question_is_withheld_after_the_condition_unit_is_removed():
    """종단: 어댑터 → split_roles → fixed_conditions → make_plan. 필터 연산이 없는 동안 제한받는 본 질문도 계산하지 않는다"""
    vb = _bundle_with_role_unit()
    vb["query_id"] = "q1"
    b, _, _, _ = split_roles_linked(vb, _units("q1"))
    bundle = QueryBundle.model_validate(b)
    assert fixed_conditions(bundle)["q1-1"]["조건식"][0]["op"] == ">="
    rec = view([["2000", "서울특별시", "가구수(가구)", 10.0]], ["시점", "행정구역별", "항목", "값"], unit="가구")
    dec = Decision.model_validate({"answers": [{"sub_question_id": "q1-1", "op": "raw", "operands": [
        {"record_id": VID, "item": "가구수(가구)", "select": {"시점": ["2000"]}}]}]})
    cp, _ = make_plan([], [rec], dec, bundle)
    assert cp.answer_steps == [] and cp.withheld and cp.withheld[0].sub_question_id == "q1-1"
    assert "조건부 집계는 아직 지원하지 않아" in cp.warnings[0]
