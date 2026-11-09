"""[NEW v4] 검색 코퍼스 — 표 하나 = 문서 하나

  table_text  현재 검색이 쓰는 표 설명문 (backend/rag/ingestion/table_text.py → storage/indices/table_index)
              = baseline. 색인 만들 때 저장한 kiwi 토큰(tokens.json)도 그대로 씀
  csv_index   CSV 값 사전(backend/rag/csv_index)에서 만든 설명문: 실제 CSV 의 열 머리·분류 값·항목·단위·연도·주석
              scope: selected(catalog.csv 고른 표, 기본) | all(raw 폴더 전체)
  external    다른 팀 정제 데이터 등 외부 파일: jsonl({id 또는 tbl_id, text, …}) 또는 csv(id, text 열)

설명문 규칙(csv_index)은 table_text 와 같은 원칙: "무엇을 세었는가" 만 넣고 지역 코드 목록·연도 목록은 넣지 않음
(지역·시점은 View 를 자를 때 슬롯으로 처리)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from backend.rag.retrieval.interfaces import Doc

SMALL_DIM = 30          # 값이 이 수 이하인 분류는 값 이름까지 (table_text.SMALL_LEVEL 과 같음)
MAX_ITEMS = 30


def _mtime_sig(*paths) -> str:
    parts = [f"{p}:{p.stat().st_mtime_ns}:{p.stat().st_size}" for p in map(Path, paths) if p.exists()]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


class TableTextCorpus:
    """현재 표 설명문 색인 (baseline)"""
    name = "table_text"

    def __init__(self, index_dir=None):
        from backend.rag.ingestion.table_text import INDEX
        self.dir = Path(index_dir or INDEX)
        self._docs, self._sig = None, None

    def _files(self):
        return [self.dir / n for n in ("ids.json", "texts.jsonl", "tokens.json")]

    def signature(self):
        return f"table_text:{_mtime_sig(*self._files())}"

    def docs(self):
        sig = self.signature()
        if self._docs is None or self._sig != sig:
            self._sig = sig
            if not (self.dir / "tokens.json").exists():
                raise FileNotFoundError(f"표 색인이 없습니다: {self.dir}  →  POST /api/v1/ingest/table-index/build "
                                        f"또는 python -m backend.rag.ingestion.table_text")
            from backend.rag.ingestion.meta_profile import load_meta_profiles
            ids = json.loads((self.dir / "ids.json").read_text(encoding="utf-8"))
            texts = {r["tbl_id"]: r["text"] for r in
                     map(json.loads, (self.dir / "texts.jsonl").read_text(encoding="utf-8").splitlines())}
            prof = {p["tbl_id"]: p for p in load_meta_profiles()}
            self._docs = [Doc(i, texts[i], {"tbl_nm": (prof.get(i) or {}).get("tbl_nm", ""),
                                            "survey_nm": (prof.get(i) or {}).get("survey_nm", "")}) for i in ids]
        return self._docs

    def cached_tokens(self, tokenizer_id):
        """색인 때 저장한 토큰 (같은 토크나이저일 때만) — baseline 이 table_search 와 똑같은 BM25 를 갖게"""
        if tokenizer_id == "kiwi:table" and (self.dir / "tokens.json").exists():
            return json.loads((self.dir / "tokens.json").read_text(encoding="utf-8"))
        return None


def csv_table_text(t: dict) -> str:
    """CSV 값 사전의 표 하나 → 설명문"""
    from backend.rag.ingestion.table_text import is_region_list, is_sido
    dims = []
    for d in t.get("dims") or []:
        names = [v["name"] for v in d.get("values") or []]
        if d.get("kind") == "regions" or is_region_list(names):
            geo = sorted({v.get("geo") for v in d.get("values") or [] if v.get("geo") and v.get("geo") != "전국"})
            dims.append(f"{d['obj_nm']}({'·'.join(geo) or '지역'})")
        elif d.get("n_values", len(names)) <= SMALL_DIM:
            dims.append(f"{d['obj_nm']}({', '.join(names[:15])})")
        else:
            dims.append(f"{d['obj_nm']}({d.get('n_values')}개: {', '.join(names[:8])} …)")
    items = [i["name"] for i in t.get("items") or []]
    if is_region_list(items):
        items = [n for n in items if not is_sido(n) and n != "전국"] + ["지역(시도)"]
    units = sorted({i.get("unit") for i in t.get("items") or [] if i.get("unit")})
    ys = t.get("years") or []
    notes = [f["text"] for f in t.get("footnotes") or [] if f.get("type") in ("통계표", "항목") and f.get("text")]
    parts = [f"{t.get('survey_nm') or ''} | {t.get('tbl_nm') or ''}",
             "분류: " + " / ".join(dims) if dims else "",
             "항목: " + ", ".join(items[:MAX_ITEMS]) + (f" 외 {len(items) - MAX_ITEMS}개" if len(items) > MAX_ITEMS else "")
             if items else "",
             "단위: " + ", ".join(units) if units else "",
             f"기간: {ys[0]}~{ys[-1]}" if ys else "",
             "경로: " + (t.get("menu_path") or ""),
             "주석: " + " / ".join(n[:80] for n in notes[:2]) if notes else ""]
    return "\n".join(x for x in parts if x)[:1500]


class CsvIndexCorpus:
    """CSV 값 사전 설명문 (실제 CSV 값 기준, raw 만 있는 표도 scope=all 이면 포함)"""
    name = "csv_index"

    def __init__(self, scope="selected", index_dir=None, footnotes=True):
        self.scope, self.index_dir, self.footnotes = scope, index_dir, footnotes
        self._docs, self._sig = None, None

    def _idx(self):
        from backend.rag.csv_index import load_index
        return load_index(self.index_dir)

    def signature(self):
        idx = self._idx()
        return f"csv_index:{self.scope}:{int(self.footnotes)}:{_mtime_sig(idx.dir / 'tables.jsonl')}"

    def docs(self):
        sig = self.signature()
        if self._docs is None or self._sig != sig:
            self._sig = sig
            idx = self._idx()
            out = []
            for tid in idx.table_ids(self.scope):
                t = idx.table(tid)
                t2 = t if self.footnotes else {**t, "footnotes": []}
                out.append(Doc(tid, csv_table_text(t2), {"tbl_nm": t.get("tbl_nm", ""), "survey_nm": t.get("survey_nm", ""),
                                                          "selected": bool(t.get("selected"))}))
            self._docs = out
        return self._docs


class ExternalCorpus:
    """외부 파일 코퍼스: jsonl 한 줄 {id|tbl_id, text, tbl_nm?, survey_nm?, …} 또는 csv (id|tbl_id, text 열)"""
    name = "external"

    def __init__(self, path, id_field=None, text_field="text"):
        self.path, self.id_field, self.text_field = Path(path), id_field, text_field
        self._docs, self._sig = None, None

    def signature(self):
        return f"external:{_mtime_sig(self.path)}:{self.path.name}"

    def docs(self):
        sig = self.signature()
        if self._docs is None or self._sig != sig:
            self._sig = sig
            if not self.path.exists():
                raise FileNotFoundError(f"외부 코퍼스 파일 없음: {self.path}")
            if self.path.suffix.lower() == ".csv":
                rows = pd.read_csv(self.path, dtype=str, encoding="utf-8-sig").fillna("").to_dict("records")
            elif self.path.suffix.lower() == ".parquet":
                rows = pd.read_parquet(self.path).fillna("").to_dict("records")
            else:
                rows = [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()]
            key = self.id_field or ("tbl_id" if rows and "tbl_id" in rows[0] else "id")
            self._docs = [Doc(str(r[key]), str(r[self.text_field]),
                              {k: v for k, v in r.items() if k not in (key, self.text_field)}) for r in rows]
        return self._docs
