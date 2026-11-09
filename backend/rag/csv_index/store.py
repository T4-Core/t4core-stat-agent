"""
[NEW v4] CSV 값 사전 만들기·저장·조회

산출물 (CSV_INDEX_DIR = storage/csv_index/)
  tables.jsonl     표마다 TableScan (열·분류(종류·값)·항목·단위·기간·연도·주석·selected) + sig(원본 크기·수정시각)
  values.parquet   역색인 (값 하나 = 행 하나): norm · name · kind · slot · tbl_id · obj_nm · code · std · n · selected
                   kind = dim(분류 값) / item(항목) / obj(열 머리=분류 이름) / table(표 이름)
                   slot = 지역 / 성별 / 연령 / 국적 / 분류 / 항목 / 열 / 표
  summary.json     만든 시각 · 소스 · 표 수 · 값 수 · 슬롯별 값 수

  build_index(source=None, scope="all", workers=4, force=False, limit=None)   # 원본이 바뀐 표만 다시 스캔
  idx = load_index()                                                            # 메모리 캐시 (파일이 바뀌면 다시 읽음)
  idx.find("출생아 수")            → 정확·변형 일치 [{name, slot, tbl_id, …}]
  idx.contains("인구", slots=…)    → 포함 일치 (인구 ⊂ 총인구수)
  idx.values("지역", tbl_ids=…)    → 그 표들의 지역 값 (표 수 순)
  idx.years(tbl_ids) · idx.table(tbl_id) · idx.tables_of(rows)
"""
import json
import re
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd

VALUE_COLS = ["norm", "name", "kind", "slot", "tbl_id", "obj_nm", "code", "std", "n", "selected"]
_PUNCT = re.compile(r"[\s·ㆍ,\.\-_/'\"“”‘’]+")
_PAREN = re.compile(r"\([^)]*\)|\[[^\]]*\]|（[^）]*）")


def norm(s):
    """비교용 정규화: NFKC · 소문자 · 공백·구두점 제거 ('출생아 수' = '출생아수')"""
    return _PUNCT.sub("", unicodedata.normalize("NFKC", str(s or "")).lower())


def variants(name):
    """이름 하나 → 같은 값으로 볼 표기 변형 (괄호 단위 빼기 · 끝 '수' 붙이기/빼기 · 끝 '별' 빼기)
    '출생아수(명)' → {출생아수, 출생아} / '인구' → {인구, 인구수} / '행정구역(시도)별' → {행정구역시도별, 행정구역, 행정구역별}"""
    base = norm(name)
    out = {base}
    np_ = norm(_PAREN.sub("", str(name or "")))
    if np_:
        out.add(np_)
    for v in list(out):
        if v.endswith("별") and len(v) > 2:
            out.add(v[:-1])
        if v.endswith("수") and len(v) > 2:
            out.add(v[:-1])
        elif len(v) >= 2 and not v.endswith(("율", "률", "비", "비율", "수")):
            out.add(v + "수")
    return {v for v in out if v}


def postings_of(scan):
    """TableScan → 역색인 행 목록"""
    t, sel = scan["tbl_id"], bool(scan.get("selected"))
    rows = [{"norm": norm(scan["tbl_nm"]), "name": scan["tbl_nm"], "kind": "table", "slot": "표", "tbl_id": t,
             "obj_nm": "", "code": "", "std": "", "n": scan["n_rows"], "selected": sel}]
    for d in scan.get("_all_dim_values") or scan["dims"]:
        rows.append({"norm": norm(d["obj_nm"]), "name": d["obj_nm"], "kind": "obj", "slot": "열", "tbl_id": t,
                     "obj_nm": d["obj_nm"], "code": f"C{d['level']}", "std": d["kind"], "n": d["n_values"], "selected": sel})
        for v in d["values"]:
            std = v.get("std") or (f"{v.get('age_from')}-{v.get('age_to') if v.get('age_to') is not None else ''}"
                                   if d["kind"] == "ages" and v.get("age_from") is not None else "")
            rows.append({"norm": norm(v["name"]), "name": v["name"], "kind": "dim", "slot": d["slot"], "tbl_id": t,
                         "obj_nm": d["obj_nm"], "code": v["code"], "std": std or "", "n": v["n_value"], "selected": sel})
    for i in scan["items"]:
        rows.append({"norm": norm(i["name"]), "name": i["name"], "kind": "item", "slot": "항목", "tbl_id": t,
                     "obj_nm": "항목", "code": i["itm_id"], "std": i["unit"], "n": i["n_value"], "selected": sel})
    return rows


# ── 만들기 ───────────────────────────────────────────────────────
def index_dir():
    from backend.core.config import CSV_INDEX_DIR
    return Path(CSV_INDEX_DIR)


def _read_jsonl(p):
    p = Path(p)
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def build_index(source=None, scope="all", workers=4, force=False, limit=None, log=print, out_dir=None):
    """원본 CSV 를 스캔해 값 사전을 만듦. 원본(크기·수정시각)이 같은 표는 이전 스캔을 그대로 씀.
    scope=all 로 만들어 두고, 조회 때 settings.csv_scope 로 selected 만 쓸지 정함 (기본)"""
    from backend.data_engine.duckdb_client import connect
    from backend.rag.csv_index.source import get_source
    source = source or get_source()
    d = Path(out_dir or index_dir())
    d.mkdir(parents=True, exist_ok=True)
    refs = source.list_tables(scope)
    if limit:
        refs = refs[:limit]
    old = {r["tbl_id"]: r for r in _read_jsonl(d / "tables.jsonl")}
    sigs = {r.tbl_id: source.signature(r) for r in refs}
    todo = [r for r in refs if force or old.get(r.tbl_id, {}).get("sig") != sigs[r.tbl_id]
            or old[r.tbl_id].get("selected") != r.selected]
    log(f"[csv_index] 표 {len(refs)}개 · 새로 스캔 {len(todo)}개 · 이전 스캔 재사용 {len(refs) - len(todo)}개 → {d}")
    t0, errors, local = time.time(), [], threading.local()

    def job(ref):
        if not hasattr(local, "con"):
            local.con = connect()
        try:
            s = source.scan(ref, local.con)
            s["sig"] = sigs[ref.tbl_id]
            s["source"] = source.name
            return s
        except Exception as e:  # noqa: BLE001  (형식이 다른 CSV 는 건너뛰고 기록)
            errors.append({"tbl_id": ref.tbl_id, "raw_path": ref.raw_path, "error": f"{e.__class__.__name__}: {str(e)[:200]}"})
            return None
    scans = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for n, s in enumerate(ex.map(job, todo), 1):
            if s:
                scans[s["tbl_id"]] = s
            if n % 100 == 0 or n == len(todo):
                log(f"  스캔 {n}/{len(todo)} ({time.time() - t0:.0f}s)")
    keep = {r.tbl_id for r in refs}
    all_scans = {t: s for t, s in old.items() if t in keep and t not in scans}
    all_scans.update(scans)
    # 역색인: 새로 스캔한 표는 전체 값, 재사용 표는 이전 values.parquet 에서
    prev = pd.read_parquet(d / "values.parquet") if (d / "values.parquet").exists() else pd.DataFrame(columns=VALUE_COLS)
    reuse = prev[prev["tbl_id"].isin(set(all_scans) - set(scans))] if len(prev) else prev
    new_rows = [p for s in scans.values() for p in postings_of(s)]
    vals = pd.concat([reuse, pd.DataFrame(new_rows, columns=VALUE_COLS)], ignore_index=True)
    sel = {t: bool(s.get("selected")) for t, s in all_scans.items()}
    vals["selected"] = vals["tbl_id"].map(sel).fillna(False).astype(bool)
    vals["n"] = pd.to_numeric(vals["n"], errors="coerce").fillna(0).astype(int)
    vals.to_parquet(d / "values.parquet", index=False)
    with (d / "tables.jsonl").open("w", encoding="utf-8") as f:
        for s in all_scans.values():
            s = {k: v for k, v in s.items() if k != "_all_dim_values"}
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    summary = {"built": datetime.now().isoformat(timespec="seconds"), "source": source.name, "dir": str(d),
               "n_tables": len(all_scans), "n_selected": sum(sel.values()), "n_values": int(len(vals)),
               "by_slot": {k: int(v) for k, v in vals["slot"].value_counts().items()},
               "n_scanned": len(scans), "errors": errors[:50], "n_errors": len(errors)}
    (d / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    _CACHE.clear()
    log(f"[csv_index] 완료: 표 {summary['n_tables']}개 · 값 {summary['n_values']}개 · 오류 {len(errors)}개")
    return summary


# ── 조회 ─────────────────────────────────────────────────────────
_CACHE, _LOCK = {}, threading.Lock()


class CsvIndex:
    def __init__(self, d):
        d = Path(d)
        if not (d / "values.parquet").exists():
            raise FileNotFoundError(f"CSV 값 사전 없음: {d}  →  POST /api/v1/csv-index/build  또는  "
                                    f"python -m backend.rag.csv_index build")
        self.dir = d
        self.tables = {r["tbl_id"]: r for r in _read_jsonl(d / "tables.jsonl")}
        self.v = pd.read_parquet(d / "values.parquet")
        self.summary = json.loads((d / "summary.json").read_text(encoding="utf-8")) if (d / "summary.json").exists() else {}
        self._exact = defaultdict(list)          # norm → 행 번호
        self._variant = defaultdict(list)        # 변형 norm → 행 번호 (항목·분류·열 이름만)
        for i, (nm, name, kind) in enumerate(zip(self.v["norm"], self.v["name"], self.v["kind"])):
            self._exact[nm].append(i)
            if kind in ("item", "dim", "obj"):
                for x in variants(name) - {nm}:
                    self._variant[x].append(i)

    # 행 번호 → dict, scope 거르기
    def _rows(self, ids, slots=None, scope="selected", tbl_ids=None):
        if not ids:
            return []
        sub = self.v.iloc[sorted(set(ids))]
        if scope == "selected":
            sub = sub[sub["selected"]]
        if slots:
            sub = sub[sub["slot"].isin(list(slots))]
        if tbl_ids is not None:
            sub = sub[sub["tbl_id"].isin(set(tbl_ids))]
        return sub.to_dict("records")

    def find(self, text, slots=None, scope="selected", variant=True):
        """정확 일치 (+ 표기 변형) → [{…, match: exact|variant}]"""
        k = norm(text)
        out = [{**r, "match": "exact"} for r in self._rows(self._exact.get(k, []), slots, scope)]
        if variant:
            vids = set(self._variant.get(k, []))
            for x in variants(text) - {k}:
                vids |= set(self._exact.get(x, [])) | set(self._variant.get(x, []))
            seen = {(r["tbl_id"], r["kind"], r["code"]) for r in out}
            out += [{**r, "match": "variant"} for r in self._rows(list(vids), slots, scope)
                    if (r["tbl_id"], r["kind"], r["code"]) not in seen]
        return out

    def contains(self, text, slots=None, scope="selected", min_len=2, limit=2000):
        """포함 일치: 질의어가 값 안에 있음(인구 ⊂ 총인구수) 또는 값이 질의어 안에 있음(출생아 ⊂ 출생아수추이)"""
        k = norm(text)
        if len(k) < min_len:
            return []
        hit = self.v["norm"].str.contains(re.escape(k), regex=True) | self.v["norm"].map(
            lambda x: len(x) >= min_len and x in k)
        sub = self.v[hit]
        if scope == "selected":
            sub = sub[sub["selected"]]
        if slots:
            sub = sub[sub["slot"].isin(list(slots))]
        return [{**r, "match": "contains"} for r in sub.head(limit).to_dict("records")]

    def scan_text(self, text, slots=None, scope="selected", min_len=2, max_len=24):
        """자유 문장 속에서 사전에 있는 표현 찾기 (긴 것 먼저, 겹치지 않게) → [(표현, 행 목록)]"""
        t = norm(text)
        out, i = [], 0
        while i < len(t):
            for L in range(min(max_len, len(t) - i), min_len - 1, -1):
                key = t[i:i + L]
                ids = self._exact.get(key, []) + self._variant.get(key, [])
                rows = self._rows(ids, slots, scope) if ids else []
                if rows:
                    out.append((key, rows))
                    i += L
                    break
            else:
                i += 1
        return out

    def values(self, slot, tbl_ids=None, scope="selected", limit=None):
        """슬롯 값 목록 (표 수 순) → [{value, n_tables, example_tables}]. 지역은 표준명, 연령은 범위로 묶음"""
        sub = self.v[self.v["slot"] == slot]
        if slot not in ("항목", "열", "표"):
            sub = sub[sub["kind"] == "dim"]
        if scope == "selected":
            sub = sub[sub["selected"]]
        if tbl_ids is not None:
            sub = sub[sub["tbl_id"].isin(set(tbl_ids))]
        key = sub["std"].where(sub["std"].astype(bool), sub["name"]) if slot in ("지역", "연령") else sub["name"]
        g = sub.assign(_k=key).groupby("_k")["tbl_id"].agg(lambda s: sorted(set(s)))
        out = [{"value": k, "n_tables": len(v), "example_tables": v[:3]} for k, v in g.items() if k]
        out.sort(key=lambda x: (-x["n_tables"], x["value"]))
        return out[:limit] if limit else out

    def table(self, tbl_id):
        return self.tables.get(tbl_id)

    def years(self, tbl_ids=None, scope="selected"):
        c = Counter()
        for t, s in self.tables.items():
            if (tbl_ids is None or t in tbl_ids) and (scope != "selected" or s.get("selected")):
                c.update(s.get("years") or [])
        return c

    def table_ids(self, scope="selected"):
        return [t for t, s in self.tables.items() if scope != "selected" or s.get("selected")]


def load_index(d=None) -> CsvIndex:
    d = Path(d or index_dir())
    key = str(d)
    f = d / "values.parquet"
    mtime = f.stat().st_mtime if f.exists() else None
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
        idx = CsvIndex(d)
        _CACHE[key] = (mtime, idx)
        return idx
