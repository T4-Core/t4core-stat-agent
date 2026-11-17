"""표 검색 — 실제 실행(144문항)에서 보인 실패 유형을 작은 코퍼스로 재현 (HCX·저장소 파일 없음)

표 프로필은 실제 KOSIS 표의 이름·항목·기간을 줄인 것. 같은 이름의 연도판(1985·1990·1995), 시도판/시군구판,
(계)/(2008~2015) 형제 표가 같이 들어 있다.
"""
import pytest

from backend.rag.ingestion.table_text import table_text
from backend.rag.search.index import Doc
from backend.rag.search.query import parse_question
from backend.rag.search.engine import TableSearch

SIDO = ["서울특별시", "부산광역시", "경기도", "전라남도", "인천광역시"]


def _regions(level):
    geo = {"전국": 1, "시도": 17} if level == "시도" else {"전국": 1, "시도": 17, "시군구": 230}
    return {"kind": "regions", "obj_nm": f"행정구역({level})별", "names": ["전국", *SIDO], "sido": SIDO, "n_codes": sum(geo.values()),
            "geo_types": geo}


def _dim(obj, names, kind="other"):
    return {"kind": kind, "obj_nm": obj, "names": names, "n_codes": len(names)}


def P(tid, name, survey, years, items, levels=(), se="년", unit="명"):
    return {"tbl_id": tid, "tbl_nm": name, "survey_nm": survey, "path": survey, "units": [unit],
            "items": [{"name": i, "unit": unit} for i in items], "levels": list(levels),
            "periods": [{"se": "M" if se == "월" else "Y", "se_raw": se, "year_from": years[0], "year_to": years[1]}]}


SEX = _dim("성별", ["계", "남자", "여자"], "sex")
OCC = _dim("점유형태별", ["계", "자기집", "전세", "보증부월세", "무보증월세", "사글세", "무상"])
PROFILES = [
    P("TX_A008_A", "한국국적을 가지지 않은 자-결혼이민자(계)", "지방자치단체외국인주민현황", (2015, 2024), ["국제결혼 이주자"], [_regions("시군구")]),
    P("TX_A011", "한국국적을 가지지 않은 자-유학생(계)(2008~2015)", "지방자치단체외국인주민현황", (2008, 2015), ["유학생"], [_regions("시군구")]),
    P("TX_A011_A", "한국국적을 가지지 않은 자-유학생(계)", "지방자치단체외국인주민현황", (2016, 2024), ["유학생"], [_regions("시군구")]),
    P("TX_A000", "시도별 외국인주민 현황(2007~2015)", "지방자치단체외국인주민현황", (2007, 2015), ["외국인주민 합계", "외국인근로자"], [_regions("시도")]),
    P("DT_1B040A3", "행정구역(시군구)별, 성별 인구수", "주민등록인구현황", (2011, 2025), ["총인구수", "남자인구수", "여자인구수"], [_regions("시군구")]),
    P("DT_1B8000F", "인구동태건수 및 동태율 추이(출생,사망,혼인,이혼)", "인구동향조사", (1970, 2025),
      ["출생아수", "사망자수", "혼인건수", "이혼건수", "조혼인율"], [], unit="명"),
    P("INH_03", "혼인건수, 조혼인율", "인구동향조사", (1970, 2025), ["혼인건수", "조혼인율"]),
    P("DT_101094A004", "당해연도 혼인 비율", "인구동태패널통계", (2015, 2023), ["비율"],
      [_dim("성별", ["전체", "남자", "여자"], "sex"), _dim("생년별", [str(y) for y in range(1983, 1996)], "cohort")], unit="%"),
    P("DT_101094A002", "누적 출산 비율", "인구동태패널통계", (2015, 2023), ["비율"],
      [_dim("성별", ["전체", "남자", "여자"], "sex"), _dim("생년별", [str(y) for y in range(1983, 1996)], "cohort")], unit="%"),
    P("DT_1BZ05011", "가구주의 성/연령별 추계가구-전국", "장래가구추계", (2022, 2052), ["계", "19세 이하", "20~24세"],
      [_dim("가구주의 성별", ["계", "남자", "여자"], "sex"), _dim("가구유형별", ["합계"])], unit="가구"),
    P("DT_1BZ0506", "가구주의 연령/가구원수별 추계가구_시도", "장래가구추계", (2022, 2052), ["계", "1인", "2인", "5인이상"],
      [_regions("시도")], unit="가구"),
    P("DT_1IN8501", "행정구역별 인구 및 가구", "인구총조사", (1985, 1985), ["인구", "가구"], [_regions("시군구"), SEX]),
    P("DT_1IN9001", "행정구역별 인구 및 가구", "인구총조사", (1990, 1990), ["인구", "가구"], [_regions("시군구"), SEX]),
    P("DT_1IN9501", "행정구역별 인구 및 가구", "인구총조사", (1995, 1995), ["인구", "가구"], [_regions("시군구"), SEX]),
    P("DT_1JU8504", "행정구역/주택의종류/주택의편익시설별 주택", "주택총조사", (1985, 1985), ["계", "주택"], [_regions("시군구")], unit="호"),
    P("DT_1JU9003", "행정구역/주택의종류/건축재료/건축년도별 주택", "주택총조사", (1990, 1990), ["주택"],
      [_regions("시군구"), _dim("건축재료별", ["총계", "벽돌", "블록", "목조"])], unit="호"),
    P("DT_1GA9009", "행정구역/거처의 종류/점유형태별 가구", "인구총조사", (1990, 1990), ["일반가구"], [_regions("시군구"), OCC], unit="가구"),
    P("DT_1GA9008", "시도/가구주의 연령/거처의 점유형태별 가구", "인구총조사", (1990, 1990), ["일반가구"], [_regions("시도"), OCC], unit="가구"),
    P("DT_1GA9509", "행정구역/거처의 종류/점유형태별 가구", "인구총조사", (1995, 1995), ["일반가구"], [_regions("시군구"), OCC], unit="가구"),
    P("DT_1B26001", "시도별 이동자수", "국내인구이동통계", (2015, 2026), ["총전입", "총전출", "순이동"], [_regions("시도"), SEX], se="월"),
    P("DT_1B81A23", "시군구/출생아수, 합계출산율", "인구동향조사", (2000, 2025), ["출생아수", "합계출산율"], [_regions("시군구")]),
    P("DT_1B81A13", "시도/성/출산순위/출생시 체중별 출생(쌍태아 이상)", "인구동향조사", (2000, 2025), ["출생"],
      [_regions("시도"), SEX, _dim("출산순위별", ["총계", "첫째아", "둘째아"]), _dim("출생시 체중별", ["계", "2.5kg 미만", "2.5kg 이상"])]),
    P("DT_1B8000H", "시도/인구동태건수 및 동태율(출생,사망,혼인,이혼)", "인구동향조사", (2000, 2025),
      ["출생아수", "사망자수", "혼인건수", "이혼건수"], [_regions("시도")]),
    P("DT_1B85003", "시도/연령(5세)별 이혼", "인구동향조사", (2000, 2025), ["이혼건수"],
      [_regions("시도"), _dim("성별", ["남편", "아내"], "sex"), _dim("연령별", ["계", "35~39세", "40~44세", "45~49세"], "ages")], unit="건"),
    P("DT_1GO0501", "행정구역/연령/성별 고령자", "인구총조사", (2005, 2005), ["고령자"],
      [_regions("시군구"), SEX, _dim("연령별", ["계", "65~69세", "70~74세"], "ages")]),
    P("DT_1IN1503", "성 및 연령별 인구 - 시군구", "인구총조사", (2015, 2025), ["인구"],
      [_regions("시군구"), SEX, _dim("연령별", ["합계", "0~4세", "65~69세", "70~74세"], "ages")]),
    P("DT_1B26B21", "시도/전입사유별 이동자수", "국내인구이동통계", (2015, 2025), ["총전입", "총전출"], [_regions("시도")]),
]


class Corpus:
    name = "test"

    def __init__(self):
        self._docs = [Doc(p["tbl_id"], table_text(p), {"tbl_nm": p["tbl_nm"], "survey_nm": p["survey_nm"], "profile": p})
                      for p in PROFILES]

    def docs(self):
        return self._docs

    def signature(self):
        import hashlib                                     # 내용이 바뀌면 달라져야 함 (BM25 토큰 디스크 캐시 키)
        return "test:search:" + hashlib.sha1("|".join(d.text for d in self._docs).encode()).hexdigest()[:12]


@pytest.fixture(scope="module")
def s():
    return TableSearch(Corpus(), facets_source="meta", llm_rerank=False)


def top(s, question, rewrite=None, filters=None, k=3, unit="main"):
    return [h["tbl_id"] for h in s.search(rewrite or question, filters, k, question=question, unit=unit, today="2026-11-12")["hits"]]


def test_parse_question():
    v = parse_question("1983년생 사람들의 결혼 비율이 2016년과 비교해 2018년에는 얼마나 줄었나요?", {"시점": [1983, 2016, 2018]})
    assert v.years == [2016, 2018] and v.cohort == [1983]            # 출생연도는 시점 조건이 아님
    assert "혼인" in v.added                                          # 일상어 사전: 결혼 → 혼인
    v = parse_question("2000년에 가구원수가 99,000명 이상인 지역들 중에서 2인 가구는 몇 집이나 되나요?")
    assert v.years == [2000] and "99" not in v.lex and "2인" in v.lex  # 임계값은 검색어가 아님
    v = parse_question("2010년 수원시 권선구에 사는 일반 가정 중에서 75세 이상의 노인 부부 가정이 몇 퍼센트나 차지하나요?")
    assert v.subs == ["수원시", "권선구"] and "75세 이상" in v.lex
    v = parse_question("부산광역시의 여성 총전입 수가 2026년 1분기에서 2분기로 얼마나 줄었나요?")
    assert v.sido == ["부산"] and v.cycle == {"Q"} and v.years == [2026] and not v.subs
    v = parse_question("1995년 동부에서 주택 한 호가 인구 천 명당 얼마나 되는지 알고 싶어요.")
    assert v.subs == ["동부"]                                         # '인구'·'가구' 는 지역이 아님
    assert parse_question("작년 서울 일반가구 수", today="2026-11-12").years == [2025]


def test_rewrite_lost_the_key_term(s):
    # 재작성 문장에서 '유학생' 이 사라진 실제 사례 → 원문 값 연결로 찾고, 시점(2011·2012)으로 (2008~2015)판을 고름
    r = top(s, "과천시에 사는 유학생들이 2011년과 비교해서 2012년에는 몇 퍼센트 줄었나요?",
            "외국인 인구수 증감률 추이", {"시점": [2011, 2012], "대상": ["외국인"], "지표": ["인구수"]})
    assert r[0] == "TX_A011"
    r = top(s, "과천시에 사는 유학생들이 2019년과 비교해서 2022년에는 몇 퍼센트 줄었나요?", "외국인 인구수 증감률 추이")
    assert r[0] == "TX_A011_A"                                        # 같은 이름의 다른 기간판


def test_title_in_question(s):
    # 원문에 표 이름이 그대로 있는데 재작성이 '여자 가구수 증감률 추이' 로 바꾼 사례
    r = top(s, "가구주의 성/연령별 추계가구-전국 조사에서 가구주 여자의 2034년의 계(가구) 대비 2041년의 계(가구) 증감률(%)은?",
            "여자 가구수 증감률 추이", {"시점": [2034, 2041], "성별": ["여자"], "지표": ["가구수"]})
    assert r[0] == "DT_1BZ05011"


def test_cohort_year_is_not_a_period(s):
    # 쿼리 모듈이 1983 을 시점에 넣고 지표를 '혼인건수' 로 바꾼 사례 (정답 표는 2015~2023 수록)
    r = top(s, "1983년생 사람들의 결혼 비율이 2016년과 비교해 2018년에는 얼마나 줄었나요?",
            "혼인건수 증감", {"시점": [1983, 2016, 2018], "지표": ["혼인건수"]})
    assert r[0] == "DT_101094A004"


def test_year_edition_and_region_level(s):
    # 같은 이름의 연도판(1990·1995) + 시도판: 시점과 시군구 수준으로 가름
    r = top(s, "1990년 화성군에서 전체 일반가구 중에서 보증부월세로 거주하는 가구의 비율은 얼마나 될까요?",
            "보증부월세 일반가구 가구수 구성비", {"시점": [1990], "지역": ["화성군"], "지표": ["가구수", "구성비"]})
    assert r[0] == "DT_1GA9009"
    r = top(s, "1990년에 광양군에 있는 집들은 그 해 그곳에 사는 사람들 천 명당 몇 채일까?", "광양", {"시점": [1990], "지역": ["광양군"]}, k=5)
    assert "DT_1JU9003" in r and "DT_1IN9001" in r                    # 주택 표와 인구 표 모두 1990년판
    assert not {"DT_1IN8501", "DT_1IN9501", "DT_1JU8504"} & set(r[:3])


def test_cycle(s):
    r = top(s, "부산광역시의 여성 총전입 수가 2026년 1분기에서 2분기로 얼마나 줄었나요?", "여자 총전입 증감")
    assert r[0] == "DT_1B26001"                                       # 월 자료가 있는 표 (분기는 월로 계산 가능)


def test_units(s):
    q = "140,000가구 이상의 증감률을 가진, 가구주 남자가 미혼인 5인 이상 가구가 2044년에서 2049년 사이에 가장 많이 증가한 지역은 어디일까요?"
    main = top(s, q, "남자 미혼 5인 이상 가구수 지역별 증감률 순위", k=5)
    assert main[0] == "DT_1BZ0506"
    assert top(s, q, "가구", k=5, unit="q-1") == main                  # 뜻 없는 하위 질의는 본 질의 순위 (끼어들지 않음)
    sub = top(s, "2015년과 2018년 부산진구의 국제결혼 이주자와 주민등록 인구", "국제결혼 이주자", unit="q-2")
    assert sub[0] == "TX_A008_A"


def test_compat_shapes(s):
    r = s.search("혼인건수 증감", {"시점": [2016, 2018], "지표": ["혼인건수"]}, 5, question="2016년과 2018년 혼인 건수 차이")
    assert r["pool_ids"] and {"rank", "tbl_id", "score", "stages", "feas", "unmet", "cover", "cost"} <= set(r["hits"][0])
    assert r["hits"][0]["tbl_id"] in ("INH_03", "DT_1B8000F")
    c = s.search_compat("혼인건수", 3, filters={"시점": [2020]}, question="2020년 혼인건수")
    assert [h["rank"] for h in c] == [1, 2, 3] and "stages" not in c[0]


def test_compare_passes_question(s):
    from backend.rag.search.tuning.compare import evaluate_one
    row = {"question": "과천시에 사는 유학생들이 2011년과 비교해서 2012년에는 몇 퍼센트 줄었나요?", "gold": ["TX_A011"],
           "groups": {"R1": ["TX_A011"]}}
    units = [{"unit": "main", "search_query": "외국인 인구수 증감률 추이", "filters": {"시점": [2011, 2012], "지표": ["인구수"]}},
             {"unit": "q-1", "search_query": "인구", "filters": {"시점": [2011, 2012], "지표": ["인구"]}}]
    res = evaluate_one(s, row, units, 10, 50)
    assert res["hit@1"] == 1 and res["pool@k"] == 1 and res["fail"] == ""


def test_structure_checks(s):
    # 조건이 적은 질문 → 질문이 건드리지 않는 분류(출산순위·체중)가 많은 세부 표보다 단순한 표
    r = top(s, "2025년 경기도에서 태어난 아이는 몇 명이에요?", "출생아수", {"시점": [2025], "지역": ["경기도"]})
    assert r.index("DT_1B81A23") < r.index("DT_1B81A13") if "DT_1B81A13" in r else "DT_1B81A23" in r
    # 연령·성별을 물으면 그 분류가 있는 표
    r = top(s, "2023년 서울 40대 남성 이혼 건수", "남자 이혼건수", {"시점": [2023], "지역": ["서울특별시"], "성별": ["남자"]})
    assert r[0] == "DT_1B85003"
    # 지역 수준을 물으면 그 수준이 있는 표 (시도판은 뒤로)
    r = top(s, "2020년 인구총조사 등록센서스 방식 시군구 성별 인구", "인구수 시군구별 성별 인구")
    assert r[0] == "DT_1IN1503"
    x = s.search("인구", None, 5, question="2020년 인구총조사 등록센서스 방식 시군구 성별 인구")["parsed"]
    assert x["axis"] == "시군구" and x["want_sex"]


def test_partial_years_stay(s):
    # 요청 연도를 한 표가 다 담지 못하는 경우(연도판이 나뉨): 일부만 담은 표도 후보로 남김 → View 가 있는 연도만 줌
    r = top(s, "2005년과 2025년 인구총조사 고령인구 비교", "인구수 인구 인구수", {"시점": [2005, 2025]}, k=4)
    assert "DT_1GO0501" in r and "DT_1IN1503" in r
    h = {x["tbl_id"]: x for x in s.search("고령인구", None, 6, question="2005년과 2025년 인구총조사 고령인구 비교")["hits"]}
    assert "시점 0.5" in h["DT_1GO0501"]["feas_notes"]
    v = parse_question("1995년부터 5년마다 총인구 변화", today="2026-11-13")
    assert v.years == [1995, 2000, 2005, 2010, 2015, 2020, 2025]
    assert parse_question("2024년 상반기 서울특별시 혼인 건수는 몇 건이야?").cycle == {"H"}


def test_llm_rerank():
    calls = []

    def fake_chat(messages, schema=None, max_tokens=0):
        calls.append(messages[1]["content"])
        return {"order": [3, 1, 99]}                       # 3번을 맨 앞으로, 모르는 번호는 무시, 빠진 번호는 원래 순서

    s2 = TableSearch(Corpus(), facets_source="meta", llm_rerank=True, chat_fn=fake_chat)
    base = [h["tbl_id"] for h in TableSearch(Corpus(), facets_source="meta", llm_rerank=False).search(
        "혼인건수", None, 5, question="2020년 혼인 건수")["hits"]]
    r = s2.search("혼인건수", None, 5, question="2020년 혼인 건수")
    got = [h["tbl_id"] for h in r["hits"]]
    assert got == [base[2], base[0], base[1], *base[3:]] and r["llm"] == "llm"
    assert "[1]" in calls[0] and "항목:" in calls[0] and "연도:" in calls[0]
    assert [h["rank"] for h in r["hits"]] == [1, 2, 3, 4, 5] and r["hits"][0]["stages"]["llm"]["rank"] == 1
    s2.search("혼인건수", None, 5, question="2020년 혼인 건수")
    assert len(calls) == 1                                  # 같은 질문·후보는 캐시

    def broken(*a, **k):
        raise RuntimeError("HCX 429")
    s3 = TableSearch(Corpus(), facets_source="meta", llm_rerank=True, chat_fn=broken)
    r = s3.search("이혼건수", None, 5, question="2021년 이혼 건수 알려줘")
    assert r["hits"] and r["llm"].startswith("실패")        # 실패해도 검색 결과는 그대로
