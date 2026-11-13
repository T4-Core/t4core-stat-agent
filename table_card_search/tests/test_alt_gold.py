"""[NEW 11-12] 정답 판정 (alt_gold) — 가짜 KOSIS 데이터 + CSV 값 사전 (HCX·네트워크 없음)
같은 값을 가진 다른 표 = 대체 정답 (단위가 달라도 환산해서 같으면 / 큰 단위로 반올림한 표는 rounded), 값이 다른 표는 아님"""
import json

import pandas as pd

from tests import fake_kosis


def _clone(kd, src_tbl, new_tbl, name, fn=None, unit=None):
    src = kd / "raw" / "주민등록인구현황" / f"101_{src_tbl}.csv"
    b = pd.read_csv(src, dtype=str, encoding="utf-8-sig")
    b["TBL_ID"], b["TBL_NM"] = new_tbl, name
    if fn:
        b["DT"] = b["DT"].astype(float).map(fn).map(lambda x: f"{x:g}")
    if unit:
        b["UNIT_NM"] = unit
    b.to_csv(src.with_name(f"101_{new_tbl}.csv"), index=False, encoding="utf-8-sig")
    m = json.loads((kd / "meta" / f"101_{src_tbl}.json").read_text(encoding="utf-8"))
    m["TBL"] = [{"TBL_NM": name}]
    (kd / "meta" / f"101_{new_tbl}.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    cat = pd.read_csv(kd / "catalog.csv", dtype=str, encoding="utf-8-sig")
    row = cat[cat["tbl_id"] == src_tbl].iloc[0].copy()
    row["tbl_id"], row["tbl_nm"] = new_tbl, name
    pd.concat([cat, row.to_frame().T]).to_csv(kd / "catalog.csv", index=False, encoding="utf-8-sig")


def _fact(kd, region, year, item="총인구수"):
    df = pd.read_csv(kd / "raw" / "주민등록인구현황" / "101_DT_1B040A3.csv", dtype=str, encoding="utf-8-sig")
    r = df[(df["C1_NM"] == region) & (df["PRD_DE"] == str(year)) & (df["ITM_NM"] == item)].iloc[0]
    return {"fact_id": f"F_{region}", "view_id": "v", "parent_table_id": "101_DT_1B040A3", "kind": "SCALAR",
            "period": f"{year}년", "item_name": item, "coordinate_labels": {"행정구역(시군구)별": region}, "unit": "명",
            "value": {"raw": float(r["DT"]), "display_digits": 0},
            "coordinate": {"TBL_ID": "DT_1B040A3", "PRD_SE": r["PRD_SE"], "PRD_DE": r["PRD_DE"], "ITM_NM": item,
                           "UNIT_NM": "명", "normalized_value": r["DT"], "normalized_unit": "명"}}


def test_alt_gold(tmp_path):
    kd = tmp_path / "kosis_data"
    fake_kosis.build(kd)
    _clone(kd, "DT_1B040A3", "DT_ALT_SAME", "시도별 주민등록 인구 (다른 표)")
    _clone(kd, "DT_1B040A3", "DT_ALT_K", "시도별 인구 (천명)", fn=lambda v: round(v / 1000, 1), unit="천명")
    _clone(kd, "DT_1B040A3", "DT_ALT_DIFF", "시도별 추정 인구", fn=lambda v: v + 5)
    from backend.rag.csv_index.source import KosisRawCsvSource
    from backend.rag.csv_index.store import build_index, load_index
    build_index(source=KosisRawCsvSource(kd), scope="all", workers=1, out_dir=tmp_path / "ci", log=lambda *a: None)
    from table_card_search.alt_gold import Judge, load_alt
    judge = Judge(load_index(tmp_path / "ci"), log=lambda *a: None)
    seoul, total = _fact(kd, "서울특별시", 2023), _fact(kd, "전국", 2024)
    rec = {"dataset_id": "SG-1", "answerability_type": "ANSWERABLE",
           "retrieval_eval": {"golden_table_ids": ["DT_1B040A3"], "required_evidence_groups": {
               "R1": {"acceptable_table_ids": ["101_DT_1B040A3"], "required_fact_ids": [seoul["fact_id"]]},
               "R2": {"acceptable_table_ids": ["101_DT_1B040A3"], "required_fact_ids": [total["fact_id"]]}}},
           "generation_eval": {"intermediate_facts": [seoul, total]}}
    res = judge.judge(rec)
    got = {g: {a["tbl_id"]: a["match"] for a in v["alternatives"]} for g, v in res["groups"].items()}
    assert got["R1"] == {"DT_ALT_SAME": "exact", "DT_ALT_K": "rounded"}, got     # 값이 다른 DT_ALT_DIFF 는 아님
    assert got["R2"] == {"DT_ALT_SAME": "exact", "DT_ALT_K": "rounded"}, got     # 총계(전국) 사실도
    p = tmp_path / "alt.jsonl"
    p.write_text(json.dumps(res, ensure_ascii=False) + "\n", encoding="utf-8")
    assert load_alt(p) == {"SG-1": {"R1": ["DT_ALT_K", "DT_ALT_SAME"], "R2": ["DT_ALT_K", "DT_ALT_SAME"]}}
    assert load_alt(p, include_rounded=False) == {"SG-1": {"R1": ["DT_ALT_SAME"], "R2": ["DT_ALT_SAME"]}}
    # 다른 항목(남자인구수)의 사실이면 총인구수 값이 같아도 대체 정답 아님 — 항목이 맞아야 함
    male = _fact(kd, "서울특별시", 2023, item="남자인구수")
    r2 = judge.judge({**rec, "retrieval_eval": {"golden_table_ids": ["DT_1B040A3"], "required_evidence_groups": {}},
                      "generation_eval": {"intermediate_facts": [male]}})
    assert set(a["tbl_id"] for a in r2["groups"]["ALL"]["alternatives"]) == {"DT_ALT_SAME", "DT_ALT_K"}
    skipped = judge.judge({**rec, "answerability_type": "UNANSWERABLE"})
    assert skipped["status"] == "skipped"
