"""table_card 검토에서 찾은 문제가 expend 규칙에서 고쳐졌는지 (회귀 테스트)"""
from table_card_expend import rules as R
from table_card_expend.split import viewpoints, year_spans

V = R.load_dict()["_지표목록"]


def items(*xs):
    return [{"name": n, "unit": u, "kind": R.measure_kind(n, u)} for n, u in xs]


def inds(title, its, target=()):
    return [x for x, _ in R.infer_indicators(title, its, list(target), V)]


def test_birth_year_table_is_not_births():
    got = inds("출생연도별 인구", items(("인구", "명")), ["인구"])
    assert "출생아수" not in got and "인구수" in got


def test_north_korea_born_is_not_births():
    assert "출생아수" not in inds("연령/성/혼인상태별 북한출생 인구", items(("인구", ""), ("남자", "")), ["인구"])


def test_ratio_table_gets_no_count_indicators():
    got = inds("주택소유 가구 비율", items(("비율", "%")), ["가구"])
    assert "가구수" not in got and "주택수" not in got


def test_average_household_size_is_not_population():
    assert "인구수" not in inds("평균 가구원수", items(("평균 가구원수", "명/가구")), ["가구원"])


def test_one_person_household_people_count_is_household_count():
    got = inds("성/거처의 종류별 1인가구", items(("1인가구-합계", "명")), ["1인가구"])
    assert "가구수" in got


def test_household_composition_axis_does_not_make_household_count():
    got = inds("성, 세대구성 및 연령별 고령자", items(("인구", "명")), ["1인가구", "인구"])
    assert "가구수" not in got and "인구수" in got


def test_measure_kind():
    assert R.measure_kind("경제활동참가율", "%") == "ratio"
    assert R.measure_kind("평균연령", "세") == "average"
    assert R.measure_kind("가구", "가구") == "count"


def test_sido_regex_keeps_jeju_4_3():
    assert R.clean_title("제주4·3 사건 관련 인구") .startswith("제주4·3")
    assert R.clean_title("통근·통학인구(전남,12세이상)") == "통근·통학인구(12세이상)"


def test_merge_notes_and_definitions():
    cmmt = [{"CMMT_NM": "통계표", "CMMT_DC": "외국인 제외."},
            {"CMMT_NM": "통계표", "CMMT_DC": "통근·통학인구 ☞ 통근인구란 12세이상으로 매일 정기적으로 집에서 직장에 "},
            {"CMMT_NM": "통계표", "CMMT_DC": "                  근무하러 다니는 자를 말한다. "}]
    notes = R.merge_notes(cmmt)
    assert notes == ["외국인 제외.", "통근·통학인구 ☞ 통근인구란 12세이상으로 매일 정기적으로 집에서 직장에 근무하러 다니는 자를 말한다."]
    d = R.definitions(notes)
    assert d[0]["용어"] == "통근·통학인구" and "근무하러" in d[0]["정의"]


def test_population_scope():
    pop = R.population("성, 연령 및 교육정도별 인구(6세이상, 내국인)", [{"name": "총계(12세이상)"}],
                       ["외국인 제외.", "특별조사구 인구제외.", "집단가구 포함."])
    assert {"6세 이상", "내국인", "12세 이상", "외국인 제외", "특별조사구 제외", "집단가구 포함"} <= set(pop)


def test_region_full_names_fills_missing_parent_by_code():
    rows = [{"code": "00", "name": "전국", "std": "전국", "geo_type": "전국", "parent": ""},
            {"code": "11", "name": "서울특별시", "std": "서울특별시", "geo_type": "시도", "parent": ""},
            {"code": "11020", "name": "중구", "std": "중구", "geo_type": "시군구", "parent": ""},
            {"code": "21", "name": "부산직할시", "std": "부산직할시", "geo_type": "시군구", "parent": ""},
            {"code": "21020", "name": "중구", "std": "중구", "geo_type": "시군구", "parent": ""}]
    names, orig, bare = R.region_full_names(rows)
    assert "서울특별시 중구" in names and "부산광역시 중구" in names and "부산광역시" in names
    assert bare == [] and orig["부산광역시"] == "부산직할시"


def test_year_spans_and_viewpoints():
    assert year_spans([2015, 2016, 2017, 2020]) == [(2015, 2017), (2020, 2020)]
    v = viewpoints(["인구수"], [{"표준": "성별", "원래": "성", "값_수": 2}], ["전국", "시도"])
    assert "시도별 성별 인구수" in v and not any("별별" in x for x in v)
