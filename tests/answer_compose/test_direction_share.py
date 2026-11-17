"""[NEW] 방향 단어 검사(placeholder.direction_problems), share 분모 표기, 목록 문장의 '외 N개'"""
from backend.agent.answer_compose.facts import Facts
from backend.agent.answer_compose.placeholder import check, fill
from backend.agent.answer_compose.tables import build_tables
from backend.agent.answer_compose.template import sentence
from backend.agent.answer_compose.write import build_prompt
from backend.schemas.chart import CalcResult
from tests.answer_compose._data import growth, inp, request
from tests.chart_calculate._views import VID

def calc(value, ins, step_id="a1") -> CalcResult:
    return CalcResult.model_validate({**growth(step_id).model_dump(), "value": value, "inputs": ins})


DOWN = calc(-2.3875315663834327, [inp("2021", 260562), inp("2025", 254341)])      # 줄어든 계산
NEG_BASE = calc(-50.0, [inp("2021", -100), inp("2025", -50)])                      # -100 → -50: 값은 -50% 지만 50 늘었다


def problems(text, *results):
    f = Facts(request(results=list(results)))
    return check(text, fill(text, f), f, [])


# ── 방향 ─────────────────────────────────────────────────────────
def test_negative_value_written_as_increase_is_rejected():
    p = problems("혼인건수는 {a1.abs} 증가했습니다.", DOWN)
    assert len(p) == 1 and p[0].startswith("방향이 맞지 않음: {a1} 은 감소인데 반대로 씀")


def test_positive_value_written_as_decrease_is_rejected():
    assert "{a1} 은 증가인데 반대로 씀" in problems("혼인건수는 {a1.abs} 감소했습니다.", growth())[0]


def test_matching_direction_passes_for_all_words():
    assert problems("혼인건수는 {a1.abs} 감소했습니다.", DOWN) == []
    assert problems("혼인건수는 {a1.abs} 줄었습니다.", DOWN) == []
    assert problems("혼인건수는 {a1.abs} 늘었습니다.", growth()) == []


def test_direction_follows_end_minus_start_not_the_sign_of_the_rate():
    """기준값이 음수인 지수 · 증감률은 값의 부호가 방향과 반대일 수 있다. 방향은 두 값의 차이로 본다"""
    assert problems("순이동은 {a1.abs} 증가했습니다.", NEG_BASE) == []
    assert "{a1} 은 증가인데 반대로 씀" in problems("순이동은 {a1.abs} 감소했습니다.", NEG_BASE)[0]


def test_rate_words_and_mixed_words_do_not_trigger():
    assert problems("연평균 증가율은 {a1} 입니다.", DOWN) == []                       # '증가율' 은 방향이 아니다
    assert problems("한때 증가했지만 결국 {a1.abs} 감소했습니다.", DOWN) == []         # 두 방향 단어가 같이 있으면 판단하지 않는다


def test_each_sentence_is_checked_separately_and_two_calcs_in_one_sentence_are_skipped():
    two = [growth(), DOWN.model_copy(update={"step_id": "a2"})]
    assert problems("혼인건수는 {a1.abs} 증가했습니다. 출생아수는 {a2.abs} 감소했습니다.", *two) == []
    assert len(problems("혼인건수는 {a1.abs} 증가했습니다. 출생아수는 {a2.abs} 증가했습니다.", *two)) == 1     # 둘째 문장만 틀림
    assert problems("혼인건수는 {a1.abs} 증가했고 출생아수는 {a2.abs} 감소했습니다.", *two) == []


def test_zero_and_diff_are_not_checked():
    assert problems("혼인건수는 {a1} 증가했습니다.", growth(value=0)) == []
    diff = CalcResult.model_validate({"step_id": "a1", "op": "diff", "value": -5, "unit": "건", "display_ref": "d2",
                                      "inputs": [inp("2025", 1), inp("2025", 6)]})
    assert problems("차이는 {a1.abs} 증가했습니다.", diff) == []


# ── share 분모 ───────────────────────────────────────────────────
def share(total=True, label="전국 대비", **kw) -> CalcResult:
    ins = [{**inp("2025", 9299548, "인구수(명)", unit="명"), "role": "part"}]
    if total:
        ins.append({**inp("2025", 51325329, "인구수(명)", unit="명"), "role": "total", "key": {"행정구역별": "전국", "시점": "2025"}})
    return CalcResult.model_validate({"step_id": "a1", "op": "share", "value": 18.1, "unit": "%", "display_ref": "d1",
                                      "scope_label": label, "inputs": ins, "record_ids": [VID], **kw})


def test_denominator_uses_scope_label_and_total_input():
    f = Facts(request(results=[share()]))
    assert f.denominator(f.results["a1"]) == "전국 대비 — 인구수 전국 2025년 51,325,329명"
    assert sentence(f, f.results["a1"]) == "인구수의 비중은 18.1%입니다. (분모: 전국 대비 — 인구수 전국 2025년 51,325,329명)"


def test_denominator_when_selected_scope_or_no_label():
    f = Facts(request(results=[share(total=False, label="선택 항목 내 비중")]))
    assert f.denominator(f.results["a1"]) == "선택 항목 내 비중"
    g = Facts(request(results=[share(label=None)]))
    assert g.denominator(g.results["a1"]) == "인구수 전국 2025년 51,325,329명"
    assert Facts(request()).denominator(Facts(request()).results["a1"]) is None            # share 가 아니면 없음


def test_denominator_in_summary_note_and_prompt():
    f = Facts(request(results=[share()]))
    summary = build_tables(f)[0]
    assert summary.rows[0][4] == "분모: 전국 대비 — 인구수 전국 2025년 51,325,329명"
    prompt = build_prompt(f, [])
    assert "분모: 전국 대비 — 인구수 전국 2025년 51,325,329명 (분모 값 {a1.in1}, 미리보기: 51,325,329명)" in prompt


def test_share_list_has_denominator_in_sentence_and_table_title():
    pts = [{"key": {"행정구역별": r, "시점": "2025"}, "value": v} for r, v in [("서울", 18.1), ("부산", 6.4)]]
    r = share().model_copy(update={"value": pts})
    f = Facts(request(results=[r]))
    assert sentence(f, r).endswith("입니다. (분모: 전국 대비 — 인구수 전국 2025년 51,325,329명)")
    assert [t for t in build_tables(f) if t.table_id == "t_a1"][0].title.endswith("(분모: 전국 대비 — 인구수 전국 2025년 51,325,329명)")


# ── 목록 '외 N개' ────────────────────────────────────────────────
def test_list_sentence_shows_five_then_remaining_count():
    regions = ["의성군", "군위군", "청송군", "영양군", "봉화군", "고령군", "성주군", "영덕군"]
    r = CalcResult.model_validate({
        "step_id": "a1", "op": "rank", "unit": "%", "display_ref": "d1", "inputs": [inp("2025", 1, "고령인구비율(%)", unit="%")],
        "value": [{"key": {"행정구역별": n, "시점": "2025"}, "value": 46.3 - i, "rank": i + 1} for i, n in enumerate(regions)]})
    text = sentence(Facts(request(results=[r])), r)
    assert text == ("2025년 고령인구비율 순위는 1위 의성군 46.3%, 2위 군위군 45.3%, 3위 청송군 44.3%, "
                    "4위 영양군 43.3%, 5위 봉화군 42.3% 외 3개입니다.")      # 모든 항목의 시점이 같으면 앞에 한 번만


def test_common_key_only_when_other_part_still_tells_items_apart():
    def rank(keys):
        return CalcResult.model_validate({"step_id": "a1", "op": "rank", "unit": "건", "display_ref": "d2", "inputs": [inp("2025", 1)],
                                          "value": [{"key": k, "value": 100 - i, "rank": i + 1} for i, k in enumerate(keys)]})
    both = rank([{"행정구역별": "서울", "시점": "2024"}, {"행정구역별": "서울", "시점": "2025"}, {"행정구역별": "부산", "시점": "2025"}])
    f = Facts(request(results=[both]))
    assert "1위 서울 2024년 100건" in sentence(f, both)                                      # 공통 열이 없으면 그대로
    same_region = rank([{"행정구역별": "서울", "시점": "2024"}, {"행정구역별": "서울", "시점": "2025"}])
    assert sentence(Facts(request(results=[same_region])), same_region) == "서울 혼인건수 순위는 1위 2024년 100건, 2위 2025년 99건입니다."
    identical = rank([{"시점": "2025"}, {"시점": "2025"}])                                    # 구분할 이름이 사라지면 묶지 않는다
    assert "1위 2025년 100건, 2위 2025년 99건" in sentence(Facts(request(results=[identical])), identical)
