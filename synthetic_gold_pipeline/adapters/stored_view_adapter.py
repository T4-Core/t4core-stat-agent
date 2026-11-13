"""방식 A: 미리 저장된 View(CSV / Parquet)를 직접 읽는 Adapter.

폴더 구조 (읽기 전용):
  <views_root>/<ORG>_<TBL>/<임의 이름>.csv | .parquet      파일 1개 = View 1개

지원 형식
  1) KOSIS 표준 컬럼 (ORG_ID, TBL_ID, C1.., ITM_ID, PRD_SE, PRD_DE, DT …)
  2) collector store tidy 컬럼 (prd_se, prd_de, cN_code, cN_name, itm_id, itm_nm, unit, value_raw)

원본 좌표
  - View 파일에 _src_row (+ 선택 _src_path) 가 있으면 원본 RAW 행을 가리킨다.
  - 없으면 원본 좌표는 저장된 View 파일 자체(행 번호 1부터, 헤더 제외)를 가리킨다.
표 메타데이터는 같은 표의 RAW·메타가 있으면 그것을 쓰고, 없으면 View 내용으로 추론한다.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from synthetic_gold_pipeline.adapters.kosis_raw_adapter import (AdapterError, KosisRawAdapter, TableRef,
                                                                 build_view_metadata, completeness_of,
                                                                 frame_snapshot_hash, split_table_key,
                                                                 tidy_to_canonical)
from synthetic_gold_pipeline.schemas.metadata import InputMode, TableMetadata, ViewMetadata
from synthetic_gold_pipeline.utils import display_path, normalize_frequency, sha256_file

log = logging.getLogger(__name__)


class StoredViewAdapter:
    def __init__(self, views_root: str | Path, raw_adapter: KosisRawAdapter | None = None, cfg: dict | None = None,
                 known_tables: dict[str, TableMetadata] | None = None):
        """known_tables: 이미 읽은(또는 캐시에서 불러온) 표 메타 — 같은 표의 RAW 를 다시 읽지 않기 위함."""
        self.root = Path(views_root).resolve()
        self.raw = raw_adapter
        self.cfg = cfg or {}
        self._meta_cache: dict[str, tuple[TableMetadata, bool]] = {k: (v, True) for k, v in (known_tables or {}).items()}

    def discover(self) -> list[tuple[str, str, Path]]:
        out = []
        if not self.root.exists():
            return out
        for d in sorted(p for p in self.root.iterdir() if p.is_dir()):
            try:
                org, tbl = split_table_key(d.name)
            except AdapterError:
                log.warning("기관ID_통계표ID 폴더가 아님: %s", d)
                continue
            for f in sorted(list(d.glob("*.csv")) + list(d.glob("*.parquet"))):
                out.append((org, tbl, f))
        return out

    @staticmethod
    def read_view_file(path: Path, org: str, tbl: str) -> pd.DataFrame:
        if path.suffix == ".parquet":
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        if "DT" not in df.columns and "value_raw" in df.columns:
            keep = {c: df[c] for c in ("_src_row", "_src_path") if c in df.columns}
            df = tidy_to_canonical(df, org, tbl)
            for c, v in keep.items():
                df[c] = v.values
        if "DT" not in df.columns or "PRD_DE" not in df.columns or "ITM_ID" not in df.columns:
            raise AdapterError(f"저장된 View 형식을 해석할 수 없음: {path}")
        df = df.copy()
        for c in df.columns:
            if c != "_src_row":
                df[c] = df[c].astype(object).where(df[c].notna(), None).map(lambda v: v if v is None else str(v))
        for c, v in (("ORG_ID", org), ("TBL_ID", tbl), ("PRD_SE", ""), ("ITM_NM", ""), ("UNIT_NM", ""), ("TBL_NM", "")):
            if c not in df.columns:
                df[c] = v
        return df

    def _table_meta(self, org: str, tbl: str, df: pd.DataFrame, path: Path) -> tuple[TableMetadata, bool]:
        key = f"{org}_{tbl}"
        if key in self._meta_cache and self._meta_cache[key][1]:
            return self._meta_cache[key]
        if self.raw is not None:
            refs = [r for r in self.raw.discover(include_tables=[key]) if r.key == key]
            if refs:
                self._meta_cache[key] = (self.raw.load(refs[0]).meta, True)
                return self._meta_cache[key]
        # RAW 없음: View 내용으로 메타 추론
        adapter = self.raw or KosisRawAdapter(self.root, self.cfg)
        ref = TableRef(org, tbl, key, path, "stored_view", None, {}, survey_hint=path.parent.parent.name)
        d = df.copy()
        if "_src_row" not in d.columns:
            d["_src_row"] = range(1, len(d) + 1)
        tm = adapter.build_table_metadata(ref, d, {})
        tm.metadata_source = "stored_view"
        return tm, False

    def load_view_file(self, org: str, tbl: str, f: Path) -> tuple[ViewMetadata, pd.DataFrame] | None:
        try:
            df = self.read_view_file(f, org, tbl)
        except (AdapterError, OSError, ValueError) as e:
            log.warning("저장된 View 읽기 실패 %s: %s", f, e)
            return None
        tm, from_raw = self._table_meta(org, tbl, df, f)
        if "_src_row" in df.columns and from_raw:
            df["_src_row"] = pd.to_numeric(df["_src_row"], errors="coerce").astype("Int64")
            provenance = "raw"          # 원본 RAW 행 번호를 그대로 가리킴
        else:
            df["_src_row"] = range(1, len(df) + 1)
            provenance = "stored_view_file"
            tm = tm.model_copy(update={"source_path": display_path(f), "source_file_hash": sha256_file(f)})
        snap = frame_snapshot_hash(df)
        se = normalize_frequency(next((s for s in df["PRD_SE"].fillna("") if s), ""))
        vid = f"ssv::{tm.parent_table_id}::{f.stem}::{se}::{snap[:8]}"
        vm = build_view_metadata(tm, df, vid, f, InputMode.STORED_VIEW, snap, completeness_of(tm), {})
        vm.metadata_completeness.notes.append(f"stored view provenance={provenance}")
        return vm, df

    def load_views(self) -> list[tuple[ViewMetadata, pd.DataFrame]]:
        out = []
        for org, tbl, f in self.discover():
            r = self.load_view_file(org, tbl, f)
            if r is not None:
                out.append(r)
        return out
