"""
입력 읽기 — 카탈로그 · 메타 JSON · 원본 CSV(행·열·시점 스캔) · 통계설명

카드 묶음(set)마다 입력 폴더가 다름 (table_card 의 CARD_SET 과 같은 구분)
  full    storage/kosis_data (KOSIS_DATA_DIR) — 이미 받아 둔 전수·인구 14개 조사. 기본 범위 = catalog selected
  sample  <KOSIS_EXTRA_DIR>/sample          — 공용 다운로드(kosis_fetch)로 받은 표본 표. collector 와 같은 모양
통계설명은 두 묶음 모두 <KOSIS_EXTRA_DIR>/expl/<stat_id>.json (kosis_fetch expl) 이 있을 때만 씀

원본 CSV 스캔은 기존 CSV 값 사전 코드(backend.rag.csv_index.scanner.scan_kosis_csv)를 그대로 씀
  1) 이미 만들어 둔 CSV 값 사전(storage/csv_index/tables.jsonl)에 같은 서명의 표가 있으면 그것을 재사용 (48GB 를 다시 읽지 않음)
  2) 없으면 직접 스캔하고 <출력>/cache/scan/<기관>_<표>.json 에 저장 (원본 크기·수정시각이 같으면 다음에 재사용)
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

SETS = ("full", "sample")


@dataclass
class TableSrc:
    set_name: str
    org_id: str
    tbl_id: str
    tbl_nm: str
    category: str
    section: str
    path: str
    survey_type: str
    also_in: str
    stat_id: str
    selected: bool
    meta_path: Path
    raw_path: Path

    @property
    def key(self):
        return f"{self.org_id}_{self.tbl_id}"

    def meta(self):
        if not self.meta_path.exists():
            return {}
        try:
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except ValueError:
            return {}


def data_dir(set_name) -> Path:
    if set_name == "full":
        from backend.core.config import KOSIS_DATA_DIR
        return Path(KOSIS_DATA_DIR)
    if set_name == "sample":
        from kosis_fetch.fetch import sample_dir
        return sample_dir()
    raise ValueError(f"set 은 {SETS}: {set_name}")


def expl_dir() -> Path:
    from kosis_fetch.fetch import extra_dir
    return extra_dir() / "expl"


def list_tables(set_name="full", scope="selected", limit=None, tables=None) -> list[TableSrc]:
    """scope=selected: catalog selected 행 (table_card 와 같은 대상). all: 원본 CSV 가 있는 catalog 행 전체(표본 제외)"""
    from backend.core.utils import safe
    d = data_dir(set_name)
    p = d / "catalog.csv"
    if not p.exists():
        raise FileNotFoundError(f"catalog.csv 없음: {p}" + ("  (python -m kosis_fetch.fetch meta 먼저)" if set_name == "sample" else ""))
    cat = pd.read_csv(p, dtype=str).fillna("")
    if set_name == "full":
        if scope == "selected":
            cat = cat[cat["selected"] == "True"]
        else:
            cat = cat[cat.get("is_sample", pd.Series("False", index=cat.index)) != "True"]
    cat = cat.drop_duplicates(["org_id", "tbl_id"])
    out = []
    for r in cat.to_dict("records"):
        if tables and r["tbl_id"] not in tables:
            continue
        raw = d / "raw" / safe(r.get("category", "")) / f"{r['org_id']}_{r['tbl_id']}.csv"
        if set_name == "full" and scope == "all" and not raw.exists():
            continue
        out.append(TableSrc(set_name, r["org_id"], r["tbl_id"], r.get("tbl_nm") or r["tbl_id"], r.get("category", ""),
                            r.get("section", ""), r.get("path", ""), r.get("survey_type", ""), r.get("also_in", ""),
                            r.get("stat_id", ""), r.get("selected") == "True",
                            d / "meta" / f"{r['org_id']}_{r['tbl_id']}.json", raw))
    return out[:limit] if limit else out


# ── 원본 CSV 스캔 ───────────────────────────────────────────────
def _sig(t: TableSrc):
    from backend.rag.csv_index.source import _sig as csv_sig
    from backend.rag.ingestion.normalize import KIND_RULES_VERSION
    return f"{csv_sig(str(t.raw_path), str(t.meta_path) if t.meta_path.exists() else None)}|kind{KIND_RULES_VERSION}"


def _csv_index_scans():
    """기존 CSV 값 사전 tables.jsonl → {tbl_id: scan} (없으면 빈 dict)"""
    try:
        from backend.core.config import CSV_INDEX_DIR
    except Exception:  # noqa: BLE001
        return {}
    p = Path(CSV_INDEX_DIR) / "tables.jsonl"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["tbl_id"]] = r
    return out


def scan_all(tables: list[TableSrc], cache_dir: Path, workers=4, use_csv_index=True, log=print):
    """원본 CSV 가 있는 표만 스캔 → {tbl_id: scan}. scan 모양 = csv_index.scanner.scan_kosis_csv"""
    from backend.rag.csv_index.scanner import scan_kosis_csv
    from backend.rag.csv_index.source import TableRef
    cache_dir.mkdir(parents=True, exist_ok=True)
    idx = _csv_index_scans() if use_csv_index else {}
    res, todo, stat = {}, [], {"csv_index": 0, "cache": 0, "scan": 0, "no_raw": 0, "error": 0}
    for t in tables:
        if not t.raw_path.exists():
            stat["no_raw"] += 1
            continue
        sig = _sig(t)
        hit = idx.get(t.tbl_id)
        if hit and hit.get("sig") == sig:
            res[t.tbl_id] = hit
            stat["csv_index"] += 1
            continue
        cp = cache_dir / f"{t.key}.json"
        if cp.exists():
            c = json.loads(cp.read_text(encoding="utf-8"))
            if c.get("sig") == sig:
                res[t.tbl_id] = c
                stat["cache"] += 1
                continue
        todo.append((t, sig, cp))
    local = threading.local()
    errors = []

    def job(x):
        t, sig, cp = x
        if not hasattr(local, "con"):
            from backend.data_engine.duckdb_client import connect
            local.con = connect()
        ref = TableRef(tbl_id=t.tbl_id, tbl_nm=t.tbl_nm, org_id=t.org_id, category=t.raw_path.parent.name,
                       menu_path=t.path, raw_path=str(t.raw_path),
                       meta_path=str(t.meta_path) if t.meta_path.exists() else None, selected=t.selected)
        try:
            s = scan_kosis_csv(local.con, ref)
        except Exception as e:  # noqa: BLE001  (형식이 다른 CSV 는 메타만으로 카드 생성)
            errors.append({"tbl_id": t.tbl_id, "error": f"{e.__class__.__name__}: {str(e)[:150]}"})
            return None
        s.pop("_all_dim_values", None)
        s["sig"] = sig
        cp.write_text(json.dumps(s, ensure_ascii=False, default=str), encoding="utf-8")
        return s

    if todo:
        log(f"  원본 CSV 스캔 {len(todo)}개 (CSV 값 사전 재사용 {stat['csv_index']} · 캐시 {stat['cache']})")
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            for n, s in enumerate(ex.map(job, todo), 1):
                if s:
                    res[s["tbl_id"]] = s
                    stat["scan"] += 1
                if n % 100 == 0:
                    log(f"    {n}/{len(todo)}")
    stat["error"] = len(errors)
    return res, stat, errors


# ── 통계설명 ────────────────────────────────────────────────────
# statisticsExplData 출력변수 (KOSIS 개발가이드 '통계설명') → 카드에 쓰는 칸만
EXPL_FIELDS = {"writingPurps": "조사목적", "examinObjrange": "조사대상범위", "josaUnit": "조사단위",
               "josaItm": "조사항목", "mainTermExpl": "주요용어", "dataUserNote": "유의사항",
               "statsPeriod": "조사주기", "enumSampleMng": "전수표본"}


def survey_explanation(stat_id) -> dict:
    """kosis_fetch expl 결과 → {조사목적: …, 주요용어: …} (없으면 빈 dict)"""
    if not stat_id:
        return {}
    p = expl_dir() / f"{stat_id}.json"
    if not p.exists():
        return {}
    rows = json.loads(p.read_text(encoding="utf-8")).get("rows") or []
    out = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        for k, label in EXPL_FIELDS.items():
            v = " ".join(str(r.get(k) or "").split())
            if v and label not in out:
                out[label] = v[:400]
    return out
