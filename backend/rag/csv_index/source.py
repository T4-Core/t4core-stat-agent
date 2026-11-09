"""
[NEW v4] 데이터 소스 인터페이스 — CSV 값 사전이 '어디서 표를 읽는가'를 갈아끼울 수 있게

  DataSource (Protocol)
    list_tables(scope)  → [TableRef]       scope = "selected" (catalog.csv selected) | "all" (raw 폴더 전체)
    signature(ref)      → str              바뀌었는지 판단 (캐시 키)
    scan(ref, con)      → dict TableScan   표 하나의 구조 (scanner.scan_kosis_csv 와 같은 모양)

  구현
    KosisRawCsvSource   지금 쓰는 수집 결과 (storage/kosis_data: catalog.csv · meta/*.json · raw/<조사>/<기관>_<표>.csv)
                        기존 코드와 같은 방식: 표 목록은 catalog.csv(normalize.load_targets 와 같은 규칙), 원본 위치는 normalize.raw_path
    (예정) 정제 데이터 소스  타 파트의 정제 데이터가 나오면 같은 3개 메서드만 구현해 get_source("이름") 으로 교체
"""
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd


@dataclass
class TableRef:
    tbl_id: str
    tbl_nm: str
    org_id: str
    category: str                  # 조사 폴더 이름
    menu_path: str                 # catalog.csv path (KOSIS 메뉴 경로)
    raw_path: str
    meta_path: str | None
    selected: bool

    def as_dict(self):
        return asdict(self)


class DataSource(Protocol):
    name: str

    def list_tables(self, scope: str = "selected") -> list[TableRef]: ...

    def signature(self, ref: TableRef) -> str: ...

    def scan(self, ref: TableRef, con) -> dict: ...


def _sig(*paths):
    out = []
    for p in paths:
        p = Path(p) if p else None
        out.append(f"{p.stat().st_size}:{int(p.stat().st_mtime)}" if p and p.exists() else "-")
    return ";".join(out)


class KosisRawCsvSource:
    """storage/kosis_data 의 원본 CSV (+ 메타 JSON 은 주석·조사명만)"""
    name = "kosis_raw_csv"

    def __init__(self, data_dir=None):
        from backend.core.config import KOSIS_DATA_DIR
        self.data_dir = Path(data_dir or KOSIS_DATA_DIR)

    def _catalog(self):
        f = self.data_dir / "catalog.csv"
        return pd.read_csv(f, dtype=str).fillna("") if f.exists() else pd.DataFrame(
            columns=["category", "path", "org_id", "tbl_id", "tbl_nm", "selected"])

    def list_tables(self, scope="selected"):
        from backend.core.utils import safe
        cat = self._catalog()
        raw_dir = self.data_dir / "raw"
        refs, seen = [], set()

        def ref_of(r, raw, selected):
            meta = self.data_dir / "meta" / f"{r['org_id']}_{r['tbl_id']}.json"
            return TableRef(tbl_id=r["tbl_id"], tbl_nm=r.get("tbl_nm") or r["tbl_id"], org_id=r["org_id"],
                            category=raw.parent.name, menu_path=r.get("path") or "", raw_path=str(raw),
                            meta_path=str(meta) if meta.exists() else None, selected=selected)
        # 1) catalog.csv (selected 먼저) — 원본이 실제로 있는 행만
        for sel in (True, False):
            rows = cat[(cat["selected"] == "True") == sel] if "selected" in cat else cat.iloc[0:0]
            for r in rows.to_dict("records"):
                if r["tbl_id"] in seen:
                    continue
                raw = raw_dir / safe(r["category"]) / f"{r['org_id']}_{r['tbl_id']}.csv"
                if raw.exists():
                    refs.append(ref_of(r, raw, sel))
                    seen.add(r["tbl_id"])
        # 2) catalog.csv 에 없는 raw 파일 (scope=all 일 때만 쓰이지만 목록에는 둠)
        if raw_dir.exists():
            for raw in sorted(raw_dir.glob("*/*.csv")):
                org, _, tbl = raw.stem.partition("_")
                if tbl and tbl not in seen:
                    head = pd.read_csv(raw, dtype=str, nrows=1, encoding="utf-8-sig")
                    nm = head["TBL_NM"].iloc[0] if "TBL_NM" in head and len(head) else tbl
                    refs.append(ref_of({"tbl_id": tbl, "tbl_nm": nm, "org_id": org, "path": ""}, raw, False))
                    seen.add(tbl)
        return [r for r in refs if scope == "all" or r.selected]

    def signature(self, ref):
        return _sig(ref.raw_path, ref.meta_path)

    def scan(self, ref, con):
        from backend.rag.csv_index.scanner import scan_kosis_csv
        return scan_kosis_csv(con, ref)


SOURCES = {"kosis_raw_csv": KosisRawCsvSource}


def get_source(name="kosis_raw_csv", **kw) -> DataSource:
    if name not in SOURCES:
        raise ValueError(f"모르는 데이터 소스: {name} (가능: {list(SOURCES)})")
    return SOURCES[name](**kw)
