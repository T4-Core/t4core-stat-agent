"""[NEW 11-18] 전체 파이프라인 테스트(질문 34개, 실제 HCX)에서 나온 모듈 6 항목의 회귀 테스트
  - Q01 '2025년 서울 인구는?' 에 View 가 장래인구추계 표를 골라 추계값을 실제 인구처럼 답함 → 근거 표가 추계이면 답변에 밝힌다
  - 단위가 천명이면 답변도 '934만 명'
"""
import pytest

from backend.agent.answer_compose.caveats import build_caveats
from backend.agent.answer_compose.facts import Facts
from backend.agent.answer_compose.pipeline import run_module6
from backend.agent.chart_calculate.calculate import run_answer_steps
from backend.schemas.answer import Module6Request
from backend.schemas.chart import Step
from tests.answer_compose._data import BUNDLE
from tests.chart_calculate._views import VID, view


def _no_hcx(*a, **k):
    raise RuntimeError("HCX 없음")


def answer_for(item, value, unit_meta="", **meta):
    v = view([["2025", "서울특별시", item, value]], ["시점", "행정구역별", "항목", "값"], unit=unit_meta, **meta)
    st = Step.model_validate({"step_id": "a1", "op": "raw", "operands": [
        {"role": "value", "record_id": VID, "item": item, "select": {"행정구역별": ["서울특별시"]}}]})
    r = run_answer_steps([st], [v])[0]
    from backend.agent.chart_calculate.planner import Decision, make_plan  # noqa: F401  (표시 설정은 계획 단계가 정한다)
    req = Module6Request(query_bundle=BUNDLE, records=[v], calc_results=[r], displays={}, answer_steps=[st])
    return v, req, run_module6(req, chat=_no_hcx)


def test_answer_shows_man_myeong_for_a_cheon_myeong_table():
    _, _, out = answer_for("인구(천명)", 9340.0)
    assert "934만 명" in out.answer and "9,340천명" not in out.answer


@pytest.mark.parametrize("survey", ["장래인구추계", "장래가구추계", "인구 전망", "출산율 예측"])
def test_projection_table_is_stated_in_the_answer(survey):
    v, req, out = answer_for("인구(천명)", 9340.0, survey_nm=survey)
    texts = [c.text for c in build_caveats(Facts(req))]
    assert any("추계" in t or "전망" in t or "예측" in t for t in texts) and any(survey in t for t in texts)
    assert "실제" in out.answer.split("※", 1)[1]                    # 템플릿 답변의 ※ 줄에 들어간다


@pytest.mark.parametrize("survey", ["주민등록인구통계", "인구동향조사", ""])
def test_ordinary_tables_get_no_projection_notice(survey):
    v, req, out = answer_for("인구(천명)", 9340.0, survey_nm=survey)
    assert not [c for c in build_caveats(Facts(req)) if "추계" in c.text or "전망" in c.text]


def test_projection_notice_is_given_once_even_if_many_calculations_use_the_table():
    v = view([["2025", "서울특별시", "인구(천명)", 9340.0], ["2025", "부산광역시", "인구(천명)", 3300.0]],
             ["시점", "행정구역별", "항목", "값"], survey_nm="장래인구추계")
    steps = [Step.model_validate({"step_id": f"a{i}", "op": "raw", "operands": [
        {"role": "value", "record_id": VID, "item": "인구(천명)", "select": {"행정구역별": [reg]}}]})
        for i, reg in enumerate(["서울특별시", "부산광역시"], 1)]
    res = run_answer_steps(steps, [v])
    req = Module6Request(query_bundle=BUNDLE, records=[v], calc_results=res, displays={}, answer_steps=steps)
    assert len([c for c in build_caveats(Facts(req)) if "추계" in c.text]) == 1


# ── [11-18] F14 · F15: 문장 검사 ──────────────────────────────────
def share_facts(n=5):
    from backend.agent.answer_compose import placeholder  # noqa: F401
    pts = [{"key": {"시점": str(2021 + i)}, "value": 17.0 + i} for i in range(n)]
    from backend.schemas.chart import CalcResult
    r = CalcResult.model_validate({"step_id": "a1", "op": "share", "value": pts, "unit": "%", "display_ref": "d1", "record_ids": [VID]})
    v = view([[p["key"]["시점"], "서울특별시", "출생아수", 1.0] for p in pts], ["시점", "행정구역별", "항목", "값"])
    return Facts(Module6Request(query_bundle=BUNDLE, records=[v], calc_results=[r],
                                displays={"d1": {"source_unit": "%", "display_unit": "%", "unit_scale": 1}}))


def test_f14_name_slot_after_vs_is_rejected_when_it_holds_the_point_key():
    from backend.agent.answer_compose import placeholder
    f = share_facts()
    bad = "2021년에는 {a1.r0}로 전국 대비 {a1.r0.key}였습니다."
    assert any("대비" in p for p in placeholder.check(bad, placeholder.fill(bad, f), f, []))
    ok = "2021년 서울의 비중은 {a1.r0}로 전국 대비 수치입니다. {a1.r1} {a1.r2} {a1.r3} {a1.r4}"
    assert not any("대비" in p for p in placeholder.check(ok, placeholder.fill(ok, f), f, []))


def test_f15_listing_only_the_first_part_without_saying_what_was_left_out_is_rejected():
    from backend.agent.answer_compose import placeholder
    f = share_facts(8)
    cut = " ".join(f"{{a1.r{i}}}" for i in range(5))
    assert any("5개만 서술" in p for p in placeholder.check(cut, placeholder.fill(cut, f), f, []))


def test_f15_exact_omission_count_with_a_pointer_to_the_table_passes_and_a_wrong_count_does_not():
    from backend.agent.answer_compose import placeholder
    f = share_facts(8)
    head = " ".join(f"{{a1.r{i}}}" for i in range(5))
    right = head + " 외 3개는 아래 표에 있습니다."
    wrong = head + " 외 2개는 아래 표에 있습니다."
    no_table = head + " 외 3개입니다."
    assert not any("서술함" in p for p in placeholder.check(right, placeholder.fill(right, f), f, []))
    assert any("서술함" in p for p in placeholder.check(wrong, placeholder.fill(wrong, f), f, []))
    assert any("서술함" in p for p in placeholder.check(no_table, placeholder.fill(no_table, f), f, []))


def test_f15_picking_specific_points_is_not_treated_as_a_cut_listing():
    from backend.agent.answer_compose import placeholder
    f = share_facts(5)
    pick = "처음 {a1.r0} 에서 마지막 {a1.r4} 로 바뀌었습니다."
    assert not any("서술함" in p for p in placeholder.check(pick, placeholder.fill(pick, f), f, []))


# ── [검토 7·8] 전체 check 결과로 확인 ───────────────────────────────
def test_review7_correct_omission_notice_passes_the_whole_check_and_a_bare_first_value_does_not():
    from backend.agent.answer_compose import placeholder
    f = share_facts(5)
    ok2 = "{a1.r0} {a1.r1} {a1.r2} {a1.r3} {a1.r4}"
    assert placeholder.check(ok2, placeholder.fill(ok2, f), f, []) == []
    bare = "처음 값은 {a1.r0} 입니다."
    assert any("서술함" in p for p in placeholder.check(bare, placeholder.fill(bare, f), f, []))


def test_review7_omission_count_is_not_reported_as_a_stray_quantity():
    from backend.agent.answer_compose import placeholder
    f = share_facts(5)
    t = "{a1.r0} 와 {a1.r1} 입니다. 외 3개는 아래 표에 있습니다."
    problems = placeholder.check(t, placeholder.fill(t, f), f, [])
    assert not any("직접 씀" in p or "서술함" in p for p in problems)


def test_review8_region_key_after_vs_is_accepted_for_diff_and_for_regional_share():
    from backend.agent.answer_compose import placeholder
    from backend.schemas.chart import CalcResult
    pts = [{"key": {"시군구별": "부산광역시"}, "value": 5000000.0}]
    r = CalcResult.model_validate({"step_id": "a1", "op": "diff", "value": pts, "unit": "명", "display_ref": "d1", "record_ids": [VID]})
    v = view([["2024", "부산광역시", "인구", 1.0]], ["시점", "시군구별", "항목", "값"])
    f = Facts(Module6Request(query_bundle=BUNDLE, records=[v], calc_results=[r],
                             displays={"d1": {"source_unit": "명", "display_unit": "명", "unit_scale": 1}}))
    t = "서울 대비 {a1.r0.key} 의 인구 차이는 {a1.r0} 입니다."
    assert not any("대비" in p for p in placeholder.check(t, placeholder.fill(t, f), f, []))


# ── 평균이 소수를 유지하는 규칙은 환산하지 않는 단위로 시험한다 (천명은 만 명으로 환산되어 이 규칙을 가린다) ──
def test_mean_of_integers_keeps_its_fraction_in_a_non_converted_unit():
    v = view([["2025", "서울", "가구(천가구)", 50.0], ["2025", "부산", "가구(천가구)", 51.0]], ["시점", "행정구역별", "항목", "값"])
    sel = {"행정구역별": ["서울", "부산"]}
    st = Step.model_validate({"step_id": "a1", "op": "aggregate", "agg": "mean", "operands": [
        {"role": "value", "record_id": VID, "item": "가구(천가구)", "select": sel}]})
    r = run_answer_steps([st], [v])[0]
    out = run_module6(Module6Request(query_bundle=BUNDLE, records=[v], calc_results=[r], displays={}, answer_steps=[st]), chat=_no_hcx)
    assert r.value == 50.5 and "50.5천가구" in out.answer          # '51천가구' 로 반올림하지 않는다
