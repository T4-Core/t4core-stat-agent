"""[NEW 11-20] KOS-38 — Linear 버그 리포트 수정 모듈 6 회귀 테스트 (HCX 는 가짜 함수)

  A-5  보류 범위(withheld) · 결과 역할(요청 · 독립 · 보조 · 대체): 보류된 요청을 대신하는 값만 '참고로', 독립 하위 질문의 결과는 정식 답
  A-7  계산 없음 문구 · 근거 표 · 긴 목록 요약
"""
from backend.agent.answer_compose.caveats import build_caveats
from backend.agent.answer_compose.facts import Facts
from backend.agent.answer_compose.graph import NO_CALC_ANSWER
from backend.agent.answer_compose.pipeline import run_module6
from backend.schemas.answer import Module6Request
from backend.schemas.chart import CalcResult, Display, Withheld
from backend.schemas.query import QueryBundle, RoleLink
from tests.answer_compose._data import fake, inp, request
from tests.chart_calculate._views import VID, view

DISPLAYS = {"d1": Display(source_unit="가구", display_unit="가구"), "d2": Display(source_unit="건", display_unit="건")}
BUNDLE = QueryBundle(query_id="q", original="질문", sub_questions=["비율", "개수"], filters={"지표": ["가구수"]})
HELD = "비중의 분모로 쓸 자료가 이 질문에 정해진 자료가 아니라서 비중을 계산하지 못했습니다."


def raw(step_id, sub, value, item="보증부월세(가구)", rid=VID, unit="가구", year="1990"):
    return CalcResult(step_id=step_id, sub_question_id=sub, op="raw", value=value, unit=unit, display_ref="d1", record_ids=[rid],
                      inputs=[inp(year, value, item=item, rid=rid, unit=unit)])


def req(results, withheld=(), links=(), **kw):
    return Module6Request(query_bundle=BUNDLE, records=[view()], calc_results=results, displays=DISPLAYS,
                          withheld=list(withheld), role_links=list(links), **kw)


def held(sub="q-1", text=HELD):
    return Withheld(sub_question_id=sub, op="share", text=text)


# ── 역할 ─────────────────────────────────────────────────────────
def test_result_of_the_withheld_sub_question_is_a_substitute_and_other_sub_questions_are_independent():
    f = Facts(req([raw("a1", "q-1", 1404.0), raw("a2", "q-2", 7.0)], [held("q-1")]))
    assert [f.role_of(r) for r in f.req.calc_results] == ["대체", "독립"]


def test_without_withheld_or_sub_question_id_every_result_is_a_request():
    assert [Facts(req([raw("a1", "q-1", 1.0)])).role_of(r) for r in req([raw("a1", "q-1", 1.0)]).calc_results] == ["요청"]
    f = Facts(req([raw("a1", None, 1.0)], [held()]))
    assert f.role_of(f.req.calc_results[0]) == "요청"


def test_role_unit_result_supporting_only_withheld_questions_is_a_substitute_otherwise_an_aid():
    link = RoleLink(unit_id="q-3", role="분모", supports=["q-1"], record_ids=["view::den"])
    r = raw("a3", "q-3", 43799.0, rid="view::den")
    assert Facts(req([r], [held("q-1")], [link])).role_of(r) == "대체"
    wide = link.model_copy(update={"supports": ["q-1", "q-2"]})
    assert Facts(req([r], [held("q-1")], [wide])).role_of(r) == "보조"


# ── 답변 ─────────────────────────────────────────────────────────
def test_template_says_why_first_and_introduces_the_substitute_as_a_reference():
    out = run_module6(req([raw("a1", "q-1", 1404.0)], [held()]), chat=fake({"answer": "{a1}"}, {"answer": "{a1}"}))
    lines = out.answer.split("\n")
    assert lines[0].startswith(HELD) and "참고로" in lines[0] and "1,404가구" in lines[0]
    assert lines[0].index(HELD) < lines[0].index("참고로")
    assert not any(l == f"※ {HELD}" for l in lines)           # 본문이 이미 말한 사유를 ※ 줄로 되풀이하지 않는다
    assert any(c.ref == "q-1" and c.text == HELD for c in out.caveats)


def test_independent_result_keeps_a_plain_sentence_and_the_withheld_reason_stays_a_caveat():
    out = run_module6(req([raw("a2", "q-2", 7.0)], [held("q-1")]), chat=fake({"answer": "{a2}"}, {"answer": "{a2}"}))
    assert "참고로" not in out.answer and "7가구" in out.answer
    assert [(c.ref, c.text) for c in out.caveats if c.source == "plan_warning"] == [("q-1", HELD)]


def test_legacy_input_without_withheld_is_unchanged():
    out = run_module6(request(plan_warnings=["예전 사유"]), chat=fake({"answer": "혼인건수는 {a1.in0.key} {a1.in0}에서 {a1.in1.key} {a1.in1}으로 {a1.abs} 증가했습니다."}))
    assert "참고로" not in out.answer and [(c.ref, c.text) for c in out.caveats] == [("plan", "예전 사유")]


def test_hcx_prompt_marks_the_substitute_and_a_draft_without_a_reference_word_is_rejected():
    chat = fake({"answer": "보증부월세는 {a1}입니다."}, {"answer": "비중을 계산하지 못했습니다. 참고로 보증부월세는 {a1}입니다."})
    out = run_module6(req([raw("a1", "q-1", 1404.0)], [held()]), chat=chat)
    assert "참고 결과" in chat.calls[0][1]["content"] and "참고 결과" in chat.calls[0][0]["content"]
    assert out.method == "hcx_retry" and "참고 결과(a1)" in out.notes[0]


# ── 계산 없음 ────────────────────────────────────────────────────
def test_no_calc_answer_names_the_indicator_that_was_not_found_and_drops_unrelated_tables():
    text = "요청한 지표(자동차 등록대수)가 이 표에 없어 계산하지 못했습니다 (표의 항목: 세대수)."
    bundle = BUNDLE.model_copy(update={"filters": BUNDLE.filters.model_copy(update={"지표": ["자동차 등록대수"]})})
    out = run_module6(Module6Request(query_bundle=bundle, records=[view()], calc_results=[], withheld=[held(None, text)]), chat=fake())
    assert out.answer.startswith("받은 자료에서 자동차 등록대수를 확인하지 못했습니다.") and NO_CALC_ANSWER not in out.answer
    assert out.tables == [] and out.method == "none"


def test_no_calc_answer_without_a_reason_keeps_the_old_sentence_and_view_table():
    out = run_module6(request(results=[]), chat=fake())
    assert out.answer == NO_CALC_ANSWER and [t.kind for t in out.tables] == ["view"]


# ── 긴 목록 ──────────────────────────────────────────────────────
def test_long_list_is_summarized_by_code_instead_of_listing_the_first_few():
    pts = [{"key": {"행정구역별": f"지역{n}"}, "value": float(n)} for n in range(1, 177)]
    r = CalcResult(step_id="a1", op="raw", value=pts, unit="가구", display_ref="d1", record_ids=[VID],
                   inputs=[inp("2000", 1.0, item="가구수(가구)", unit="가구")])
    out = run_module6(req([r]), chat=fake({"answer": "{a1.r0}"}, {"answer": "{a1.r0}"}))
    assert "176개 중 가장 큰 값은 지역176 176가구, 가장 작은 값은 지역1 1가구" in out.answer and "외 " not in out.answer
    assert "표에서 확인" in out.answer


def test_list_up_to_the_citation_limit_is_still_listed():
    pts = [{"key": {"행정구역별": f"지역{n}"}, "value": float(n)} for n in range(1, 9)]
    r = CalcResult(step_id="a1", op="raw", value=pts, unit="가구", display_ref="d1", record_ids=[VID],
                   inputs=[inp("2000", 1.0, item="가구수(가구)", unit="가구")])
    out = run_module6(req([r]), chat=fake({"answer": "{a1.r0}"}, {"answer": "{a1.r0}"}))
    assert "외 3개" in out.answer and "가장 큰 값은" not in out.answer


def test_caveat_ref_is_the_scope_of_the_withheld_reason():
    f = Facts(req([raw("a2", "q-2", 7.0)], [held("q-1"), Withheld(chart_id="c1", op="raw", text="차트 사유")]))
    assert [(c.ref, c.text) for c in build_caveats(f) if c.source == "plan_warning"] == [("q-1", HELD), ("c1", "차트 사유")]


# ── 재검토 11-20 ─────────────────────────────────────────────────
def test_a_withheld_chart_does_not_demote_a_correct_answer_of_the_same_sub_question():
    chart_held = Withheld(sub_question_id="q-1", chart_id="c1", op="raw", text="차트 사유")
    f = Facts(req([raw("a1", "q-1", 100.0)], [chart_held]))
    assert f.withheld_subs == set() and f.role_of(f.req.calc_results[0]) == "요청"
    out = run_module6(req([raw("a1", "q-1", 100.0)], [chart_held]), chat=fake({"answer": "{a1}"}, {"answer": "{a1}"}))
    assert "참고로" not in out.answer and "100가구" in out.answer


def _reference_problems(draft):
    from backend.agent.answer_compose.placeholder import reference_problems
    return reference_problems(draft, Facts(req([raw("a1", "q-1", 1404.0)], [held()])))


def test_reference_word_elsewhere_does_not_excuse_a_substitute_written_as_the_answer():
    assert _reference_problems("참고 자료는 아래 표에 있습니다. 보증부월세 비율은 {a1}입니다.")


def test_substitute_needs_the_reason_before_it_and_the_reference_opening_in_its_own_sentence():
    assert _reference_problems("참고로 보증부월세는 {a1}입니다.")                          # 사유 없음
    assert _reference_problems("비율을 계산하지 못했습니다. 보증부월세는 {a1}입니다.")       # '참고로' 아님
    assert not _reference_problems("비율을 계산하지 못했습니다. 참고로 보증부월세는 {a1}입니다.")


def test_same_withheld_text_for_two_sub_questions_keeps_both_scopes():
    f = Facts(req([raw("a3", "q-3", 1.0)], [held("q-1"), held("q-2")]))
    assert [c.ref for c in build_caveats(f) if c.source == "plan_warning"] == ["q-1", "q-2"]


def test_plan_warning_already_covered_by_withheld_is_not_repeated_with_a_plan_scope():
    f = Facts(req([raw("a3", "q-3", 1.0)], [held("q-1")], plan_warnings=[HELD]))
    assert [(c.ref, c.text) for c in build_caveats(f) if c.source == "plan_warning"] == [("q-1", HELD)]
