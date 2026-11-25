"""'서울 자치구별 연령대 인구 구성' — 지역 축(자치구 → 시군구) + 연령 축을 둘 다 살림 (HCX·DuckDB 없음)

증상: 서울특별시 합계 한 행의 View 만 나옴. 원인 세 가지
  1) 비교축 '자치구' 를 View(axis_geo) · 검색(AXIS_RE) 이 몰라 지역을 펼치지 않음
  2) 비교축이 여러 개면 첫 번째만 남김 → ['연령', '시군구'] 이면 지역 축이 사라짐
  3) View 는 연령 슬롯(범위)이 없으면 연령 합계만 — '연령대별' 축이어도 구간을 펼치지 않음
"""
from backend.rag.query_analyzer.adapter import to_view_filters
from backend.rag.query_analyzer.slots import SLOT_KEYS
from backend.rag.query_analyzer.validate import fix_slots
from backend.rag.view.build import age_axis_codes, axes_of, match_level


def test_validate_axis_synonyms():
    s = {k: [] for k in SLOT_KEYS}
    s.update(지역=["서울특별시"], 대상=["인구"], 비교축=["자치구별", "연령대"], 의도=["구성비"])
    out, log = fix_slots(s, "서울 자치구별 연령대 인구 구성", {})
    assert out["비교축"] == ["시군구", "연령"] and any("'자치구' → '시군구'" in x for x in log)


def test_adapter_keeps_geo_axis_first():
    notes = []
    f = to_view_filters({"지역": ["서울특별시"], "대상": ["인구"], "비교축": ["연령", "시군구"]}, ["구성비"], notes)
    assert f["비교축"] == "시군구" and f["보조축"] == ["연령"]                     # 지역 축이 뒤에 있어도 비교축으로
    assert any("보조축" in n for n in notes)
    f1 = to_view_filters({"지역": ["서울특별시"], "비교축": ["시군구"]}, ["비교"], [])
    assert f1["비교축"] == "시군구" and "보조축" not in f1                         # 하나면 그대로


def _c(code, name, geo, parent="", depth=0, total=False):
    return {"code": code, "name": name, "std": name, "label": name, "geo_type": geo, "parent": parent, "depth": depth,
            "is_total": total}


REGIONS = {"kind": "regions", "obj_nm": "행정구역(시군구)별", "default_code": "00", "codes": [
    _c("00", "전국", "전국", total=True), _c("11", "서울특별시", "시도"), _c("11010", "종로구", "시군구", "11", 1),
    _c("11020", "중구", "시군구", "11", 1), _c("26", "부산광역시", "시도"), _c("26010", "중구", "시군구", "26", 1)]}


def _a(code, lo, hi, total=False):
    return {"code": code, "name": f"{lo}~{hi}세" if hi is not None else f"{lo}세 이상", "std": "", "label": "",
            "age_from": None if total else lo, "age_to": None if total else hi, "is_total": total}


AGES = {"kind": "ages", "obj_nm": "연령별", "default_code": "000", "codes": [_a("000", 0, None, total=True)]
        + [_a(f"5-{lo}", lo, lo + 4) for lo in range(0, 85, 5)] + [_a("85+", 85, None)]
        + [_a(f"1-{y}", y, y) for y in range(10)] + [_a("10s", 0, 9)]}


def test_view_expands_districts_and_age_groups():
    f = {"지역": ["서울특별시"], "대상": ["인구"], "비교축": "시군구", "보조축": ["연령"]}
    regions = match_level(REGIONS, f, [], [])
    assert [c["name"] for c in regions] == ["종로구", "중구"]                        # 서울 아래 자치구 (부산 중구 아님)
    notes = []
    ages = match_level(AGES, f, [], notes)
    assert [c["code"] for c in ages] == [f"5-{lo}" for lo in range(0, 85, 5)] + ["85+"]   # 5세 구간 + 85세 이상
    assert notes and notes[0]["type"] == "axis"
    assert [c["name"] for c in match_level(REGIONS, {**f, "비교축": "자치구", "보조축": None}, [], [])] == ["종로구", "중구"]


def test_view_age_total_without_axis():
    f = {"지역": ["서울특별시"], "대상": ["인구"], "비교축": "시군구"}
    assert [c["code"] for c in match_level(AGES, f, [], [])] == ["000"]                # 연령 축이 없으면 기존처럼 합계
    assert axes_of({"비교축": "시군구", "보조축": ["연령", "시군구"]}) == ["시군구", "연령"]
    assert age_axis_codes([_a("000", 0, None, total=True)]) == []


def test_search_axis_from_district_word():
    from backend.rag.search.query import parse_question
    assert parse_question("서울 자치구별 연령대 인구 구성").axis == "시군구"
