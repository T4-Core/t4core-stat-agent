"""[NEW] reasons.py(계산 불가 사유 문구) · facts.fixed_text(지역 같은 고정 대상 복원)"""
import pytest

from backend.agent.answer_compose.caveats import build_caveats
from backend.agent.answer_compose.facts import Facts
from backend.agent.answer_compose.reasons import humanize
from backend.agent.answer_compose.tables import build_tables
from backend.agent.answer_compose.template import sentence
from backend.agent.answer_compose.write import build_prompt
from backend.schemas.answer import Module6Request
from backend.schemas.chart import CalcResult
from backend.schemas.query import QueryBundle
from tests.answer_compose._data import DISPLAYS, growth, inp
from tests.chart_calculate._views import view


# ── 사유 문구 ───────────────────────────────────────────────────
@pytest.mark.parametrize("note,want", [
    ("{'시점': '2008'}: 한쪽 값 없음", "2008년은 한쪽 값이 없어 계산하지 못했습니다"),
    ("{'행정구역별': '서울', '시점': '2008'}: 키 중복", "서울 2008년은 같은 조건의 값이 여러 개라 계산하지 못했습니다"),
    ("{'시점': '2008'}: 분모 0", "2008년: 분모가 0이라 계산할 수 없습니다"),
    ("join_on 필요: 피연산자에 값이 여러 개", "비교할 시점을 정하지 못했습니다"),
    ("시점 1999 값 없음", "1999년 값이 없습니다"),
    ("기준 시점 1999 값 없음", "기준 시점인 1999년 값이 없습니다"),
    ("기준값 0", "기준 값이 0이라 비율을 계산할 수 없습니다"),
    ("단위가 다름: 명 / %", "단위가 달라 비교할 수 없습니다: 명 / %"),
    ("수록 주기가 다름: Y / M", "수록 주기가 달라 비교할 수 없습니다: Y / M"),
    ("항목 없음: 없는항목(명)", "'없는항목(명)' 항목이 자료에 없습니다"),
    ("시점에 없는 값: ['1999']", "1999년 자료가 없습니다"),
    ("행정구역별에 없는 값: ['제주', '울산']", "행정구역별에 제주, 울산이(가) 없습니다"),
    ("truncated: 행이 2000개를 넘어 앞부분만 사용", "자료의 행이 잘려 있어 계산하지 않았습니다"),
    ("시점이 하나뿐이라 직전 시점이 없음", "시점이 하나뿐이라 직전 시점과 비교할 수 없습니다"),
])
def test_humanize_known_reasons(note, want):
    assert humanize(note) == want


def test_humanize_keeps_unknown_reasons_and_joins_many():
    assert humanize("처음 보는 사유") == "처음 보는 사유"                                  # 지어내지 않는다
    assert humanize("기준값 0; 시점 1999 값 없음; 기준값 0") == "기준 값이 0이라 비율을 계산할 수 없습니다; 1999년 값이 없습니다"
    assert humanize(None) is None and humanize("") == ""


def test_user_sees_humanized_reason_everywhere_but_calc_result_keeps_original():
    bad = growth(value=None).model_copy(update={"note": "시점 1999 값 없음"})
    req = Module6Request(query_bundle=QueryBundle(original="q"), records=[view()], calc_results=[bad], displays=DISPLAYS)
    f = Facts(req)
    assert sentence(f, bad) == "혼인건수 증감률을 계산하지 못했습니다(1999년 값이 없습니다)."
    assert build_caveats(f)[0].text == "혼인건수 증감률을 계산하지 못했습니다: 1999년 값이 없습니다"
    assert build_tables(f)[0].rows[0][4] == "1999년 값이 없습니다"
    assert "사유: 1999년 값이 없습니다" in build_prompt(f, [])
    assert req.calc_results[0].note == "시점 1999 값 없음"                              # 원문은 그대로 (QA · 개발자용)


# ── 일부 시점만 계산 불가인 목록 ─────────────────────────────────
def partial_diff() -> Facts:
    pts = [{"key": {"시점": "2008"}, "value": None}, {"key": {"시점": "2009"}, "value": 6339579}]
    ins = [{**inp("2008", 9401622, "인구수(명)", rid="view::pop"), "role": "a", "key": {"행정구역별": "서울특별시", "시점": "2008"}},
           {**inp("2009", 9861567, "인구수(명)", rid="view::pop"), "role": "a", "key": {"행정구역별": "서울특별시", "시점": "2009"}},
           {**inp("2009", 3521988, "인구수(명)", rid="view::pop"), "role": "b", "key": {"행정구역별": "부산광역시", "시점": "2009"}}]
    r = CalcResult.model_validate({"step_id": "a1", "op": "diff", "unit": "명", "display_ref": "d2", "value": pts, "inputs": ins,
                                   "record_ids": ["view::pop"], "note": "{'시점': '2008'}: 한쪽 값 없음"})
    return Facts(Module6Request(query_bundle=QueryBundle(original="q"), records=[REC], calc_results=[r], displays=DISPLAYS))


def test_failed_point_in_a_list_is_not_citable_and_is_shown_as_unavailable():
    from backend.agent.answer_compose.placeholder import fill
    f = partial_diff()
    prompt = build_prompt(f, [])
    assert "2008년: 계산 불가 (자리표시자 없음)" in prompt and "{a1.r0}" not in prompt and "{a1.r1}" in prompt
    assert fill("{a1.r0}", f).problems == ["계산하지 못한 값을 인용함: {a1.r0} (2008년)"]
    assert fill("{a1.r1}", f).problems == []
    assert build_tables(f)[0].rows == [["2008", "계산 불가"], ["2009", "6,339,579건"]]
    assert build_caveats(f)[0].text == "인구수 차이: 2008년은 부산광역시 인구수 값이 없어 계산하지 못했습니다"


def test_missing_side_is_named_from_inputs():
    f = partial_diff()
    r = f.req.calc_results[0]
    assert humanize(r.note, r.inputs) == "2008년은 부산광역시 인구수 값이 없어 계산하지 못했습니다"
    assert humanize(r.note) == "2008년은 한쪽 값이 없어 계산하지 못했습니다"                 # inputs 가 없으면 예전 문구
    flipped = [i.model_copy(update={"role": {"a": "b", "b": "a"}[i.role]}) for i in r.inputs]   # a · b 이름이 바뀌어도 빠진 것은 부산
    assert humanize(r.note, flipped) == "2008년은 부산광역시 인구수 값이 없어 계산하지 못했습니다"
    neither = [i for i in r.inputs if i.key["시점"] != "2008"]                                # 두 쪽 모두 2008년 값이 없을 때
    assert humanize(r.note, neither) == "2008년은 양쪽 값이 없어 계산하지 못했습니다"
    only_a = [i for i in r.inputs if i.role == "a"]                                            # 쪽을 구분할 수 없으면 일반 문구
    assert humanize(r.note, only_a) == "2008년은 한쪽 값이 없어 계산하지 못했습니다"


def test_combine_missing_term_names_the_item():
    assert humanize("{'시점': '2008'}: 값 없음 (사망자수)") == "2008년은 사망자수 값이 없어 계산하지 못했습니다"
    assert humanize("{'시점': '2008'}: 키 중복 (출생아수: 짝지을 키마다 값이 하나여야 함)") ==         "2008년은 출생아수에 같은 조건의 값이 여러 개라 계산하지 못했습니다"


# ── 고정 대상 (지역 · 성별 · 연령) ───────────────────────────────
COLS = ["시점", "행정구역별", "성별", "항목", "값"]
ROWS = [[y, p, g, "인구수(명)", v] for y, vs in (("2021", (900, 1000, 1900)), ("2025", (950, 1100, 2050)))
        for p in ("서울특별시", "전국") for g, v in zip(("남자", "여자", "계"), vs if p == "서울특별시" else tuple(x * 5 for x in vs))]
REC = view(ROWS, COLS, rid="view::pop")


def pop(year, value, *, rid="view::pop"):
    return {**inp(year, value, "인구수(명)", rid=rid), "unit": "명"}


def result(ins, **kw) -> CalcResult:
    return CalcResult.model_validate({"step_id": "a1", "record_ids": ["view::pop"], "inputs": ins, **kw})


def facts_of(r) -> Facts:
    return Facts(Module6Request(query_bundle=QueryBundle(original="q"), records=[REC], calc_results=[r],
                                displays={"d1": DISPLAYS["d1"], "d2": DISPLAYS["d2"]}))


def test_fixed_text_restores_place_and_sex_missing_from_input_key():
    r = result([pop("2021", 1000), pop("2025", 1100)], op="growth_rate", value=10.0, unit="%", display_ref="d1")
    f = facts_of(r)
    assert f.fixed_text(r) == "서울특별시 여자"                      # 값 1000 · 1100 은 서울 여자 행에만 있다
    assert sentence(f, r) == "서울특별시 여자 인구수는 2021년 1,000명에서 2025년 1,100명으로 10.0% 증가했습니다."


def test_summary_and_list_titles_carry_the_fixed_target():
    r = result([pop("2021", 900), pop("2025", 950)], op="growth_rate", value=5.6, unit="%", display_ref="d1")
    assert build_tables(facts_of(r))[0].rows[0][0] == "서울특별시 남자 인구수 증감률"


def test_total_rows_and_ambiguous_rows_are_not_used():
    total = result([pop("2021", 1900), pop("2025", 2050)], op="growth_rate", value=7.9, unit="%", display_ref="d1")
    assert facts_of(total).fixed_text(total) == "서울특별시"                    # 성별 '계'(총계)는 뺀다
    unknown = result([pop("2021", 123456), pop("2025", 1)], op="growth_rate", value=1.0, unit="%", display_ref="d1")
    assert facts_of(unknown).fixed_text(unknown) == ""                           # 값이 맞는 행이 없으면 지어내지 않는다
    gone = result([pop("2021", 1000, rid="view::none")], op="raw", value=1000, unit="명", display_ref="d2")
    assert facts_of(gone).fixed_text(gone) == ""


def test_columns_already_in_key_are_not_repeated():
    keyed = {**pop("2021", 1000), "key": {"행정구역별": "서울특별시", "시점": "2021"}}
    r = result([keyed], op="raw", value=1000, unit="명", display_ref="d2")
    assert facts_of(r).fixed_text(r) == "여자"                                   # 지역은 key 에 있어 문장이 이미 쓴다


def test_prompt_and_numbers_know_the_fixed_target():
    r = result([pop("2021", 900), pop("2025", 950)], op="growth_rate", value=5.6, unit="%", display_ref="d1")
    assert "    대상: 서울특별시 남자" in build_prompt(facts_of(r), [])
