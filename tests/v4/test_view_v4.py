"""[NEW v4] Step 4 — View 묶음 · Point 충돌 · 선택 왕복 + 검색 문장 찌꺼기 정리 (HCX·네트워크 없음)

충돌 재현: 가짜 KOSIS 의 '행정구역(시군구)별, 성별 인구수'(DT_1B040A3)를 복제해
  DT_Y001 = 같은 교차점에 다른 값 (+12345, 메타 주석 있음)
  DT_Y002 = 같은 값을 천명 단위로 (단위 맞추면 DT_1B040A3 와 같음 → 같은 선택지로 묶여야 함)
"""
import json
from pathlib import Path

import pandas as pd

from tests import fake_kosis
from tests.test_pipeline_e2e import ROOT, _env, _run


def clone_table(kd, src_tbl, new_tbl, name, scale=None, bump=0, unit=None, cmmt=None, category="주민등록인구현황"):
    src = kd / "raw" / category / f"101_{src_tbl}.csv"
    b = pd.read_csv(src, dtype=str, encoding="utf-8-sig")
    b["TBL_ID"], b["TBL_NM"] = new_tbl, name
    v = b["DT"].astype(float)
    v = (v / scale if scale else v) + bump
    b["DT"] = v.map(lambda x: f"{x:g}")
    if unit:
        b["UNIT_NM"] = unit
    b.to_csv(src.with_name(f"101_{new_tbl}.csv"), index=False, encoding="utf-8-sig")
    m = json.loads((kd / "meta" / f"101_{src_tbl}.json").read_text(encoding="utf-8"))
    m["TBL"], m["CMMT"] = [{"TBL_NM": name}], cmmt or []
    for it in m["ITM"]:
        if unit and it.get("OBJ_ID") == "ITEM":
            it["UNIT_NM"] = unit
    (kd / "meta" / f"101_{new_tbl}.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    cat = pd.read_csv(kd / "catalog.csv", dtype=str, encoding="utf-8-sig")
    row = cat[cat["tbl_id"] == src_tbl].iloc[0].copy()
    row["tbl_id"], row["tbl_nm"] = new_tbl, name
    pd.concat([cat, row.to_frame().T]).to_csv(kd / "catalog.csv", index=False, encoding="utf-8-sig")


def build_conflict_data(kd: Path):
    fake_kosis.build(kd)
    clone_table(kd, "DT_1B040A3", "DT_Y001", "행정구역(시도)별 인구수 (외국인 포함)", bump=12345,
                cmmt=[{"CMMT_NM": "통계표", "CMMT_DC": "외국인 포함 집계"},
                      {"CMMT_NM": "항목", "ITM_NM": "총인구수", "CMMT_DC": "내국인+외국인"},
                      {"CMMT_NM": "항목", "ITM_NM": "세대수", "CMMT_DC": "이 View 와 무관한 항목 주석"}])
    clone_table(kd, "DT_1B040A3", "DT_Y002", "행정구역(시도)별 인구수 (천명)", scale=1000, unit="천명")
    return kd


def test_search_query_cleanup():
    from backend.rag.ingestion.resolve import search_query
    F = {"시점": [2024, 2025], "지역": ["전국"]}
    assert search_query("2024~2025년 전국 다문화가구 가구수 증감", F) == "다문화가구 가구수 증감"
    assert search_query("2016년, 2025년 전국 한부모가구 가구수 증감", F) == "한부모가구 가구수 증감"
    assert search_query("1983~1995년생 인구", {}) == "인구"
    assert search_query("2024년 7~9월 외국인 순이동 이동자수", {}) == "외국인 순이동 이동자수"
    assert search_query("경기도로 전입한 사람 수 추이", {"지역": ["경기도"], "지표": ["전입자수"]}) == "전입한 사람 수 추이 전입자수"
    assert search_query("70~79세 80세 이상", {}) == "70~79세 80세 이상"          # 단어 안의 ~ 는 그대로
    assert search_query("2025년 대구광역시 남자 20~29세 인구수", {"지역": ["대구광역시"], "연령": {"from": 20, "to": 29}}) \
        == "남자 인구수"
    assert search_query("출생아 수 및 사망자 수", {}) == "출생아 수 사망자 수"


def test_point_indicator_key():
    """지표 key 는 핵심 이름이 같을 때만 (포함만으로는 다른 지표)"""
    from backend.rag.view.points import _term_of, item_core, record_points
    assert item_core("총인구수") == "인구수" and item_core("남자인구수(명)") == "인구수"
    assert _term_of("총인구수", ["인구수"]) == "인구수" and _term_of("인구", ["인구수"]) == "인구수"
    assert _term_of("다문화출생아수", ["출생아수"]) is None and _term_of("추계인구", ["인구"]) is None

    def rec(tid, item, v):
        return {"id": f"view::101_{tid}::Y::q-1::value", "source": {"tbl_id": tid}, "metadata": {"unit": "명"},
                "table": {"columns": ["시점", "행정구역(시도)별", "항목", "값"], "rows": [["2025", "서울특별시", item, v]]}}

    f = {"지표": ["출생아수"]}
    a, _ = record_points(rec("A", "출생아수", 100), f)
    b, _ = record_points(rec("B", "다문화출생아수", 10), f)
    assert a[0].key_str() != b[0].key_str()                                     # 다문화 출생아수는 비교하지 않음


def test_view_conflict(tmp_path):
    storage = tmp_path / "storage"
    build_conflict_data(storage / "kosis_data")
    r = _run(["-m", "tests.v4.scenario_view"], ROOT,
             _env(STORAGE_DIR=str(storage), HCX_API_KEY="test-key", CSV_INDEX_DIR="", RUNS_DIR="", QUERY_V4_CONFIG="",
                  VIEW_SELECTION_SECRET=""))
    print(r.stdout)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
    assert '"VIEW_V4": "PASS"' in r.stdout
