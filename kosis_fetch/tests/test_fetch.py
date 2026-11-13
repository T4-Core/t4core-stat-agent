"""공용 다운로드: 키 가림 · seed 재사용 · 셀 상한 · API 경로(호출은 가짜)"""
import json

import pandas as pd
import pytest

from kosis_fetch import fetch as F

META = {"TBL": [{"TBL_NM": "표"}], "ITM": [
    {"OBJ_ID": "A", "OBJ_NM": "행정구역별", "ITM_ID": "00", "ITM_NM": "전국"},
    {"OBJ_ID": "A", "OBJ_NM": "행정구역별", "ITM_ID": "11", "ITM_NM": "서울특별시"},
    {"OBJ_ID": "ITEM", "OBJ_NM": "항목", "ITM_ID": "T1", "ITM_NM": "인구", "UNIT_NM": "명"}],
    "PRD": [{"PRD_SE": "5년", "STRT_PRD_DE": "2020", "END_PRD_DE": "2020"}], "CMMT": [], "SOURCE": [{"JOSA_NM": "「인구총조사」"}]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    kd = tmp_path / "kosis_data"
    kd.mkdir()
    pd.DataFrame([{"category": "인구총조사", "org_id": "101", "tbl_id": f"DT_S{i}", "tbl_nm": f"표{i}", "path": "a > 표본",
                   "is_sample": "True", "selected": "False", "stat_id": "1962001"} for i in range(3)] +
                 [{"category": "인구총조사", "org_id": "101", "tbl_id": "DT_F", "tbl_nm": "전수", "path": "a",
                   "is_sample": "False", "selected": "True", "stat_id": "1962001"}]).to_csv(kd / "catalog.csv", index=False)
    seed = tmp_path / "seed_meta"
    seed.mkdir()
    (seed / "101_DT_S0.json").write_text(json.dumps(META, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(F, "SEED_META", seed)
    monkeypatch.setattr(F, "SEED_DATA", tmp_path / "seed_data")
    monkeypatch.setattr(F, "full_catalog", lambda: pd.read_csv(kd / "catalog.csv", dtype=str).fillna(""))
    monkeypatch.setenv("KOSIS_EXTRA_DIR", str(tmp_path / "extra"))
    return tmp_path


def test_scrub_hides_key(monkeypatch):
    monkeypatch.setenv("KOSIS_API_KEY", "SECRET123")
    s = F.scrub("ConnectionError: https://kosis.kr/x?apiKey=SECRET123&format=json SECRET123")
    assert "SECRET123" not in s and "apiKey=***" in s


def test_meta_uses_seed_then_api(env, monkeypatch):
    import backend.rag.ingestion.collector as C
    calls = []
    monkeypatch.setattr(C, "API_KEY", "k")
    monkeypatch.setattr(C, "get_meta", lambda o, t, typ: calls.append((t, typ)) or (META[typ]))
    F.main(["meta"])
    sd = F.sample_dir()
    assert {p.name for p in (sd / "meta").glob("*.json")} == {"101_DT_S0.json", "101_DT_S1.json", "101_DT_S2.json"}
    assert {t for t, _ in calls} == {"DT_S1", "DT_S2"}                       # DT_S0 은 seed 에서
    cat = pd.read_csv(sd / "catalog.csv", dtype=str)
    assert set(cat["tbl_id"]) == {"DT_S0", "DT_S1", "DT_S2"} and set(cat["selected"]) == {"True"}


def test_data_respects_max_cells_and_writes_collector_layout(env, monkeypatch):
    import backend.rag.ingestion.collector as C
    monkeypatch.setattr(C, "API_KEY", "k")
    monkeypatch.setattr(C, "get_meta", lambda o, t, typ: META[typ])
    F.main(["meta"])

    def fake_part(part_dir, org, tbl, prd_se, sel, s, e):
        return pd.DataFrame([{"ORG_ID": org, "TBL_ID": tbl, "C1": "00", "C1_NM": "전국", "ITM_ID": "T1",
                              "ITM_NM": "인구", "UNIT_NM": "명", "PRD_SE": prd_se, "PRD_DE": s, "DT": "1"}])
    monkeypatch.setattr(C, "fetch_part", fake_part)
    F.main(["data", "--max-cells", "1"])                                     # 셀 2개 > 1 → 전부 건너뜀
    assert not list((F.sample_dir()).glob("raw/*/*.csv"))
    F.main(["data", "--max-cells", "0"])
    raws = sorted(p.name for p in F.sample_dir().glob("raw/인구총조사/*.csv"))
    assert raws == ["101_DT_S0.csv", "101_DT_S1.csv", "101_DT_S2.csv"]
    log = pd.read_csv(F.sample_dir() / "logs" / "data_log.csv")
    assert (log["source"] == "skip").sum() == 3 and (log["source"] == "api").sum() == 3
