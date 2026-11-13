"""모든 View 의 메타데이터와 실제 고유 차원값을 스캔한 공통 차원 인덱스 (역색인).

  inv_code[(dim_type, code)]      → View ID 집합   (Join Key 후보 탐색: 전체 쌍 비교 대신)
  inv_table[parent_table_id]      → View ID 집합
  inv_item[정규화 항목명]           → View ID 집합   (Hard Negative · 대체 Positive 후보)
  inv_period[(주기, 시점)]          → View ID 집합

View 데이터 프레임은 필요할 때만 읽고 LRU 로 캐시한다.
"""
from __future__ import annotations

import json
import logging
import multiprocessing
import os
import re
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from synthetic_gold_pipeline.adapters.kosis_raw_adapter import AdapterError, KosisRawAdapter, RawViewGenerator
from synthetic_gold_pipeline.adapters.stored_view_adapter import StoredViewAdapter
from synthetic_gold_pipeline.sampler.index_cache import IndexCache
from synthetic_gold_pipeline.schemas.metadata import TableMetadata, ViewCard, ViewMetadata
from synthetic_gold_pipeline.tools.units import parse_value
from synthetic_gold_pipeline.utils import atomic_write_json, display_path, resolve_path, stable_hash, write_jsonl

log = logging.getLogger(__name__)


def norm_item_name(s: str) -> str:
    s = re.sub(r"\s+", "", str(s or ""))
    s = re.sub(r"[()\[\]·_\-]", "", s)
    return s.replace("수", "") if len(s) > 2 and s.endswith("수") else s


class MetadataIndex:
    def __init__(self, views: list[ViewMetadata], tables: dict[str, TableMetadata], frame_cache_size: int = 128,
                 build_info: dict | None = None):
        self.views: dict[str, ViewMetadata] = {v.view_id: v for v in views}
        self.tables = tables
        self.build_info = build_info or {}
        self._frames: OrderedDict[str, pd.DataFrame] = OrderedDict()
        self._cache_size = frame_cache_size
        self._lock = threading.RLock()
        self.inv_code: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.inv_table: dict[str, set[str]] = defaultdict(set)
        self.inv_item: dict[str, set[str]] = defaultdict(set)
        self.inv_period: dict[tuple[str, str], set[str]] = defaultdict(set)
        for v in views:
            self._index(v)

    def _index(self, v: ViewMetadata):
        self.inv_table[v.parent_table_id].add(v.view_id)
        for d in v.dimension_definitions:
            for c in v.dimension_codes.get(d.level, []):
                self.inv_code[(d.dim_type.value, c.code)].add(v.view_id)
        for i in v.indicator_definitions:
            self.inv_item[norm_item_name(i.itm_nm)].add(v.view_id)
        for p in v.available_periods:
            self.inv_period[(v.period_frequency, p)].add(v.view_id)

    # ── 생성 ──────────────────────────────────────────────────────
    @classmethod
    def build(cls, data_root: str | Path, generated_views_dir: str | Path, allowed_root: str | Path,
              cfg: dict, cache_dir: str | Path | None = None, rebuild: bool = False) -> "MetadataIndex":
        """cache_dir 를 주면 표 단위 캐시 사용 (표 하나 끝날 때마다 저장 → 중단돼도 끝난 표는 다시 읽지 않음).
        rebuild=True 면 캐시를 무시하고 전부 다시 읽는다 (새 결과로 캐시를 덮어씀)."""
        acfg = cfg.get("adapter", {})
        icfg = cfg.get("input", {})
        xcfg = cfg.get("index", {})
        raw = KosisRawAdapter(data_root, acfg)
        gen = RawViewGenerator(generated_views_dir, allowed_root, acfg)
        cache = IndexCache(cache_dir or Path(allowed_root) / "metadata_index" / "cache", allowed_root, cfg,
                           enabled=bool(xcfg.get("cache_enabled", True)) and cache_dir is not None,
                           verify_source_hash=bool(xcfg.get("verify_source_hash", False)))
        views: list[ViewMetadata] = []
        tables: dict[str, TableMetadata] = {}
        failures = []
        modes = set(icfg.get("modes") or ["GENERATED_FROM_RAW", "STORED_VIEW"])
        refs = raw.discover(only_selected=bool(icfg.get("only_selected", False)),
                            include_tables=icfg.get("include_tables") or None)
        max_tables = icfg.get("max_tables")
        if max_tables:
            refs = refs[: int(max_tables)]
        max_views_per_table = int(icfg.get("max_views_per_table") or 0)
        every = int(xcfg.get("progress_every", 50))
        t0 = time.time()
        fps, results, todo = {}, {}, []
        for ref in refs:
            fps[ref.key] = cache.table_fingerprint(ref)
            hit = cache.load_table(ref) if not rebuild else None
            if rebuild:
                cache.stats["table_misses"] += 1
            if hit is not None:
                results[ref.key] = hit
            else:
                todo.append(ref)
        gen_views = "GENERATED_FROM_RAW" in modes
        workers = resolve_workers(xcfg.get("workers", "auto"), len(todo))
        done = [0]

        def finish(ref, out):
            if out[0] == "fail":
                failures.append({"table": ref.key, "error": out[1]})
            else:
                tm, vs = out[1], out[2]
                cache.save_table(ref, tm, vs)            # 표 하나 끝날 때마다 즉시 저장 (중단돼도 이어서)
                results[ref.key] = (tm, vs)
            done[0] += 1
            if every and (done[0] % every == 0 or done[0] == len(todo)):
                log.info("인덱싱 새로 읽음 %d/%d 표 (캐시 사용 %d, 작업자 %d) %.0fs", done[0], len(todo),
                         cache.stats["table_hits"], workers, time.time() - t0)
        if todo and workers > 1:
            ctx = multiprocessing.get_context(xcfg.get("mp_start_method") or None)   # Windows 기본 = spawn
            with ProcessPoolExecutor(max_workers=workers, mp_context=ctx, initializer=_init_worker,
                                     initargs=(str(data_root), acfg, str(generated_views_dir), str(allowed_root))) as ex:
                futs = {ex.submit(_process_table, ref, gen_views, max_views_per_table): ref for ref in todo}
                try:
                    for fu in as_completed(futs):
                        finish(futs[fu], fu.result())
                except BaseException:
                    ex.shutdown(wait=False, cancel_futures=True)
                    raise
        else:
            _W.update(raw=raw, gen=gen)
            for ref in todo:
                finish(ref, _process_table(ref, gen_views, max_views_per_table))
        for ref in refs:                                 # 결과 순서는 표 순서로 고정 (병렬이어도 재현 가능)
            if ref.key in results:
                tm, vs = results[ref.key]
                tables[tm.parent_table_id] = tm
                views += vs
        if "STORED_VIEW" in modes:
            roots = [resolve_path(p) for p in (icfg.get("stored_view_roots") or [])]
            roots.append(Path(data_root) / "stored_views")
            for r in dict.fromkeys(p for p in roots if p):
                sva = StoredViewAdapter(r, raw, acfg, known_tables=tables)
                for org, tbl, f in sva.discover():
                    tfp = fps.get(f"{org}_{tbl}")
                    vm = cache.load_stored(f, tfp) if not rebuild else None
                    if rebuild:
                        cache.stats["stored_misses"] += 1
                    if vm is None:
                        got = sva.load_view_file(org, tbl, f)
                        if got is None:
                            continue
                        vm = got[0]
                        cache.save_stored(f, tfp, vm)
                    views.append(vm)
        info = {"data_root": display_path(data_root), "n_tables": len(tables), "n_views": len(views),
                "table_failures": failures, "modes": sorted(modes), "index_seconds": round(time.time() - t0, 2),
                "cache": {"enabled": cache.enabled, "rebuild": rebuild, **cache.stats}}
        return cls(views, tables, int(xcfg.get("frame_cache_size", 128)), info)

    # ── 조회 ──────────────────────────────────────────────────────
    def view(self, view_id: str) -> ViewMetadata:
        return self.views[view_id]

    def load_frame(self, view_id: str) -> pd.DataFrame:
        with self._lock:                     # 비동기 작업의 스레드들이 캐시를 함께 씀
            return self._load_frame(view_id)

    def _load_frame(self, view_id: str) -> pd.DataFrame:
        if view_id in self._frames:
            self._frames.move_to_end(view_id)
            return self._frames[view_id]
        v = self.views[view_id]
        p = resolve_path(v.view_file)
        if p.suffix == ".parquet":
            df = pd.read_parquet(p)
        else:
            df = pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        for c in df.columns:
            if c != "_src_row":
                df[c] = df[c].astype(object).where(df[c].notna(), None).map(lambda x: x if x is None else str(x))
        df["_src_row"] = pd.to_numeric(df["_src_row"], errors="coerce").astype("Int64")
        self._frames[view_id] = df
        if len(self._frames) > self._cache_size:
            self._frames.popitem(last=False)
        return df

    def snapshot_id(self) -> str:
        tabs = sorted((k, t.source_file_hash) for k, t in self.tables.items())
        vs = sorted((v.view_id, v.data_snapshot_hash) for v in self.views.values())
        return "snap_" + stable_hash({"tables": tabs, "views": vs}, 20)

    def views_of_table(self, table_id: str) -> list[ViewMetadata]:
        return [self.views[v] for v in sorted(self.inv_table.get(table_id, ()))]

    def view_card(self, view_id: str, max_codes: int = 40, sample_rows: int = 3) -> ViewCard:
        v = self.views[view_id]
        df = self.load_frame(view_id)
        dims = []
        for d in v.dimension_definitions:
            cs = v.dimension_codes.get(d.level, [])
            dims.append({"level": d.level, "obj_nm": d.obj_nm, "dim_type": d.dim_type.value, "n_codes": len(cs),
                         "codes": [{"code": c.code, "name": c.name, "is_total": c.is_total, "depth": c.depth,
                                    "parent": c.parent_code} for c in cs[:max_codes]],
                         "truncated": len(cs) > max_codes})
        cols = [c for c in df.columns if c in ("PRD_DE", "ITM_ID", "ITM_NM", "UNIT_NM", "DT") or re.fullmatch(r"C\d(_NM)?", c)]
        rows = df[cols].head(sample_rows).to_dict("records")
        return ViewCard(view_id=v.view_id, parent_table_id=v.parent_table_id, survey_name=v.survey_name,
                        table_title=v.table_title,
                        items=[{"itm_id": i.itm_id, "itm_nm": i.itm_nm, "unit": i.unit_nm, "value_kind": i.value_kind.value}
                               for i in v.indicator_definitions],
                        dimensions=dims, periods=v.available_periods, period_frequency=v.period_frequency,
                        units=v.units, population_scope=v.population_scope,
                        observed_or_projected=v.observed_or_projected.value, scenario=v.scenario, sample_rows=rows)

    def numeric_rows(self, view_id: str, itm_id: str, prd_de: str) -> pd.DataFrame:
        df = self.load_frame(view_id)
        d = df[(df["ITM_ID"] == itm_id) & (df["PRD_DE"] == prd_de)].copy()
        d["_parsed"] = [parse_value(x) for x in d["DT"]]
        return d

    def catalog_scope(self) -> dict[str, Any]:
        """CORPUS_UNANSWERABLE 판정 범위: 수집된 전체 표·항목·시점."""
        items: dict[str, dict] = {}
        for t in self.tables.values():
            for i in t.indicator_definitions:
                e = items.setdefault(norm_item_name(i.itm_nm), {"names": set(), "tables": set(), "periods": set()})
                e["names"].add(i.itm_nm)
                e["tables"].add(t.parent_table_id)
                for ps in t.periods.values():
                    e["periods"].update(ps)
        return {"n_tables": len(self.tables), "n_views": len(self.views),
                "table_ids": sorted(self.tables), "items": items,
                "titles": {k: t.table_title for k, t in self.tables.items()},
                "surveys": sorted({t.survey_name for t in self.tables.values()})}

    # ── 저장 ──────────────────────────────────────────────────────
    def save(self, out_dir: str | Path) -> dict[str, str]:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        write_jsonl(out / "views.jsonl", list(self.views.values()))
        write_jsonl(out / "tables.jsonl", list(self.tables.values()))
        inv = {"n_code_keys": len(self.inv_code), "n_item_keys": len(self.inv_item),
               "code_index_sample": {f"{k[0]}:{k[1]}": sorted(v)[:10] for k, v in list(sorted(self.inv_code.items()))[:200]}}
        atomic_write_json(out / "index_summary.json", {"snapshot_id": self.snapshot_id(), **self.build_info, **inv})
        return {"views": display_path(out / "views.jsonl"), "tables": display_path(out / "tables.jsonl")}


def resolve_workers(val, n_todo: int) -> int:
    """index.workers: 'auto' = min(4, CPU 수 - 1), 숫자 = 그 수. 새로 읽을 표가 1개 이하면 1."""
    if n_todo <= 1:
        return 1
    if str(val).lower() == "auto":
        return max(1, min(4, (os.cpu_count() or 2) - 1))
    return max(1, int(val))


_W: dict = {}


def _init_worker(data_root: str, acfg: dict, gen_dir: str, allowed_root: str):
    _W["raw"] = KosisRawAdapter(data_root, acfg)
    _W["gen"] = RawViewGenerator(gen_dir, allowed_root, acfg)


def _process_table(ref, gen_views: bool, max_views: int):
    """표 1개 처리 (작업자 프로세스에서도 실행). 실패는 예외 대신 ('fail', 메시지)로 돌려준다."""
    try:
        lt = _W["raw"].load(ref)
    except (AdapterError, OSError, ValueError, KeyError) as e:
        return ("fail", f"{type(e).__name__}: {e}")
    vs = _W["gen"].generate(lt, max_views) if gen_views else []
    return ("ok", lt.meta, vs)


def dump_json(obj: Any) -> str:  # pragma: no cover - 디버그용
    return json.dumps(obj, ensure_ascii=False, default=lambda o: sorted(o) if isinstance(o, set) else str(o))
