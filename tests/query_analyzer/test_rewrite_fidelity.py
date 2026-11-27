"""재작성 충실도 — 11-19 오답 분석(8문항 중 5문항이 재작성에서 시작)과 '최근 N년' 시점 축소 (HCX·데이터 없음)

HCX 응답은 보고서에 적힌 실제 재작성 결과를 그대로 흉내 냄. 확인하는 것:
  0) '최근 5년' · '최근 20년' + '변했어' → 시점이 양 끝 [2021, 2025] 로 줄지 않음 (코드 · HCX 둘 다)
  1) 대상 상위어('국제결혼 이주자' → '외국인') 되돌림 · 두 해 비교의 '증감 추이' → '증감'
  2) '가구원수' → '평균 가구원수' 되돌림 · 숫자 조건 '99,000' 을 조건 칸에서 빼고 기준(thresholds)으로
  3) 'X 중 Y가 차지하는 비율' → 의도 구성비 · 지표 가구수 · 조건 Y · 분모 단위에 역할 표시
  모듈 2 의 measure 규칙(재작성 문장 끝 의도어 → intent)에 넣어 change / share 가 나오는지도 봄
"""
from datetime import date

from backend.agent.chart_decision.chart_decision_module import decide_measure_rule
from backend.rag.query_analyzer.analyze import refresh_rewritten, restore_targets, unsupported_targets
from backend.rag.query_analyzer.extract import recent_spans, rule_extract
from backend.rag.query_analyzer.rewrite import make_bundle
from backend.rag.query_analyzer.roles import add_role_units, find_roles, find_thresholds
from backend.rag.query_analyzer.sentence import build_sentences, slots_to_sentence
from backend.rag.query_analyzer.terms import lookup_terms
from backend.rag.query_analyzer.validate import validate_slots

TODAY = date(2026, 11, 19)
YEARS_5 = [f"{y}년" for y in range(2021, 2026)]


def _v(q, hcx, subs=(), today=TODAY):
    """build_slot_messages 와 같은 입력으로 검증 (HCX 응답만 가짜)"""
    q2, found, _ = rule_extract(q, today)
    full = {k: [] for k in ["시점", "지역", "전출지", "전입지", "국적", "대상", "성별", "연령", "조건", "이동", "지표", "비교축"]}
    return validate_slots({"question": q, "input_question": q2, "rule_found": found, "term_hits": lookup_terms(q2),
                           "time_spans": recent_spans(q, today),
                           "hcx_slots": {**full, **hcx, "의도": hcx.get("의도", ["값 조회"])},
                           "hcx_subs": [{**full, **x} for x in subs]})


def _measure(v, q):
    """모듈 2 규칙 measure — 분석이 넘기는 것과 같게 (rewritten · 첫 의도)"""
    b = make_bundle(q, v, build_sentences(v))
    qb = {"original": q, "rewritten": b.rewritten, "intent": [b.intent] if b.intent else []}
    return decide_measure_rule(b.rewritten, qb)[0], b


# ── 0) 최근 N년 ───────────────────────────────────────────────
def test_recent_years_not_shrunk_by_code():
    for q, n in (("최근 5년 혼인건수 얼마나 변했어?", 5), ("최근 20년 출생아수 얼마나 줄었어?", 20),
                 ("지난 10년간 이혼건수 변화", 10), ("최근 3개년 인구 몇 명 늘었어", 3)):
        q2, found, notes = rule_extract(q, TODAY)
        assert found["시점"] == [f"{y}년" for y in range(2026 - n, 2026)], (q, found, notes)
    assert recent_spans("최근 20년 출생아수", TODAY) == [(2006, 2025)]
    assert rule_extract("최근 5년 전국 인구", TODAY)[1]["지역"] == ["전국"]  # '5년 전국' 을 '5년 전' 으로 읽지 않음
    assert recent_spans("지난해 인구", TODAY) == []
    # 명시한 두 시점 범위('A년부터 B년까지 얼마나 변했나')는 예전처럼 양 끝 (5년 주기 표가 뒤로 밀리지 않게)
    assert rule_extract("2015년부터 2020년까지 인구 얼마나 변했나", TODAY)[1]["시점"] == ["2015년", "2020년"]


def test_recent_years_restored_when_hcx_shrinks():
    q = "최근 5년 혼인건수 얼마나 변했어?"
    v = _v(q, {"시점": ["2021년", "2025년"], "대상": ["혼인"], "지표": ["혼인건수"], "의도": ["증감"]})
    assert v["slots"]["시점"] == YEARS_5
    assert v["slots"]["의도"] == ["증감", "추이"]  # 5년치 값 + 2021 대비 2025 증감
    m, b = _measure(v, q)
    assert b.rewritten == "2021~2025년 혼인건수 추이 증감" and b.intent == "증감" and m == "change"  # 질문에 없는 '전국' 은 넣지 않음
    # HCX 가 '추이' 로만 읽어도 변화 표현이 있으면 증감
    v = _v(q, {"시점": ["2021년", "2025년"], "대상": ["혼인"], "지표": ["혼인건수"], "의도": ["추이"]})
    assert v["slots"]["의도"] == ["증감", "추이"] and _measure(v, q)[0] == "change"


def test_recent_years_restored_in_sub_questions():
    q = "최근 5년 혼인건수와 이혼건수 얼마나 변했어?"
    v = _v(q, {"시점": ["2021년", "2025년"], "대상": ["혼인", "이혼"], "지표": ["혼인건수", "이혼건수"], "의도": ["증감"]},
           [{"시점": ["2021년", "2025년"], "대상": ["혼인"], "지표": ["혼인건수"], "의도": "증감"},
            {"대상": ["이혼"], "지표": ["이혼건수"], "의도": "추이"}])
    assert [x["시점"] for x in v["sub_slots"]] == [YEARS_5, YEARS_5]
    assert [x["의도"] for x in v["sub_slots"]] == ["증감", "증감"]
    assert build_sentences(v)["sub_questions"][0].endswith("혼인건수 증감")


def test_twenty_years():
    q = "최근 20년 출생아수 얼마나 줄었어?"
    v = _v(q, {"시점": ["2006년", "2025년"], "대상": ["출생아"], "지표": ["출생아수"], "의도": ["증감"]})
    assert v["slots"]["시점"][0] == "2006년" and len(v["slots"]["시점"]) == 20


def test_trend_question_keeps_trend():
    q = "최근 5년 혼인건수 변화 추이"  # 흐름을 물음 → 증감으로 바꾸지 않음
    v = _v(q, {"시점": YEARS_5, "대상": ["혼인"], "지표": ["혼인건수"], "의도": ["추이"]})
    assert v["slots"]["의도"] == ["추이"] and _measure(v, q)[0] == "raw"


# ── 1) 대상 상위어 · 두 해 비교 ─────────────────────────────────
Q1 = "부산진구에 사는 국제결혼 이주자가 2015년과 2018년을 비교했을 때 몇 명 늘거나 줄었나요?"
HCX1 = {"시점": ["2015년", "2018년"], "지역": ["부산진구"], "대상": ["외국인"], "지표": ["인구수"], "비교축": ["연도"],
        "의도": ["증감", "추이"]}


def test_two_year_change_is_not_trend():
    v = _v(Q1, HCX1)
    assert v["slots"]["의도"] == ["증감"] and v["slots"]["비교축"] == []
    assert build_sentences(v)["rewritten"] == "2015년, 2018년 부산진구 외국인 인구수 증감"
    assert _measure(v, Q1)[0] == "change"  # 예전: '… 연도별 증감 추이' → raw


def test_target_hypernym_restored_from_question():
    v = _v(Q1, HCX1)
    state = {"bundle": {"rewritten": build_sentences(v)["rewritten"], "sub_questions": []}, "sub_slots": [],
             "sub_intents": [], "intents": v["slots"]["의도"], "thresholds": v["thresholds"]}
    raw = {k: x for k, x in v["slots"].items() if k != "의도" and x}
    assert unsupported_targets(raw, Q1, lookup_terms(Q1)) == ["외국인"]
    raw2, _, swapped = restore_targets(raw, [], Q1, ["국제결혼 이주자"], lookup_terms(Q1))
    assert raw2["대상"] == ["국제결혼 이주자"] and swapped == [("외국인", ["국제결혼 이주자"])]
    # 보고서의 정답 재작성과 같은 문장 (모듈 3 이 표 항목 '국제결혼 이주자' 와 맞춤)
    assert refresh_rewritten(state, raw2)["bundle"]["rewritten"] == "2015년, 2018년 부산진구 국제결혼 이주자 인구수 증감"
    # 원문 표현이 없으면 그대로
    assert restore_targets(raw, [], Q1, [], ())[2] == []


def test_supported_targets_are_kept():
    assert unsupported_targets({"대상": ["이혼"]}, "갈라서는 부부 늘었어?", [("갈라서", ["이혼건수"])]) == []  # 용어 사전
    assert unsupported_targets({"대상": ["인구"]}, "대구 사람 몇 명", []) == []  # 일반 말
    assert unsupported_targets({"대상": ["결혼이민자"]}, "베트남 결혼이민자 시도별", []) == []  # 질문에 있음
    assert unsupported_targets({"대상": ["출생아"]}, "출생아수 추이", []) == []  # 겹침


# ── 2) 가구원수 · 숫자 조건 ─────────────────────────────────────
Q2 = "2000년 행정구역별로 가구원수가 99,000명 이상인 지역에서 2인 가구의 수는?"
Q2P = "2000년에 가구원수가 99,000명 이상인 지역들 중에서 2인 가구는 몇 집이나 되나요?"


def test_household_members_not_average_and_condition_kept():
    v = _v(Q2, {"시점": ["2000년"], "대상": ["가구"], "지표": ["평균가구원수", "2인 가구수"], "비교축": ["행정구역"]},
           [{"시점": ["2000년"], "대상": ["가구"], "지표": ["평균가구원수"], "비교축": ["행정구역"], "의도": "값 조회"},
            {"시점": ["2000년"], "대상": ["가구"], "지표": ["2인 가구수"], "비교축": ["행정구역"], "의도": "값 조회"}])
    assert v["slots"]["지표"] == ["2인 가구수"]  # 가구원수는 지역을 고르는 기준 → 조건 단위로
    assert v["sub_slots"] == []
    assert [(t["말"], t["op"], t["값"]) for t in v["thresholds"]] == [("가구원수", ">=", 99000)]
    assert "가구원수 99,000명 이상" in build_sentences(v)["rewritten"]
    assert any("되돌림(질문에 '평균' 없음)" in x and x.endswith("→ 가구원수") for x in v["log"])
    assert find_roles(Q2) == [("조건", "가구원수")]


def test_number_only_condition_removed():
    v = _v(Q2P, {"시점": ["2000년"], "대상": ["가구"], "지표": ["평균가구원수", "2인 가구수"], "조건": ["99,000"],
                 "비교축": ["지역"], "의도": ["합계"]})
    assert v["slots"]["조건"] == [] and v["slots"]["지표"] == ["2인 가구수"]
    assert v["thresholds"][0]["표기"] == "99,000명 이상" and v["thresholds"][0]["지역_고르기"]


def test_category_threshold_keeps_indicator():
    # '가구원수가 5명 이상인 가구' 는 분류 값 기준 (지역을 고르는 기준이 아님) → 지표에서 빼지 않음
    t = find_thresholds("2020년 가구원수가 5명 이상인 가구 수")
    assert t[0]["지역_고르기"] is False
    v = _v("2020년 가구원수가 5명 이상인 가구 수", {"시점": ["2020년"], "대상": ["가구"], "지표": ["가구원수", "가구수"]})
    assert v["slots"]["지표"] == ["가구원수", "가구수"]


def test_average_kept_when_asked():
    v = _v("2020년 전국 평균 가구원수", {"시점": ["2020년"], "대상": ["가구"], "지표": ["평균 가구원수"]})
    assert v["slots"]["지표"] == ["평균 가구원수"]


# ── 3) 'X 중 Y가 차지하는 비율' ────────────────────────────────
Q3 = "1990년 화성군의 일반가구 중 보증부월세가 차지하는 비율은?"
Q3P = "1990년 화성군에서 전체 일반가구 중에서 보증부월세로 거주하는 가구의 비율은 얼마나 될까요?"


def test_share_of_reads_as_composition():
    v = _v(Q3, {"시점": ["1990년"], "지역": ["화성군"], "대상": ["일반가구"], "지표": ["보증부월세비율"]},
           [{"시점": ["1990년"], "지역": ["화성군"], "지표": ["보증부월세비율"], "의도": "값 조회"},
            {"시점": ["1990년"], "지역": ["화성군"], "대상": ["일반가구"], "의도": "값 조회"}])
    s = v["slots"]
    assert (s["의도"], s["대상"], s["지표"], s["조건"]) == (["구성비"], ["일반가구"], ["가구수"], ["보증부월세"])
    assert v["sub_slots"] == []  # 분모만 담은 하위 질문은 빼고 역할 단위로
    m, b = _measure(v, Q3)
    assert b.rewritten == "1990년 화성군 보증부월세 일반가구 가구수" and m == "share"


def test_share_of_colloquial():
    v = _v(Q3P, {"시점": ["1990년"], "지역": ["화성군"], "대상": ["일반가구"], "지표": ["가구수"], "조건": ["보증부월세"]},
           [{"시점": ["1990년"], "지역": ["화성군"], "대상": ["일반가구"], "지표": ["가구수"], "조건": ["보증부월세"], "의도": "값 조회"},
            {"시점": ["1990년"], "지역": ["화성군"], "대상": ["일반가구"], "조건": ["보증부월세"], "의도": "값 조회"}])
    assert v["slots"]["의도"] == ["구성비"] and v["sub_slots"] == []
    assert _measure(v, Q3P)[0] == "share"


def test_rate_indicator_question_is_not_composition():
    q = "2023년 전국 인구 중 고령인구비율은?"
    v = _v(q, {"시점": ["2023년"], "대상": ["인구"], "지표": ["고령인구비율"]})
    assert v["slots"]["의도"] == ["값 조회"] and v["slots"]["지표"] == ["고령인구비율"]


def test_denominator_role_added_even_if_sentence_mentions_it():
    # 하위 문장이 '일반가구' 를 담았어도 조건(보증부월세)이 붙은 단위는 분모가 아님 → 역할 단위를 더함
    vb = {"filters": {"시점": [1990], "지역": ["화성군"], "대상": ["일반가구"]}, "search_text": "보증부월세 일반가구 가구수",
          "sub_questions": ["1990년 화성군 보증부월세 일반가구 가구수", "1990년 화성군 보증부월세 일반가구"],
          "sub_filters": [{"조건": ["보증부월세"], "대상": ["일반가구"]}, {"조건": ["보증부월세"], "대상": ["일반가구"]}]}
    assert add_role_units(Q3P, vb) == [("분모", "일반가구")]
    assert vb["sub_filters"][-1]["역할"] == "분모"  # 맨 뒤 (modules.split_roles 가 떼어 냄)
    # 분모만 담은 단위가 이미 있으면 예전처럼 더하지 않음
    vb2 = {"filters": {"시점": [1990]}, "sub_questions": ["보증부월세 가구수", "일반가구"],
           "sub_filters": [{"조건": ["보증부월세"]}, {"대상": ["일반가구"]}]}
    assert add_role_units(Q3, vb2) == []


# ── 문장 ─────────────────────────────────────────────────────
def test_sentence_puts_calc_intent_last():
    base = {"시점": ["2015년", "2018년"], "대상": ["출생아"], "지표": ["출생아수"]}
    assert slots_to_sentence({**base, "의도": ["증감", "추이"]}) == "2015년, 2018년 출생아수 추이 증감"
    assert slots_to_sentence({**base, "의도": ["순위", "추이"]}) == "2015년, 2018년 출생아수 추이 순위"
    assert slots_to_sentence({**base, "의도": "증감"}, extra=["출생아수 1,000명 이상"]) == \
        "2015년, 2018년 출생아수 1,000명 이상 출생아수 증감"
