"""Adapter · Metadata Index · Compatibility Graph · ViewClusterSampler."""
from __future__ import annotations

import pandas as pd

from synthetic_gold_pipeline.adapters.kosis_raw_adapter import KosisRawAdapter, split_table_key
from synthetic_gold_pipeline.adapters.view_mapping_adapter import ViewMappingAdapter
from synthetic_gold_pipeline.sampler.view_cluster_sampler import ViewClusterSampler
from synthetic_gold_pipeline.schemas.metadata import DimensionType, InputMode, ObservationType
from synthetic_gold_pipeline.schemas.planning import HopType, ReasoningType
from synthetic_gold_pipeline.tests.conftest import find_view


def test_table_key_parsing_supports_inh_and_dt():
    assert split_table_key("101_DT_1B040A3") == ("101", "DT_1B040A3")
    assert split_table_key("101_INH_1B04005") == ("101", "INH_1B04005")


def test_adapter_does_not_assume_c1_is_region(demo_env):
    t = demo_env["index"].tables["101_DT_DEMO_PROJ"]
    types = {d.level: d.dim_type for d in t.dimension_definitions}
    assert types == {"C1": DimensionType.SCENARIO, "C2": DimensionType.REGION}
    assert t.observed_or_projected == ObservationType.PROJECTED


def test_adapter_sources_raw_only_store_parquet_and_inh(demo_env):
    tabs = demo_env["index"].tables
    assert tabs["101_DT_DEMO_FOREIGN"].metadata_source == "raw_only"          # meta JSON 없음
    assert tabs["101_DT_DEMO_MOVE_Q"].source_path.endswith(".parquet")         # RAW 없이 store parquet
    assert "101_INH_DEMO_MARRY" in tabs
    assert tabs["101_DT_DEMO_DUP"].duplicate_coordinate_rows > 0               # 같은 좌표 중복 행
    assert tabs["101_DT_DEMO_SGG"].dimension_definitions[0].code_name_unique is False   # '중구' 2개


def test_totals_and_hierarchy(demo_env):
    v = demo_env["index"].view(find_view(demo_env["index"], "101_DT_DEMO_POP", "T20", "2024"))
    cm = v.code_map("C1")
    assert cm["00"].is_total and cm["00"].has_children
    assert cm["11"].parent_code == "00" and cm["11"].depth == 1 and not cm["11"].is_total


def test_missing_symbols_preserved_as_text(demo_env):
    df = demo_env["index"].load_frame(find_view(demo_env["index"], "101_DT_DEMO_POP", "T22", "2022"))
    assert "-" in set(df["DT"])                       # 0 으로 바뀌지 않음


def test_stored_view_mode_a_keeps_raw_row_numbers(demo_env):
    idx = demo_env["index"]
    sv = [v for v in idx.views.values() if v.input_mode == InputMode.STORED_VIEW]
    assert len(sv) == 1
    df = idx.load_frame(sv[0].view_id)
    raw = pd.read_csv(demo_env["root"] / "kosis" / "raw" / "주민등록인구현황" / "101_DT_DEMO_POP.csv", dtype=str,
                      keep_default_na=False, encoding="utf-8-sig")
    for _, r in df.iterrows():
        assert raw.iloc[int(r["_src_row"]) - 1]["DT"] == r["DT"]


def test_view_ids_are_stable(demo_env, cfg, tmp_path):
    from synthetic_gold_pipeline.sampler.metadata_index import MetadataIndex
    idx2 = MetadataIndex.build(demo_env["root"] / "kosis", tmp_path / "gv", tmp_path, cfg)
    assert set(idx2.views) == set(demo_env["index"].views)
    assert idx2.snapshot_id() == demo_env["index"].snapshot_id()


def test_inverted_index(demo_env):
    idx = demo_env["index"]
    v11 = idx.inv_code[("REGION", "11")]
    assert any(idx.view(v).parent_table_id == "101_INH_DEMO_MARRY" for v in v11)
    assert len(idx.inv_table["101_DT_DEMO_POP"]) >= 15


def test_monthly_vs_quarterly_same_prd_de_not_comparable(demo_env):
    idx, g = demo_env["index"], demo_env["graph"]
    m = find_view(idx, "101_DT_DEMO_MOVE_M", "T10", "202401")
    q = find_view(idx, "101_DT_DEMO_MOVE_Q", "T10", "202401")
    e = g.edge(m, q)
    assert e.period_relation == "INCOMPARABLE_FREQUENCY"
    assert not e.allowed["RATIO"] and not e.allowed["CONDITIONAL"] and not e.allowed["TIME_SERIES"]


def test_observed_vs_projected_not_combined(demo_env):
    idx, g = demo_env["index"], demo_env["graph"]
    pop = find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    proj = find_view(idx, "101_DT_DEMO_PROJ", "T1", "2024", {"C1": ["1"]})
    e = g.edge(pop, proj)
    assert not e.allowed["RATIO"] and not e.allowed["CONDITIONAL"]
    assert any("추계" in r for r in e.reasons["RATIO"])


def test_code_system_mismatch_is_structurally_incompatible(demo_env):
    idx, g = demo_env["index"], demo_env["graph"]
    a = find_view(idx, "101_DT_DEMO_SGG", "T1", "2024")
    b = find_view(idx, "101_DT_DEMO_SGG_HH", "T1", "2024")
    j = g.edge(a, b).join[0]
    assert j.common_codes == ["11140"] and not j.structural_ok and j.name_mismatches


def test_time_series_only_within_same_table_item(demo_env):
    idx, g = demo_env["index"], demo_env["graph"]
    a = find_view(idx, "101_DT_DEMO_POP", "T20", "2023")
    b = find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    c = find_view(idx, "101_DT_DEMO_POP_OLD", "T20", "2024")
    assert g.edge(a, b).allowed["TIME_SERIES"]
    assert not g.edge(a, c).allowed["TIME_SERIES"]          # 다른 표 → 같은 시계열로 간주하지 않음


def test_duplicate_rows_flag_join_risk(demo_env):
    idx, g = demo_env["index"], demo_env["graph"]
    a = find_view(idx, "101_DT_DEMO_DUP", "T1", "2024")
    b = find_view(idx, "101_DT_DEMO_POP", "T20", "2024")
    e = g.edge(a, b)
    assert e.duplicate_risk and not e.allowed["CONDITIONAL"]


def test_sampler_covers_types_and_hop_classification(demo_env):
    s = ViewClusterSampler(demo_env["index"], demo_env["graph"], demo_env["cfg"]["sampler"], base_seed=7)
    seen = set()
    for i in range(45):
        rt = [ReasoningType.TIME_SERIES_COMPARISON, ReasoningType.CROSS_TABLE_RATIO,
              ReasoningType.CONDITIONAL_AGGREGATION][i % 3]
        c = s.sample(rt, i)
        if c is None:
            continue
        seen.add((rt, c.hop_type))
        tables = {demo_env["index"].view(v).parent_table_id for v in c.view_ids}
        assert (len(tables) > 1) == (c.hop_type == HopType.MULTI_TABLE_MULTI_VIEW)
        assert 2 <= len(c.view_ids) <= 3
        assert not set(c.hard_negative_candidates) & set(c.view_ids)
        if rt == ReasoningType.TIME_SERIES_COMPARISON:
            assert c.hop_type == HopType.SINGLE_TABLE_MULTI_VIEW
        if rt == ReasoningType.CROSS_TABLE_RATIO:
            assert c.hop_type == HopType.MULTI_TABLE_MULTI_VIEW
    assert (ReasoningType.CONDITIONAL_AGGREGATION, HopType.MULTI_TABLE_MULTI_VIEW) in seen


def test_sampler_is_reproducible(demo_env):
    a = ViewClusterSampler(demo_env["index"], demo_env["graph"], demo_env["cfg"]["sampler"], base_seed=11)
    b = ViewClusterSampler(demo_env["index"], demo_env["graph"], demo_env["cfg"]["sampler"], base_seed=11)
    for i in range(10):
        ca, cb = a.sample(ReasoningType.CROSS_TABLE_RATIO, i), b.sample(ReasoningType.CROSS_TABLE_RATIO, i)
        assert (ca and ca.view_ids, ca and ca.random_seed) == (cb and cb.view_ids, cb and cb.random_seed)


def test_sampler_table_cap(demo_env):
    s = ViewClusterSampler(demo_env["index"], demo_env["graph"], {**demo_env["cfg"]["sampler"], "max_samples_per_table": 1},
                           base_seed=3)
    c = s.sample(ReasoningType.TIME_SERIES_COMPARISON, 0)
    s.register_accepted(c)
    for i in range(1, 15):
        c2 = s.sample(ReasoningType.TIME_SERIES_COMPARISON, i)
        if c2:
            assert not set(c2.table_ids) & set(c.table_ids)


def test_view_mapping_unmapped_when_no_existing_views(demo_env, tmp_path, monkeypatch):
    monkeypatch.delenv("RAG_VIEWS_DIR", raising=False)
    m = ViewMappingAdapter(tmp_path / "nope.jsonl")
    vid = find_view(demo_env["index"], "101_DT_DEMO_POP", "T20", "2024")
    if not m.available:
        r = m.map_view(demo_env["index"].view(vid))
        assert r["status"] == "UNMAPPED" and r["existing_rag_view_ids"] == []


def test_view_mapping_with_existing_views(demo_env, tmp_path):
    import json
    p = tmp_path / "views.jsonl"
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in [
        {"id": "view::101_DT_DEMO_POP::Y::00::trend",
         "source": {"table_key": "101_DT_DEMO_POP", "prd_se": "Y", "itm_id": ["T20"], "dims": {"c1": {"codes": ["00"]}},
                    "period": {}}},
        {"id": "view::101_DT_DEMO_POP::Y::05::breakdown",
         "source": {"table_key": "101_DT_DEMO_POP", "prd_se": "Y", "itm_id": ["T20"], "dims": {}, "period": {"in": ["2024"]}}},
    ]), encoding="utf-8")
    m = ViewMappingAdapter(p)
    vid = find_view(demo_env["index"], "101_DT_DEMO_POP", "T20", "2024")
    r = m.map_view(demo_env["index"].view(vid))
    assert r["status"] in ("MAPPED_EXACT", "MAPPED_CONTAINING")
    assert r["existing_rag_view_ids"] == ["view::101_DT_DEMO_POP::Y::05::breakdown"]


def test_dimension_classification_keywords():
    a = KosisRawAdapter(".")
    assert a.classify_dimension("가구주의 성별")[0] == DimensionType.SEX
    assert a.classify_dimension("행정구역(시군구)별")[0] == DimensionType.REGION
    assert a.classify_dimension("연령별(5세)")[0] == DimensionType.AGE
    assert a.classify_dimension("산업별")[0] == DimensionType.INDUSTRY
    assert a.classify_dimension("임의분류")[0] == DimensionType.OTHER


# ── Metadata Index 캐시 ─────────────────────────────────────────────
def _build(root, cfg, rebuild=False):
    from synthetic_gold_pipeline.sampler.metadata_index import MetadataIndex
    return MetadataIndex.build(root / "kosis", root / "gv", root, cfg, cache_dir=root / "cache", rebuild=rebuild)


def _fresh(tmp_path):
    from synthetic_gold_pipeline.demo_data import build_demo_dataset
    build_demo_dataset(tmp_path / "kosis")
    return tmp_path


def test_index_cache_reused_and_identical(tmp_path, cfg):
    root = _fresh(tmp_path)
    a = _build(root, cfg)
    b = _build(root, cfg)
    assert a.build_info["cache"]["table_misses"] == 13 and b.build_info["cache"]["table_hits"] == 13
    assert b.build_info["cache"]["table_misses"] == 0 and b.build_info["cache"]["stored_hits"] == 1
    assert a.snapshot_id() == b.snapshot_id()
    assert {k: v.model_dump() for k, v in a.views.items()} == {k: v.model_dump() for k, v in b.views.items()}


def test_index_cache_resumes_after_interruption(tmp_path, cfg, monkeypatch):
    import pytest
    root = _fresh(tmp_path)
    orig = KosisRawAdapter.load
    calls = {"n": 0}

    def flaky(self, ref):
        calls["n"] += 1
        if calls["n"] == 5:
            raise KeyboardInterrupt("중단 시뮬레이션")
        return orig(self, ref)
    monkeypatch.setattr(KosisRawAdapter, "load", flaky)
    with pytest.raises(KeyboardInterrupt):
        _build(root, cfg)
    monkeypatch.setattr(KosisRawAdapter, "load", orig)
    b = _build(root, cfg)
    assert b.build_info["cache"]["table_hits"] == 4 and b.build_info["cache"]["table_misses"] == 9


def test_index_cache_invalidation(tmp_path, cfg):
    root = _fresh(tmp_path)
    _build(root, cfg)
    raw = root / "kosis" / "raw" / "인구동향조사" / "101_INH_DEMO_MARRY.csv"
    df = pd.read_csv(raw, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df.loc[0, "DT"] = "123456789"
    df.to_csv(raw, index=False, encoding="utf-8-sig")
    b = _build(root, cfg)
    assert b.build_info["cache"]["table_misses"] == 1 and b.build_info["cache"]["invalid"] == {"fingerprint_changed": 1}
    v = next(v for v in b.views.values() if v.parent_table_id == "101_DT_DEMO_POP")
    from synthetic_gold_pipeline.utils import resolve_path
    resolve_path(v.view_file).unlink()
    c = _build(root, cfg)
    assert c.build_info["cache"]["invalid"] == {"view_file_missing": 1} and v.view_id in c.views
    cfg2 = {**cfg, "adapter": {**cfg["adapter"], "split_dimension_types": []}}
    d = _build(root, cfg2)
    assert d.build_info["cache"]["table_hits"] == 0                       # View 생성 설정이 바뀜 → 전부 다시
    e = _build(root, cfg, rebuild=True)
    assert e.build_info["cache"]["table_hits"] == 0 and e.build_info["cache"]["table_misses"] == 13


# ── 인덱싱 성능 최적화가 결과를 바꾸지 않는지 ─────────────────────────
def test_numeric_mask_matches_parse_value():
    import numpy as np
    from synthetic_gold_pipeline.adapters.kosis_raw_adapter import numeric_mask
    from synthetic_gold_pipeline.tools.units import parse_value
    vals = ["1", "0", "-3", "1,234", "1,234.5", " 12 ", "1 234", "-", "*", "X", "x", "NaN", "nan", "", " ", "…", "..",
            "1.2.3", "12a", "+5", "−", "1,23", "007", None]
    got = numeric_mask(pd.Series(vals, dtype=object))
    assert got.tolist() == [parse_value(v).ok for v in vals]
    assert numeric_mask(pd.Series(["5", "-"], dtype="str")).dtype == np.bool_


def test_select_recent_and_snapshot_hash_are_order_independent():
    from synthetic_gold_pipeline.adapters.kosis_raw_adapter import frame_snapshot_hash, select_recent
    cand = [(("T1", "A", y), None, 1) for y in ("2021", "2022", "2023")] + [(("T2", "A", y), None, 1) for y in ("2022", "2023")]
    assert [c[0] for c in select_recent(cand, 3)] == [("T1", "A", "2023"), ("T2", "A", "2023"), ("T1", "A", "2022")]
    df = pd.DataFrame({"ITM_ID": ["a", "b"], "PRD_DE": ["1", "2"], "DT": ["-", "3"], "_src_row": [2, 1]})
    assert frame_snapshot_hash(df) == frame_snapshot_hash(df.iloc[::-1])


def test_parallel_index_equals_sequential(tmp_path, cfg):
    from synthetic_gold_pipeline.sampler.metadata_index import MetadataIndex
    root = _fresh(tmp_path)
    seq = MetadataIndex.build(root / "kosis", root / "gv1", root, {**cfg, "index": {**cfg["index"], "workers": 1}},
                              cache_dir=root / "c1")
    par = MetadataIndex.build(root / "kosis", root / "gv2", root,
                              {**cfg, "index": {**cfg["index"], "workers": 2, "mp_start_method": "spawn"}},
                              cache_dir=root / "c2")
    assert list(seq.views) == list(par.views) and seq.snapshot_id() == par.snapshot_id()
    drop = {"view_file", "view_file_hash"}
    assert [{k: v for k, v in x.model_dump().items() if k not in drop} for x in seq.views.values()] == \
           [{k: v for k, v in x.model_dump().items() if k not in drop} for x in par.views.values()]


def test_max_views_per_table_limits_before_writing(tmp_path, cfg):
    from synthetic_gold_pipeline.sampler.metadata_index import MetadataIndex
    root = _fresh(tmp_path)
    idx = MetadataIndex.build(root / "kosis", root / "gv", root, {**cfg, "input": {**cfg["input"], "max_views_per_table": 3}},
                              cache_dir=root / "c")
    pop = [v for v in idx.views.values() if v.parent_table_id == "101_DT_DEMO_POP" and v.input_mode.value == "GENERATED_FROM_RAW"]
    assert len(pop) == 3 and {v.available_periods[0] for v in pop} == {"2024"}        # 최근 시점, 항목 번갈아
    assert len(list((root / "gv" / "101_DT_DEMO_POP").glob("*.parquet"))) == 3       # 버릴 View 는 파일도 안 씀
