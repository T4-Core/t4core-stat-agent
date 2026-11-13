"""[NEW 11-12] 144문항 비교에서 나온 수정 중 검색 쪽 확인 — 2) 검색 문장의 의도 단어  4) 조건 확인(지표·지역) (데이터 없음)"""
from backend.rag.ingestion.resolve import indicator_ok, region_ok, search_query, unmet


def test_search_query_drops_intent_words():
    assert search_query("국제결혼 이주자 인구수 증감 추이", {}) == "국제결혼 이주자 인구수"
    assert search_query("일반가구 초등학교 비율 순위", {"지표": ["초등학교 비율"]}) == "일반가구 초등학교 비율"


# ── 4) 조건 확인 ──
P_SGG = {"tbl_id": "T1", "tbl_nm": "한국국적을 가지지 않은 자-결혼이민자(계)", "periods": [{"year_from": 2010, "year_to": 2023}],
         "levels": [{"kind": "regions", "names": ["전국", "서울특별시", "부산광역시"], "sido": ["서울특별시", "부산광역시"],
                     "geo_types": {"전국": 1, "시도": 17, "시군구": 229}}],
         "items": [{"name": "계", "unit": "명"}], "units": ["명"]}
P_SIDO = {**P_SGG, "levels": [{"kind": "regions", "names": ["전국", "서울특별시"], "sido": ["서울특별시"],
                                "geo_types": {"전국": 1, "시도": 17}}]}
P_MARRY = {"tbl_id": "T2", "tbl_nm": "시도/부의 혼인종류/ 처의 혼인종류별 혼인(발생기준)", "periods": [], "levels": [],
           "items": [{"name": "계", "unit": "건"}], "units": ["건"]}


def test_indicator_ok():
    assert indicator_ok(P_SGG, ["인구수"], ["계"])                       # 일반 지표 → 단위 '명' 으로 충족
    assert not indicator_ok(P_MARRY, ["인구수"], ["계"])                 # 단위 '건' 인 표는 아님
    assert indicator_ok(P_MARRY, ["혼인건수"], ["계"])                   # '혼인건수' → 어간 '혼인' 이 표 이름에
    assert indicator_ok(P_MARRY, ["구성비"], ["계"])                     # 계산 단어만이면 조건 없음
    assert indicator_ok(P_SGG, ["보증부월세비율", "인구수"], ["계"])       # 값 하나라도 맞으면 충족


def test_region_ok_sigungu():
    names, sidos = ["전국", "서울특별시", "부산광역시"], {"서울", "부산"}
    assert region_ok(P_SGG, "부산진구", names, sidos)                    # 시군구 수준이 있는 표
    assert not region_ok(P_SIDO, "부산진구", names, {"서울"})             # 시도까지만 있는 표
    assert region_ok(P_SGG, "부산광역시", names, sidos) and not region_ok(P_SGG, "대구광역시", names, sidos)
    assert region_ok(P_SGG, "서울특별시 도봉구", names, sidos)
    assert unmet(P_SGG, {"시점": [2015, 2018], "지역": ["부산진구"], "지표": ["인구수"]}) == []
