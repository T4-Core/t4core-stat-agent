"""[NEW] judge/extract.py 단위 테스트 — 손으로 만든 가짜 Record 사용 (데이터 파일·HCX 없음)

실행  pytest tests/judge -q   (저장소 루트에서)

pytest 는 이름이 test_ 로 시작하는 함수를 찾아 실행하고, assert 가 틀리면 실패로 표시한다.
(자바 JUnit 의 @Test 메서드 + assertEquals 와 같은 역할. 클래스 없이 함수만으로 쓸 수 있다)
"""
from backend.rag.judge.extract import extract_contents
from backend.schemas.record import Record
from tests.judge._records import make_record   # test_slots.py 와 함께 쓰는 가짜 Record 생성기


# ---- 1. 기본: 연간 표, 지역 × 성별 ----
def test_region_and_sex():
    rec = make_record(["시점", "행정구역(시군구)별", "성별", "항목", "값"],
                      [["2023", "대구광역시", "남자", "인구", 1170000],
                       ["2023", "대구광역시", "여자", "인구", 1200000]])
    c = extract_contents(rec)
    assert c.years == {2023}
    assert c.tbl_id == "DT_TEST"
    region = c.dims_of("regions")[0]
    assert region.std == {"대구광역시"}
    sex = c.dims_of("sex")[0]
    assert sex.labels == ["남자", "여자"]          # 처음 나온 순서 유지
    assert c.items == ["인구"]
    assert c.n_points == 2 and not c.is_empty


# ---- 2. 연령 5세 구간 + 합계 라벨 ----
def test_age_ranges_and_total():
    rec = make_record(["시점", "연령별", "항목", "값"],
                      [["2023", "계", "인구", 300], ["2023", "20 - 24세", "인구", 100], ["2023", "25 - 29세", "인구", 200]])
    age = extract_contents(rec).dims_of("ages")[0]
    assert age.age_ranges == [(20, 24), (25, 29)]   # "계" 는 범위에서 제외
    assert age.has_total is True
    assert age.role == ""                           # 본인 연령


# ---- 3. [P1] 연령 분류가 없는 표 → ages 열 없음 (3단계에서 연령 missing 판정의 근거) ----
def test_no_age_dimension():
    rec = make_record(["시점", "행정구역별", "항목", "값"], [["2023", "대구광역시", "총인구", 2370000]])
    c = extract_contents(rec)
    assert c.dims_of("ages") == []
    assert [d.kind for d in c.dims] == ["regions"]


# ---- 4. 월간 표: "2023.01" → 연도 2023 ----
def test_monthly_periods():
    rec = make_record(["시점", "항목", "값"], [["2023.01", "출생아수", 20000], ["2023.02", "출생아수", 19000]],
                      prd_se="M")
    c = extract_contents(rec)
    assert c.years == {2023}
    assert c.period_labels == ["2023.01", "2023.02"]
    assert c.prd_se == "M"


# ---- 5. 빈 View: 행 0개 → is_empty, 연도는 metadata 에서 ----
def test_empty_view_uses_metadata_years():
    rec = make_record(["시점", "행정구역별", "항목", "값"], [], prd_from="2021", prd_to="2023", n_points=0)
    c = extract_contents(rec)
    assert c.is_empty is True and c.n_points == 0
    assert c.years == {2021, 2022, 2023}
    assert c.dims_of("regions")[0].labels == []     # 열은 있지만 값은 없음


# ---- 6. 가구주의 연령: 본인 연령이 아님 → role 로 구분 ----
def test_householder_age_role():
    rec = make_record(["시점", "가구주의 연령별", "항목", "값"],
                      [["2023", "20 - 24세", "가구수", 10], ["2023", "25 - 29세", "가구수", 20],
                       ["2023", "30 - 34세", "가구수", 30]])
    age = extract_contents(rec).dims_of("ages")[0]
    assert age.role == "가구주"
    assert age.age_ranges[0] == (20, 24)


# ---- 7. 이름이 겹쳐 상위 지역이 붙은 라벨 ----
def test_duplicate_region_labels():
    rec = make_record(["시점", "행정구역별", "항목", "값"],
                      [["2023", "서울특별시 동부", "인구", 1], ["2023", "부산광역시 중구", "인구", 2], ["2023", "대구", "인구", 3]])
    region = extract_contents(rec).dims_of("regions")[0]
    assert region.std == {"서울특별시", "부산광역시 중구", "대구광역시"}


# ---- 8. 추이 View: 5개 연도 + pydantic Record 로 넣어도 같은 결과 ----
def test_trend_view_and_pydantic_input():
    rows = [[str(y), "인구", 100 + y] for y in range(2019, 2024)]
    rec = make_record(["시점", "항목", "값"], rows, view_type="trend")
    c_dict = extract_contents(rec)
    c_model = extract_contents(Record.model_validate(rec))   # ViewResult 안에서는 pydantic 객체로 온다
    assert c_dict.years == {2019, 2020, 2021, 2022, 2023}
    assert c_dict.view_type == "trend"
    assert c_dict == c_model                                 # dataclass 는 필드 값이 같으면 == 가 True


# ---- 9. 값이 None 인 칸은 n_points 에서 빠짐 (KOSIS '-' 부호 등) ----
def test_none_values_not_counted():
    rec = make_record(["시점", "항목", "값"], [["2023", "인구", None], ["2022", "인구", 5]])
    c = extract_contents(rec)
    assert c.n_points == 1 and not c.is_empty
    assert c.years == {2022, 2023}


# ---- 10. '특성별' 열은 성별이 아님 ----
#   [CHANGED v4] 이전: normalize.level_kind 가 '성별' 로 끝나는 이름을 라벨과 관계없이 sex 로 분류하던 한계를 고정한 테스트.
#   v4 에서 고침 ('성별' 앞이 단어 경계일 때만 + 값에 남·여가 있어야) → other
def test_known_misclassified_sex_column():
    rec = make_record(["시점", "특성별", "항목", "값"],
                      [["2023", "1인가구", "가구수", 10], ["2023", "2인가구", "가구수", 20]])
    dim = extract_contents(rec).dims[0]
    assert dim.kind == "other"                      # 이전: "sex"
    assert dim.labels == ["1인가구", "2인가구"]


# ---- 11. 라벨별 값 개수: 라벨은 있지만 값이 비어 있는 연령 구간 ----
def test_label_points_with_missing_values():
    rec = make_record(["시점", "연령별", "항목", "값"],
                      [["2023", "계", "인구", 300], ["2023", "20 - 24세", "인구", 100], ["2023", "25 - 29세", "인구", None]])
    age = extract_contents(rec).dims_of("ages")[0]
    assert age.age_ranges == [(20, 24), (25, 29)]   # 범위에는 25~29 도 있음 (라벨이 있으므로)
    assert age.label_points == {"계": 1, "20 - 24세": 1, "25 - 29세": 0}   # 하지만 값은 0 개


# ---- 12. 연도별 값 개수 + 값 열이 없는 표는 '모름'({}) ----
def test_year_points_and_unknown_without_value_column():
    rec = make_record(["시점", "행정구역별", "항목", "값"],
                      [["2023", "대구광역시", "인구", 5], ["2024", "대구광역시", "인구", None],
                       ["2024.01", "대구광역시", "인구", None]])
    c = extract_contents(rec)
    assert c.years == {2023, 2024}
    assert c.year_points == {2023: 1, 2024: 0}       # 2024 는 행이 2개지만 값은 0 개 ("2024.01" 도 2024 로 묶임)

    no_value = make_record(["시점", "행정구역별", "항목"], [["2023", "대구광역시", "인구"]], n_points=1)
    c2 = extract_contents(no_value)
    assert c2.year_points == {}                      # 값 열이 없으면 셀 수 없음 = 모름 (0 과 다름)
    assert c2.dims[0].label_points == {}
