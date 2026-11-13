"""[NEW 11-13] 리뷰 지적 수정 (모듈 6): 자리표시자 검사 강화, 전부 결측인 계산, 보류 사유 전달, 같은 값의 다른 지역 행 강조"""
from backend.agent.answer_compose.facts import Facts, has_value
from backend.agent.answer_compose.pipeline import run_module6
from backend.agent.answer_compose.placeholder import check, fill
from backend.agent.answer_compose.tables import build_tables
from backend.agent.answer_compose.write import allowed_tokens, build_prompt
from backend.agent.chart_calculate.calculate import run_answer_steps
from backend.schemas.answer import Module6Request
from backend.schemas.chart import CalcResult, Step
from backend.schemas.query import QueryBundle
from tests.answer_compose._data import DISPLAYS, fake, growth, inp, request
from tests.chart_calculate._views import VID, view
from tests.chart_calculate.test_review_fixes import BUSAN, raw, run as run_module3_for


def run_check(text, results=None, allowed=None):
    f = Facts(request(results=results))
    filled = fill(text, f, allowed)
    return filled, check(text, filled, f, [])


# ── P1-4: 수치 인용과 시점 인용을 구분 ──────────────────────────────
def test_year_placeholder_cannot_stand_in_for_the_result():
    """실제 결과는 24.8% 인데 '증감률은 2025%입니다' 에 입력 시점 자리표시자만 붙인 문장이 통과하던 문제"""
    _, problems = run_check("증감률은 {a1.in1.key}%입니다.")
    assert any("시점·이름 자리표시자 뒤에 %" in p for p in problems)
    assert any(p.startswith("인용하지 않은 계산 결과: a1") for p in problems)
    _, only_key = run_check("혼인건수는 {a1.in0.key}년 {a1.in1.key}입니다.")
    assert any(p.startswith("인용하지 않은 계산 결과: a1") for p in only_key)


def test_inputs_alone_do_not_count_as_using_the_result():
    _, problems = run_check("혼인건수는 {a1.in0}에서 {a1.in1}이 되었습니다.")
    assert any(p.startswith("인용하지 않은 계산 결과: a1") for p in problems)
    filled, ok = run_check("혼인건수는 {a1.in0}에서 {a1.in1}으로 {a1.abs} 증가했습니다.")
    assert ok == [] and filled.value_used == ["a1"]


def test_only_placeholders_shown_in_the_prompt_are_allowed():
    pts = [{"key": {"행정구역별": f"지역{n}", "시점": "2025"}, "value": 100.0 - n, "rank": n + 1} for n in range(12)]
    r = CalcResult.model_validate({"step_id": "a1", "op": "rank", "unit": "건", "display_ref": "d2", "value": pts,
                                   "inputs": [inp("2025", 100)], "record_ids": [VID]})
    f = Facts(request(results=[r]))
    prompt = build_prompt(f, [])
    allowed = allowed_tokens(prompt)
    assert "{a1.r9}" in prompt and "{a1.r10}" not in prompt and "{a1.r11}" not in prompt        # 프롬프트는 10개까지만 보여 준다
    assert {"a1.r0", "a1.r0.abs", "a1.r0.key", "a1.r0.rank", "a1.r9"} <= allowed and "a1.r11" not in allowed
    assert fill("{a1.r11}", f).problems == []                                                    # 허용 목록이 없으면(예전 호출) 풀린다
    assert fill("{a1.r11}", f, allowed).problems == ["프롬프트에 없는 자리표시자: {a1.r11} — [계산 결과]에 적힌 것만 쓴다"]
    assert fill("{a1.r9}", f, allowed).problems == []
    # 허용 목록의 모든 항목은 실제로 풀린다 (프롬프트가 보여 준 것을 거절하지 않는다)
    assert all(fill("{" + t + "}", f, allowed).problems == [] for t in allowed)


def test_pipeline_rejects_unseen_placeholder_and_falls_back():
    pts = [{"key": {"행정구역별": f"지역{n}", "시점": "2025"}, "value": 100.0 - n, "rank": n + 1} for n in range(12)]
    r = CalcResult.model_validate({"step_id": "a1", "op": "rank", "unit": "건", "display_ref": "d2", "value": pts,
                                   "inputs": [inp("2025", 100)], "record_ids": [VID]})
    bad = {"answer": "12위는 {a1.r11.key} {a1.r11}이고 1위는 {a1.r0.key} {a1.r0}입니다."}
    chat = fake(bad, bad)
    out = run_module6(request(results=[r]), chat=chat)
    assert out.method == "template" and "프롬프트에 없는 자리표시자: {a1.r11.key}" in out.notes[0]
    assert "a1.r11" not in out.answer


# ── P1-5: 전부 결측이면 실패한 계산 ────────────────────────────────
def all_missing() -> CalcResult:
    return CalcResult.model_validate({
        "step_id": "a1", "op": "index", "unit": "index", "display_ref": "d1", "record_ids": [VID], "note": "기준값 0",
        "value": [{"key": {"시점": "2024"}, "value": None}, {"key": {"시점": "2025"}, "value": None}],
        "inputs": [inp("2024", 0), inp("2025", 10)]})


def test_list_with_no_valid_value_is_a_failed_calculation():
    r = all_missing()
    assert not has_value(r) and Facts(request(results=[r])).ok_results == []
    chat = fake()
    out = run_module6(request(results=[r]), chat=chat)
    assert (out.insufficient, out.method, chat.calls) == (True, "template", [])                   # HCX 도 부르지 않는다
    assert out.answer.splitlines()[0] == "혼인건수 지수를 계산하지 못했습니다(기준 값이 0이라 비율을 계산할 수 없습니다)."
    assert "2024년 -" not in out.answer and [t.kind for t in out.tables] == ["view"]            # 빈 목록 표도 없다
    assert [c.source for c in out.caveats] == ["calc_note"]


def test_partial_list_is_still_a_success():
    r = all_missing().model_copy(update={"value": [{"key": {"시점": "2024"}, "value": None}, {"key": {"시점": "2025"}, "value": 100.0}]})
    out = run_module6(request(results=[r]), chat=fake({"answer": "{a1.r1.key} 지수는 {a1.r1}입니다."}))
    assert (out.insufficient, out.method) == (False, "hcx")


# ── P1-3: 보류 사유가 답변까지 ─────────────────────────────────────
def test_plan_warnings_become_the_first_caveats():
    req = request(plan_warnings=["질문의 지역(서울특별시) 자료가 없어 계산하지 못했습니다 (받은 자료의 지역: 부산광역시)."])
    out = run_module6(req, chat=fake({"answer": "{a1.in0} {a1.in1} {a1.abs}"}))
    assert [c.source for c in out.caveats][:1] == ["plan_warning"]


def test_withheld_calculation_reaches_the_answer_end_to_end():
    m3 = run_module3_for(BUSAN, raw({"행정구역별": ["부산광역시"]}), filters={"지역": ["서울특별시"]})
    req = Module6Request(query_bundle=QueryBundle(query_id="q", original="서울 출생아 수"), records=[view(BUSAN, ["시점", "행정구역별", "항목", "값"], rid="v1")],
                         calc_results=m3.calc_results, displays=m3.displays, answer_steps=m3.chart_plan.answer_steps,
                         plan_warnings=m3.chart_plan.warnings)
    chat = fake()
    out = run_module6(req, chat=chat)
    assert (out.method, out.insufficient, chat.calls) == ("none", True, [])
    assert "※ 질문의 지역(서울특별시) 자료가 없어 계산하지 못했습니다 (받은 자료의 지역: 부산광역시)." in out.answer
    assert "900" not in out.answer                                                                # 부산 값을 서울 값처럼 말하지 않는다


# ── 같은 값의 다른 지역 행은 근거로 강조하지 않는다 ──────────────────────
def test_same_value_in_another_region_is_not_highlighted_when_the_selection_is_known():
    rows = [["2025", "서울특별시", "출생아수(명)", 900.0], ["2025", "부산광역시", "출생아수(명)", 900.0], ["2025", "대구광역시", "출생아수(명)", 500.0]]
    rec = view(rows, ["시점", "행정구역별", "항목", "값"], rid="v1")
    step = Step.model_validate({"step_id": "a1", "op": "raw", "operands": [
        {"role": "value", "record_id": "v1", "item": "출생아수(명)", "select": {"행정구역별": ["서울특별시"], "시점": ["2025"]}}]})
    res = run_answer_steps([step], [rec])
    make = lambda steps: Module6Request(query_bundle=QueryBundle(original="q"), records=[rec], calc_results=res,  # noqa: E731
                                        displays={"d": DISPLAYS["d2"]}, answer_steps=steps)
    view_table = lambda req: [t for t in build_tables(Facts(req)) if t.kind == "view"][0]            # noqa: E731
    known = view_table(make([step]))
    assert [known.raw_rows[i][1] for i in known.highlight_rows] == ["서울특별시"]
    unknown = view_table(make([]))                                                                   # 선택 조건을 모르면 값으로만 찾는다
    assert [unknown.raw_rows[i][1] for i in unknown.highlight_rows] == ["서울특별시", "부산광역시"]


# ── 계산해서 만드는 지표를 '없음' 으로 알리지 않는다 ────────────────────
def _missing(*requested, slot="지표"):
    return {"slot": slot, "type": "missing", "requested": list(requested), "text": f"View 조건 {slot} {list(requested)} 없음"}


def test_derived_indicator_missing_is_not_a_caveat_but_real_missing_indicator_is():
    """'혼인건수 증감률' 은 모듈 3 이 계산하는 값이라 표에 없는 것이 당연하다. 실제 HCX 가 이 주의사항을 보고 '증감률 정보는 제공되지 않았다'고 덧붙였다"""
    from backend.agent.answer_compose.caveats import build_caveats
    notes = [_missing("혼인건수 증감률"), _missing("출생아수 추이", "사망자수 증가율"),           # 계산해서 만드는 값 → 뺀다
             _missing("고령인구비율"), _missing("혼인건수", "혼인건수 증감률"),                 # 실제 지표가 없음 → 남긴다
             _missing("남자", slot="성별")]                                                  # 지표 슬롯이 아님 → 남긴다
    f = Facts(request(records=[view(notes=notes)]))
    texts = [c.text for c in build_caveats(f)]
    assert texts == ["View 조건 지표 ['고령인구비율'] 없음", "View 조건 지표 ['혼인건수', '혼인건수 증감률'] 없음", "View 조건 성별 ['남자'] 없음"]
    prompt = build_prompt(f, build_caveats(f))
    assert "['혼인건수 증감률'] 없음" not in prompt and "['혼인건수', '혼인건수 증감률'] 없음" in prompt      # HCX 에게도 보이지 않는다


# ── 단위 중복: HCX 가 '{a1}명' 이라고 써서 '6,092,672명명' 이 되던 문제 ─────────
def test_unit_already_in_the_value_is_not_repeated():
    f = Facts(request())
    assert fill("증가율은 {a1}%입니다.", f).text == "증가율은 24.8%입니다."                       # 24.8% + % → 한 번만
    assert fill("혼인건수는 {a1.in1}건입니다.", f).text == "혼인건수는 240,326건입니다."         # 240,326건 + 건
    assert fill("{a1.in0.key}년에는 {a1.in0}이었고", f).text == "2021년에는 192,507건이었고"   # 2021년 + 년
    assert fill("{a1.abs} 증가했고 {a1}만큼", f).text == "24.8% 증가했고 24.8%만큼"             # 단위로 시작하지 않는 뒤 글자는 그대로
    assert fill("{a1.in1}과 {a1.in0}의 차이", f).text == "240,326건과 192,507건의 차이"
    assert fill("{a1.in1}건건", f).text == "240,326건건"                                         # 같은 글자가 두 번 이어져도 한 번만 걷어 낸다


def test_unit_duplicate_does_not_break_the_check():
    f = Facts(request())
    text = "혼인건수는 {a1.in0}에서 {a1.in1}으로 {a1.abs}% 증가했습니다."
    filled = fill(text, f)
    assert filled.text == "혼인건수는 192,507건에서 240,326건으로 24.8% 증가했습니다." and check(text, filled, f, []) == []


# ── 어림 표현: 계산된 정확한 값에 '약' 을 붙이지 않는다 ─────────────────────
def test_approximation_words_around_exact_values_are_removed():
    """실제 HCX 가 '2022년에는 약 372,939명으로 증가하였으며' 처럼 정확한 값에 '약' 을 붙였다"""
    f = Facts(request())
    assert fill("2022년에는 약 {a1.in1}으로 증가하였으며", f).text == "2022년에는 240,326건으로 증가하였으며"
    assert fill("혼인건수는 대략 {a1.in0}이었고 거의 {a1.in1}에 이르렀다", f).text == "혼인건수는 192,507건이었고 240,326건에 이르렀다"
    assert fill("증가율은 약{a1.abs}입니다", f).text == "증가율은 24.8%입니다"                    # 띄어쓰기 없이 붙어도
    assert fill("{a1.in0} 정도입니다. {a1.in1}가량 늘었다", f).text == "192,507건입니다. 240,326건 늘었다"   # 뒤의 정도 · 가량 (조사가 달라지지 않는 곳)
    assert fill("약 {a1.in0}에서", f).text == "192,507건에서"                                      # 문장 맨 앞


def test_approximation_words_are_kept_when_they_are_not_about_a_number():
    f = Facts(request())
    assert fill("계약 {a1.in0}", f).text == "계약 192,507건"                                      # '계약' 의 '약' 은 단어 일부
    assert fill("약속한 값은 {a1.in0}", f).text == "약속한 값은 192,507건"
    assert fill("{a1.in0} 정도에서 {a1.in1}정도로", f).text == "192,507건 정도에서 240,326건정도로"   # 조사가 붙는 '정도에서' · '정도로' 는 지우면 조사가 어색해져 그대로 둔다
    assert fill("약 {a1.in0.key}", f).text == "2021년"                                              # 연도 앞의 약도 정확한 값 앞이라 뺀다 (어색한 표현)


def test_approximation_removal_does_not_break_checks_and_prompt_forbids_it():
    from backend.agent.prompts import ANSWER_COMPOSE_SYS
    f = Facts(request())
    text = "혼인건수는 약 {a1.in0}에서 약 {a1.in1}으로 약 {a1.abs} 증가했습니다."
    filled = fill(text, f)
    assert filled.text == "혼인건수는 192,507건에서 240,326건으로 24.8% 증가했습니다." and check(text, filled, f, []) == []
    assert "어림 표현" in ANSWER_COMPOSE_SYS and "'약'" in ANSWER_COMPOSE_SYS
