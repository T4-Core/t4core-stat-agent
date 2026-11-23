"""[NEW 11-17] 자체 검토 보고서(모듈3_모듈6_수정_자체검토_보고서.md) 모듈 6 항목의 회귀 테스트. 항목 번호는 보고서의 A-N"""
import pytest

from backend.agent.answer_compose import placeholder, template
from backend.agent.answer_compose.facts import Facts
from backend.agent.answer_compose.pipeline import run_module6
from backend.agent.answer_compose.tables import build_tables
from backend.agent.chart_calculate.calculate import run_answer_steps
from backend.core.reasons import humanize
from backend.schemas.answer import Module6Request
from backend.schemas.chart import Step
from tests.answer_compose._data import BUNDLE
from tests.chart_calculate._views import VID, view

NAT = {"행정구역별": ["전국"]}


def calc(d, records):
    st = Step.model_validate({"step_id": "a1", **d})
    return st, run_answer_steps([st], records)[0]


def operand(item, select=None):
    return {"role": "value", "record_id": VID, "item": item, "select": NAT if select is None else select}


def facts(records, *pairs, displays=None):
    return Facts(Module6Request(query_bundle=BUNDLE, records=records, calc_results=[r for _, r in pairs],
                                displays=displays or {}, answer_steps=[s for s, _ in pairs]))


def _no_hcx(*a, **k):
    raise RuntimeError("HCX 없음")


# ── A-3 음수 값을 부호째 쓰고 방향 단어를 붙인 문장 ─────────────────
def births():
    v = view()
    return v, calc({"op": "growth_rate", "base": "prev", "operands": [operand("출생아수(명)")]}, [v])


@pytest.mark.parametrize("draft", ["출생아수는 2022년 {a1.r0} 감소했습니다.",
                                   "출생아수는 2022년 {a1.r0} 감소했고 2024년 {a1.r2.abs} 증가했습니다."])
def test_a3_negative_value_written_with_its_sign_next_to_a_direction_word_is_rejected(draft):
    v, pair = births()
    f = facts([v], pair)
    filled = placeholder.fill(draft, f)
    assert any("{a1.r0.abs}" in p for p in placeholder.check(draft, filled, f, []))


@pytest.mark.parametrize("draft", ["출생아수는 2022년 {a1.r0.abs} 감소했고 2024년 {a1.r2.abs} 증가했습니다.",
                                   "출생아수 증감률은 2022년 {a1.r0}, 2023년 {a1.r1}, 2024년 {a1.r2}, 2025년 {a1.r3}입니다."])
def test_a3_absolute_value_with_words_or_signed_value_without_words_passes(draft):
    v, pair = births()
    f = facts([v], pair)
    filled = placeholder.fill(draft, f)
    assert placeholder.check(draft, filled, f, []) == []


# ── A-4 displays 를 받지 못했을 때 소수 값 ───────────────────────────
def test_a4_fractional_count_keeps_its_decimals_without_displays():
    v = view([["2023", "전국", "합계출산율(명)", 0.721], ["2024", "전국", "합계출산율(명)", 0.748]])
    raw = calc({"op": "raw", "operands": [operand("합계출산율(명)", {**NAT, "시점": ["2024"]})]}, [v])
    out = run_module6(Module6Request(query_bundle=BUNDLE, records=[v], calc_results=[raw[1]], displays={},
                                     answer_steps=[raw[0]]), chat=_no_hcx)
    assert "0.748명" in out.answer and out.tables[0].rows[0][3] == "0.748명"


def test_a4_mean_of_counts_without_displays_still_rounds_like_the_planner():
    v = view([["2025", "서울", "인구수(명)", 6691777.0], ["2025", "부산", "인구수(명)", 6691778.0]], ["시점", "행정구역별", "항목", "값"])
    pair = calc({"op": "aggregate", "agg": "mean", "operands": [operand("인구수(명)", {"행정구역별": ["서울", "부산"]})]}, [v])
    assert facts([v], pair).fmt_result(pair[1], pair[1].value) == "6,691,778명"


# ── A-5 · A-10 사유 문구 ────────────────────────────────────────
@pytest.mark.parametrize("note,expected", [
    ("내부 오류로 계산하지 못함: ValueError", "계산 중 오류가 발생해 계산하지 못했습니다"),
    ("2024 4분기: 같은 시점에 값이 둘 이상(150, 160)이라 계산하지 않음", "2024 4분기는 같은 시점의 값이 둘 이상(150, 160)이라 계산하지 못했습니다"),
    ("2025 1분기: 직전 시점(2024 4분기)에 값이 둘 이상이라 계산하지 않음",
     "2025 1분기는 직전 시점(2024 4분기)의 값이 둘 이상이라 계산하지 못했습니다"),
    ("2025 1분기: 직전 시점(2024 4분기) 값이 없어 계산하지 않음", "2025 1분기는 직전 시점(2024 4분기) 값이 없어 계산하지 못했습니다"),
    ("2023: 직전 시점(2022) 값이 없어 계산하지 않음", "2023년은 직전 시점(2022년) 값이 없어 계산하지 못했습니다"),
])
def test_a5_a10_reasons_become_sentences(note, expected):
    assert humanize(note) == expected


def test_a5_old_import_path_still_works():
    from backend.agent.answer_compose.reasons import humanize as old
    assert old is humanize


# ── A-6 차트 경고도 사용자용 문장 ─────────────────────────────────
def test_a6_chart_warnings_are_user_sentences():
    from backend.agent.chart_calculate.content import build_charts
    from backend.agent.chart_calculate.planner import Decision, make_plan
    from backend.schemas.chart import ChartRequest
    years = ["2021", "2022", "2023", "2024", "2025"]
    v = view([[y, "전국", "혼인건수(건)", n] for y, n in zip(years, (192507.0, None, 193657.0, 222412.0, 240326.0))])
    dec = {"charts": [{"chart_id": "c1", "record_id": VID, "select": {**NAT, "항목": ["혼인건수(건)"]}}]}
    cp, displays = make_plan([ChartRequest(chart_id="c1", sub_question_ids=["q-1"], chart_type="line", measure="growth_rate",
                                           fallback_chart="bar")], [v], Decision.model_validate(dec))
    contents, _ = build_charts(cp, [v], displays=displays)
    warnings = contents[0].warnings
    assert "2023년은 직전 시점(2022년) 값이 없어 계산하지 못했습니다" in warnings
    assert "값이 비어 있는 자료 1개는 계산에서 제외했습니다" in warnings
    assert not any("계산하지 않음" in w or "제외한 행" in w for w in warnings)


# ── A-7 원본 View 표는 한 항목 안에서 자릿수를 맞춘다 ─────────────────
def test_a7_view_table_uses_one_number_of_decimals_per_item():
    rows = [["2022", "전국", "합계출산율(명)", 0.778], ["2023", "전국", "합계출산율(명)", 0.72],
            ["2024", "전국", "합계출산율(명)", 0.7], ["2025", "전국", "합계출산율(명)", 1.0],
            ["2025", "전국", "출생아수(명)", 254341.0]]
    v = view(rows)
    pair = calc({"op": "raw", "operands": [operand("합계출산율(명)")]}, [v])
    shown = [r[-1] for r in build_tables(facts([v], pair))[-1].rows]
    assert shown == ["0.778명", "0.720명", "0.700명", "1.000명", "254,341명"]


# ── A-8 표시하면 0 인 증감 ────────────────────────────────────────
def test_a8_tiny_change_sentence_reads_naturally():
    v = view([["2024", "전국", "혼인건수(건)", 100000.0], ["2025", "전국", "혼인건수(건)", 100003.0]])
    pair = calc({"op": "growth_rate", "from": "2024", "to": "2025", "operands": [operand("혼인건수(건)")]}, [v])
    assert template.sentence(facts([v], pair), pair[1]) == \
        "전국 혼인건수는 2024년 100,000건에서 2025년 100,003건으로, 변화가 거의 없습니다(0.0%)."


def test_a8_tiny_cagr_sentence_has_no_dangling_comma():
    v = view([["2021", "전국", "혼인건수(건)", 100000.0], ["2025", "전국", "혼인건수(건)", 100003.0]])
    pair = calc({"op": "cagr", "from": "2021", "to": "2025", "operands": [operand("혼인건수(건)")]}, [v])
    assert template.sentence(facts([v], pair), pair[1]).endswith("2021년부터 2025년까지 연평균 변화가 거의 없습니다(0.0%).")


# ── A-9 쓰지 않는 함수 ───────────────────────────────────────────
def test_a9_prompt_text_based_allowed_tokens_is_gone():
    from backend.agent.answer_compose import write
    assert not hasattr(write, "allowed_tokens")


# ── 외부 피드백 A-4: displays 와 answer_steps 가 모두 없어도 평균은 평균으로 ─────────
def test_a4_mean_without_displays_and_steps_keeps_its_name_and_decimals():
    v = view([["2025", "서울", "인구(천명)", 50.0], ["2025", "부산", "인구(천명)", 51.0]], ["시점", "행정구역별", "항목", "값"])
    st, r = calc({"op": "aggregate", "agg": "mean", "operands": [operand("인구(천명)", {"행정구역별": ["서울", "부산"]})]}, [v])
    assert r.agg == "mean"
    out = run_module6(Module6Request(query_bundle=BUNDLE, records=[v], calc_results=[r], displays={}), chat=_no_hcx)
    assert "평균은 5.1만 명" in out.answer      # 50.5천명 = 5.05만 명 → 소수 첫째 자리


def test_a4_agg_is_only_set_for_aggregate():
    v = view()
    _, r = calc({"op": "raw", "operands": [operand("혼인건수(건)", {**NAT, "시점": ["2025"]})]}, [v])
    assert r.agg is None


# ── 외부 피드백 A-3: 방향은 값마다 그 값의 서술어로 본다 (출생아수 직전 대비: -4.4%, -7.7%, +3.6%, +6.7%) ──
@pytest.mark.parametrize("draft", [
    "출생아수는 2022년 {a1.r0.abs} 증가했고 2024년 {a1.r2.abs} 감소했습니다.",          # 절댓값으로 방향을 뒤집음
    "출생아수는 2022년 {a1.r0.abs}, 2023년 {a1.r1.abs} 증가했습니다.",                 # 나열 뒤 서술어 하나
    "출생아수는 2024년 {a1.r2.abs} 감소했습니다.",
])
def test_a3_direction_word_is_checked_against_the_value_it_describes(draft):
    v, pair = births()
    f = facts([v], pair)
    filled = placeholder.fill(draft, f)
    assert any("방향이 맞지 않음" in p for p in placeholder.check(draft, filled, f, []))


@pytest.mark.parametrize("draft", [
    "출생아수는 2022년 {a1.r0}였고 2024년 {a1.r2.abs} 증가했습니다.",                   # 음수는 숫자로만, 증가는 양수 값에
    "출생아수는 2022년 {a1.r0.abs} 감소했고 2024년 {a1.r2.abs} 증가했습니다.",
    "출생아수는 2022년 {a1.r0.abs}, 2023년 {a1.r1.abs} 감소한 뒤 2024년 {a1.r2.abs}, 2025년 {a1.r3.abs} 증가했습니다.",   # [11-18] 4개 모두 나열 (F15: 앞에서부터 나열하다 만 문장은 걸린다)
])
def test_a3_correct_mixed_direction_sentences_pass(draft):
    v, pair = births()
    f = facts([v], pair)
    filled = placeholder.fill(draft, f)
    assert placeholder.check(draft, filled, f, []) == []


# ── 남은 한계 3 (A-3): 방향도 자리표시자로 ({a1.dir} · {a1.rN.dir}) ─────────────────────
def test_limit3_dir_placeholder_fills_the_direction_from_the_value():
    v, pair = births()
    f = facts([v], pair)
    draft = "출생아수는 2022년 {a1.r0.abs} {a1.r0.dir}했고 2024년 {a1.r2.abs} {a1.r2.dir}했습니다."
    filled = placeholder.fill(draft, f)
    assert filled.text == "출생아수는 2022년 4.4% 감소했고 2024년 3.6% 증가했습니다."
    assert placeholder.check(draft, filled, f, []) == []


def test_limit3_scalar_dir_uses_end_minus_start():
    from tests.answer_compose._data import growth, request
    f = Facts(request(results=[growth()]))
    assert placeholder.fill("혼인건수는 {a1.abs} {a1.dir}했습니다.", f).text == "혼인건수는 24.8% 증가했습니다."


def test_limit3_dir_is_refused_where_it_has_no_meaning():
    v = view()
    raw = calc({"op": "raw", "operands": [operand("혼인건수(건)", {**NAT, "시점": ["2025"]})]}, [v])
    f = facts([v], raw)
    assert any("방향" in p for p in placeholder.fill("{a1.dir}", f).problems)
    flat = view([["2024", "전국", "혼인건수(건)", 100.0], ["2025", "전국", "혼인건수(건)", 100.0]])
    zero = calc({"op": "change", "from": "2024", "to": "2025", "operands": [operand("혼인건수(건)")]}, [flat])
    assert any("변화가 없" in p for p in placeholder.fill("{a1.dir}", facts([flat], zero)).problems)


def test_limit3_dir_alone_is_not_a_value_citation_and_is_shown_in_the_prompt():
    from backend.agent.answer_compose.write import build_prompt, shown_tokens
    v, pair = births()
    f = facts([v], pair)
    draft = "출생아수는 2022년 {a1.r0.dir}했습니다."
    filled = placeholder.fill(draft, f)
    assert any("인용하지 않은 계산 결과" in p for p in placeholder.check(draft, filled, f, []))
    assert "{a1.r0.dir}" in build_prompt(f, []) and "a1.r0.dir" in shown_tokens(f)


def test_limit3_clause_safety_net_catches_a_direction_word_far_from_the_value():
    v, pair = births()
    f = facts([v], pair)
    draft = "출생아수는 증가세가 이어져 2022년 {a1.r0.abs}, 2023년 {a1.r1.abs}를 기록했습니다."
    problems = placeholder.check(draft, placeholder.fill(draft, f), f, [])
    assert any("{a1.r0}" in p for p in problems) and any("{a1.r1}" in p for p in problems)


# ── 실제 HCX 확인 (보고서 11.3) ─────────────────────────────────────
def ranks():
    rows = [["2023", r, "인구수(명)", n] for r, n in (("경기도", 13630821.0), ("서울특별시", 9386034.0), ("부산광역시", 3293362.0))]
    v = view(rows, ["시점", "행정구역별", "항목", "값"])
    return v, calc({"op": "rank", "operands": [operand("인구수(명)", {})]}, [v])


def test_h5_rank_number_matching_the_cited_point_is_allowed():
    """HCX 가 '1위: {a1.r0.key} ({a1.r0})' 처럼 써서 두 번 다 거절됐다 (2026-11-17 실제 HCX)"""
    v, pair = ranks()
    f = facts([v], pair)
    draft = "2023년 인구 순위는 1위 {a1.r0.key} {a1.r0}, 2위 {a1.r1.key} {a1.r1}, 3위 {a1.r2.key} {a1.r2}입니다."
    assert placeholder.check(draft, placeholder.fill(draft, f), f, []) == []


def test_h5_wrong_rank_number_is_still_rejected_and_the_retry_names_rank_placeholders():
    v, pair = ranks()
    f = facts([v], pair)
    draft = "2023년 인구 순위는 2위 {a1.r0.key} {a1.r0}, 1위 {a1.r1.key} {a1.r1}, 3위 {a1.r2.key} {a1.r2}입니다."
    problems = placeholder.check(draft, placeholder.fill(draft, f), f, [])
    assert any("자리표시자 밖에 숫자" in p and "{a1.r0.rank}" in p for p in problems)


def test_h6_single_point_rank_reads_like_a_superlative():
    v = view([["2023", r, "인구수(명)", n] for r, n in (("경기도", 13630821.0), ("서울특별시", 9386034.0))],
             ["시점", "행정구역별", "항목", "값"])
    pair = calc({"op": "rank", "top_n": 1, "operands": [operand("인구수(명)", {})]}, [v])
    assert template.sentence(facts([v], pair), pair[1]) == "2023년 인구수가 가장 많은 곳은 경기도로, 13,630,821명입니다."


def test_h7_signed_negative_value_next_to_a_dir_placeholder_is_rejected():
    """HCX 가 '{a1.r0} {a1.r0.dir}' 로 써서 '-0.4% 감소' 가 통과했다 (2026-11-17 실제 HCX 재확인)"""
    v, pair = births()
    f = facts([v], pair)
    draft = "출생아수는 2022년에는 {a1.r0} {a1.r0.dir}, 2024년에는 {a1.r2} {a1.r2.dir}였습니다."
    problems = placeholder.check(draft, placeholder.fill(draft, f), f, [])
    assert any("{a1.r0.abs}" in p for p in problems) and not any("{a1.r2}" in p for p in problems)


def test_h7_dir_placeholder_must_belong_to_the_value_beside_it():
    v, pair = births()
    f = facts([v], pair)
    draft = "출생아수는 2022년 {a1.r0.abs} {a1.r2.dir}했습니다."
    problems = placeholder.check(draft, placeholder.fill(draft, f), f, [])
    assert any("다른 값의 방향" in p for p in problems)


def test_h8_draft_that_repeats_the_retry_instructions_is_rejected():
    """재시도에서 HCX 가 답변 대신 고칠 점을 옮겨 적었고 검사를 통과했다 (2026-11-17 실제 HCX 재확인)"""
    v, pair = births()
    f = facts([v], pair)
    draft = "- 음수 값을 부호째 쓰고 방향 자리표시자를 붙이는 경우, 예를 들어 {a1.r0} — 방향을 쓸 때는 절댓값 {a1.r0.abs}를 사용해야 한다."
    assert any("지시문" in p for p in placeholder.check(draft, placeholder.fill(draft, f), f, []))


def test_h8_retry_message_asks_for_the_answer_only():
    from backend.agent.answer_compose.write import retry_messages
    msg = retry_messages([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], "초안", ["문제 하나"])[-1]["content"]
    assert "답변 문장만" in msg and "옮겨 적지" in msg


def test_h5_rank_number_after_its_value_is_matched_to_the_nearer_placeholder():
    """'{a1.r0.key}가 {a1.r0}으로 1위를 차지하였고, 그 뒤를 이어 {a1.r1.key}가 …' 가 거절됐다 (실제 HCX 재확인)"""
    v, pair = ranks()
    f = facts([v], pair)
    draft = ("2023년 {a1.r0.key}가 {a1.r0}으로 1위를 차지하였고, 그 뒤를 이어 {a1.r1.key}가 {a1.r1}으로 2위, "
             "{a1.r2.key}가 {a1.r2}으로 3위입니다.")
    assert placeholder.check(draft, placeholder.fill(draft, f), f, []) == []


# ── 남은 한계 (보고서 12.3) ───────────────────────────────────────
@pytest.mark.parametrize("draft,ok", [
    ("2023년 인구는 경기도가 {a1.r0}으로 가장 많고, 그 뒤를 이어 서울특별시가 {a1.r1}, 부산광역시가 {a1.r2}입니다.", True),
    ("2023년 인구는 서울특별시가 {a1.r0}으로 가장 많고, 경기도가 {a1.r1}입니다.", False),
    ("전국 17개 시도 중 {a1.r0.key}가 {a1.r0}으로 가장 많습니다. 서울특별시는 {a1.r1}입니다.", True),
])
def test_r4_name_written_next_to_a_value_must_be_that_values_name(draft, ok):
    v, pair = ranks()
    f = facts([v], pair)
    problems = [p for p in placeholder.check(draft, placeholder.fill(draft, f), f, []) if "의 이름은" in p]
    assert (problems == []) is ok
    if not ok:
        assert "{a1.r0.key}" in problems[0] and "경기도" in problems[0]


def test_r5_template_does_not_repeat_the_failure_as_a_caveat_and_names_the_direction():
    v = view([["2025", "전국", "혼인건수(건)", 240326.0]])
    st, r = calc({"op": "extreme", "kind": "min", "operands": [operand("혼인건수(건)")]}, [v])
    out = run_module6(Module6Request(query_bundle=BUNDLE, records=[v], calc_results=[r], displays={}, answer_steps=[st]), chat=_no_hcx)
    assert out.answer.count("계산하지 못했습니다") == 1 and "최솟값" in out.answer
    assert any(c.source == "calc_note" for c in out.caveats)          # 출력의 주의사항 목록에는 남는다

