"""[NEW 11-12] 144문항 비교에서 나온 수정 중 질의 분석 v3 부분 확인 (HCX·데이터 없음)
1) 시군구 추출 · 시도 앞글자 오인   2) 계산 단어   3) 개념 묶기   — 4) 조건 확인은 tests/v4/test_resolve_1112.py"""
from datetime import date

from backend.rag.query_analyzer.extract import rule_extract
from backend.rag.query_analyzer.measures import concept_groups
from backend.rag.query_analyzer.terms import lookup_terms
from backend.rag.query_analyzer.validate import validate_slots

TODAY = date(2026, 11, 12)


def _v(q, hcx, subs=()):
    q2, found, _ = rule_extract(q, TODAY)
    return validate_slots({"question": q, "input_question": q2, "rule_found": found, "term_hits": lookup_terms(q2),
                           "hcx_slots": {**hcx, "의도": hcx.get("의도", "값 조회")}, "hcx_subs": list(subs)})


# ── 1) 시군구 ──
def test_sigungu_extract():
    region = lambda q: rule_extract(q, TODAY)[1].get("지역")
    assert region("2018년 부산진구의 국제결혼 이주자의 수") == ["부산진구"]          # 이전: 부산광역시
    assert region("1990년 화성군의 일반가구 중 보증부월세 비율") == ["화성군"]
    assert region("2010년 수원시 권선구에 사는 일반 가정") == ["수원시 권선구"]        # 이어진 시·구는 값 하나
    assert region("2022년 서울특별시 도봉구의 총인구수") == ["서울특별시", "도봉구"]
    assert region("1980년에 대구시에서 슬레이트 집") == ["대구광역시"]                # '대구시' 는 시도
    assert region("대구 중구 인구") == ["대구광역시", "중구"]
    assert region("시도별 성별 출산순위별 출생시 체중별 출생 중 서울특별시") == ["서울특별시"]   # '출생시' 는 지역 아님
    assert region("1995년 시도별 고령자가구가 49,000가구 이하인 지역") is None        # '고령자가구' 는 지역 아님
    assert region("경기 침체 시기 인구") is None


def test_sigungu_fill_when_hcx_drops():
    v = _v("1995년에 가평군에서 보증부월세로 사는 집의 수", {"시점": ["1995년"], "대상": ["주택"], "지표": ["주택수"]})
    assert v["slots"]["지역"] == ["가평군"]                                          # HCX 가 빠뜨려도 코드가 채움
    v = _v("2010년 수원시 권선구에 사는 일반 가정", {"지역": ["수원시"], "대상": ["일반가구"]})
    assert v["slots"]["지역"] == ["수원시 권선구"]                                   # HCX 가 넓은 앞부분만 쓰면 바꿈
    v = _v("2010년 수원시 권선구에 사는 일반 가정", {"지역": ["권선구"], "대상": ["일반가구"]})
    assert v["slots"]["지역"] == ["권선구"]                                          # 끝부분을 썼으면 그대로


def test_sub_inherits_main_region():
    v = _v("2022년 대전 출생아 수와 사망자 수", {"지역": ["대전광역시"], "지표": ["출생아수", "사망자수"]},
           [{"지표": ["출생아수"]}, {"지표": ["사망자수"]}])
    assert [x["지역"] for x in v["sub_slots"]] == [["대전광역시"], ["대전광역시"]]


# ── 2) 계산 단어 · 의도 단어 ──
def test_measure_words_leave_indicator():
    v = _v("1990년 화성군에서 일반가구 중 보증부월세 가구의 비율", {"대상": ["일반가구"], "지표": ["가구수", "구성비"]})
    assert v["slots"]["지표"] == ["가구수"] and v["slots"]["의도"] == ["구성비"]    # 구성비는 의도로
    v = _v("2020년 대비 2025년 시군구간 전입 증감률", {"지표": ["전입 증감률", "변화폭(%p)"]})
    assert v["slots"]["지표"] == ["전입"] and v["slots"]["의도"] == ["증감률"]
    v = _v("누적 출산 비율 2016년과 2023년", {"지표": ["누적 출산 비율"], "의도": "추이"})
    assert v["slots"]["지표"] == ["누적 출산 비율"]                                   # 표 이름에 쓰이는 '비율'은 남김


# ── 3) 개념 묶기 ──
def test_concept_groups():
    def shape(t, i):
        return [(c["대상"], c["지표"]) for c in concept_groups(t, i)]
    assert shape(["국제결혼 이주자"], ["인구수"]) == [(["국제결혼 이주자"], ["인구수"])]                 # 나누지 않음
    assert shape(["외국인근로자", "국제결혼가정 자녀"], ["인구수", "증감률"]) == \
        [(["외국인근로자"], ["인구수"]), (["국제결혼가정 자녀"], ["인구수"])]
    assert shape(["주택", "인구"], ["가구수", "인구수"]) == [(["주택"], ["가구수"]), (["인구"], ["인구수"])]
    assert shape(["일반가구"], ["구성비"]) == [(["일반가구"], [])]                                     # 계산 단어는 개념 아님
    assert shape([], ["인구수", "총인구수"]) == [([], ["총인구수", "인구수"])]                         # 이름이 겹치면 하나
    assert shape(["인구"], ["인구수", "순이동자수"]) == [([], ["순이동자수"]), (["인구"], ["인구수"])]
    assert len(shape([], ["혼인건수", "출생아수", "사망자수"])) == 3


def test_code_split_keeps_target_with_generic():
    v = _v("2018년 부산진구의 국제결혼 이주자의 수는 2015년에 비해", {"시점": ["2015년", "2018년"], "대상": ["국제결혼 이주자"],
                                                                   "지표": ["인구수"], "의도": "증감"})
    assert v["sub_slots"] == []                                                       # 이전: '인구' / '국제결혼 이주자' 로 나뉨


