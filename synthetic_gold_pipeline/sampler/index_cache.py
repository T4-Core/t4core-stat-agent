"""Metadata Index 캐시 — 표 단위로 저장해 다음 실행과 중단 후 재실행을 빠르게 한다.

  outputs/metadata_index/cache/tables/<ORG_TBL>.json   표 1개 = TableMetadata + 그 표의 View 메타데이터 목록
  outputs/metadata_index/cache/stored/<해시>.json       저장된 View(방식 A) 파일 1개

- 표 하나를 처리할 때마다 바로 원자적으로 저장한다 → 인덱싱 중간에 끊겨도 끝난 표는 다시 읽지 않는다.
- 캐시가 유효한 조건 (모두 만족해야 사용)
    1) 원본 RAW/parquet · 메타 JSON 의 (경로, 크기, 수정 시각) 이 같음
    2) catalog.csv 의 해당 표 행이 같음
    3) View 생성에 영향을 주는 설정(adapter, input.modes/max_views_per_table) 과 캐시 형식 버전이 같음
    4) 캐시에 적힌 View 파일이 모두 있고 크기가 같음
  하나라도 다르면 그 표만 다시 읽는다. index.verify_source_hash=true 면 원본 SHA-256 도 다시 계산해 비교(느리지만 엄격).
- 원본 파일에는 쓰지 않는다. 캐시는 출력 폴더 안에만 쓴다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from synthetic_gold_pipeline.schemas.metadata import TableMetadata, ViewMetadata
from synthetic_gold_pipeline.utils import (atomic_write_text, canonical_json, ensure_inside, resolve_path, safe_name,
                                           sha256_file, stable_hash)

log = logging.getLogger(__name__)
CACHE_FORMAT_VERSION = 2          # 2: 벡터화 스냅샷 해시 (View ID 가 v1 과 다름)


def file_stat(p: Path | None) -> dict[str, Any] | None:
    if p is None:
        return None
    try:
        st = Path(p).stat()
    except OSError:
        return None
    return {"path": Path(p).resolve().as_posix(), "size": st.st_size, "mtime_ns": st.st_mtime_ns}


def view_settings_hash(cfg: dict) -> str:
    """View·표 메타데이터 결과를 바꾸는 설정만 (run·llm 같은 설정 변경은 캐시를 깨지 않음)."""
    icfg = cfg.get("input", {})
    return stable_hash({"v": CACHE_FORMAT_VERSION, "adapter": cfg.get("adapter", {}),
                        "modes": sorted(icfg.get("modes") or []),
                        "max_views_per_table": icfg.get("max_views_per_table")}, 16)


class IndexCache:
    def __init__(self, cache_dir: str | Path, allowed_root: str | Path, cfg: dict, enabled: bool = True,
                 verify_source_hash: bool = False):
        self.dir = Path(cache_dir)
        self.allowed_root = Path(allowed_root)
        self.enabled = enabled
        self.verify = verify_source_hash
        self.settings = view_settings_hash(cfg)
        self.stats = {"table_hits": 0, "table_misses": 0, "stored_hits": 0, "stored_misses": 0, "invalid": {}}

    # ── 지문 ──
    def table_fingerprint(self, ref) -> dict[str, Any]:
        return {"settings": self.settings, "key": ref.key, "data_kind": ref.data_kind, "data": file_stat(ref.data_path),
                "meta": file_stat(ref.meta_path), "catalog": stable_hash(ref.catalog or {}, 16)}

    def stored_fingerprint(self, path: Path, table_fp: dict | None) -> dict[str, Any]:
        return {"settings": self.settings, "file": file_stat(path), "table": table_fp}

    def _table_path(self, key: str) -> Path:
        return self.dir / "tables" / f"{safe_name(key, 150)}.json"

    def _stored_path(self, path: Path) -> Path:
        return self.dir / "stored" / f"{stable_hash(Path(path).resolve().as_posix(), 20)}.json"

    # ── 읽기 ──
    def _read(self, p: Path, fp: dict) -> dict | None:
        if not self.enabled or not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._invalid("corrupt")
            return None
        if canonical_json(d.get("fingerprint")) != canonical_json(fp):
            self._invalid("fingerprint_changed")
            return None
        for vf in d.get("view_files", []):
            q = resolve_path(vf["path"])
            if q is None or not q.exists() or q.stat().st_size != vf["size"]:
                self._invalid("view_file_missing")
                return None
        return d

    def _invalid(self, why: str):
        self.stats["invalid"][why] = self.stats["invalid"].get(why, 0) + 1

    def load_table(self, ref) -> tuple[TableMetadata, list[ViewMetadata]] | None:
        fp = self.table_fingerprint(ref)
        d = self._read(self._table_path(ref.key), fp)
        if d is None:
            self.stats["table_misses"] += 1
            return None
        tm = TableMetadata.model_validate(d["table"])
        if self.verify and sha256_file(ref.data_path) != tm.source_file_hash:
            self._invalid("source_hash_changed")
            self.stats["table_misses"] += 1
            return None
        self.stats["table_hits"] += 1
        return tm, [ViewMetadata.model_validate(v) for v in d["views"]]

    def load_stored(self, path: Path, table_fp: dict | None) -> ViewMetadata | None:
        d = self._read(self._stored_path(path), self.stored_fingerprint(path, table_fp))
        if d is None:
            self.stats["stored_misses"] += 1
            return None
        self.stats["stored_hits"] += 1
        return ViewMetadata.model_validate(d["view"])

    # ── 쓰기 (표 하나 끝날 때마다 즉시) ──
    @staticmethod
    def _view_files(views: list[ViewMetadata]) -> list[dict]:
        out = []
        for v in views:
            q = resolve_path(v.view_file)
            if q is not None and q.exists():
                out.append({"path": v.view_file, "size": q.stat().st_size})
        return out

    def save_table(self, ref, tm: TableMetadata, views: list[ViewMetadata]):
        if not self.enabled:
            return
        p = ensure_inside(self._table_path(ref.key), self.allowed_root)
        payload = {"fingerprint": self.table_fingerprint(ref), "table": tm.model_dump(mode="json"),
                   "views": [v.model_dump(mode="json") for v in views], "view_files": self._view_files(views)}
        atomic_write_text(p, json.dumps(payload, ensure_ascii=False))

    def save_stored(self, path: Path, table_fp: dict | None, vm: ViewMetadata):
        if not self.enabled:
            return
        p = ensure_inside(self._stored_path(path), self.allowed_root)
        payload = {"fingerprint": self.stored_fingerprint(path, table_fp), "view": vm.model_dump(mode="json"),
                   "view_files": []}
        atomic_write_text(p, json.dumps(payload, ensure_ascii=False))
