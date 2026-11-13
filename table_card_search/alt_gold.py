"""
정답 판정 — 골든셋의 정답 사실(값)을 다른 표에서도 그대로 얻을 수 있으면 그 표도 정답(대체 정답)으로 인정

  왜: 골든셋 정답은 '생성에 쓴 표 하나' 뿐이라, 같은 값을 가진 다른 표를 찾아도 오답으로 셈 (144문항 비교에서 확인)
  기준: 이름·설명이 비슷한 것이 아니라 '값' — 같은 시점·지역·항목(·조건)의 칸 값이 정답 값과 같아야 함
        (주민등록인구 vs 인구총조사 인구처럼 이름은 비슷해도 정의가 다른 표는 값이 달라 걸러짐)

  1) 후보 표 (CSV 값 사전, 원본은 안 읽음): 정답 사실마다
       같은 시점이 있음 ∩ 같은 항목 이름(분류 값으로 들어간 경우 포함) ∩ 같은 지역(총계면 생략) ∩ 총계가 아닌 다른 조건 값
     근거 그룹의 사실들을 모두 만족하는 표만, 정답 표는 뺌
  2) 값 확인 (후보 표의 원본 CSV 만 DuckDB 로): 같은 좌표 행의 값 × 단위 환산 = 정답 값
       exact   : 허용 오차 안에서 같음 (정답의 표시 자릿수 기준 ±0.5, 단위 환산 포함: 천명 ↔ 명)
       rounded : 후보 표가 더 큰 단위로 반올림한 값 (예: 1,450천명 ↔ 1,449,896명) — 보고서에 따로 셈
     남은 분류가 총계가 아닌 행이 여러 개면(어느 행인지 정할 수 없음) 인정하지 않음
  3) 근거 그룹마다: 그 그룹의 사실(최대 max_facts 개 확인)을 모두 맞춘 표 = 그 그룹의 대체 정답

출력  alt_positives.jsonl (정답 데이터셋 옆, 레코드마다 한 줄 · 이어서 실행 가능)
        {dataset_id, gold_tables, status, groups: {R1: {n_facts, checked, alternatives: [{tbl_id, tbl_nm, match, checked}]}}}
      → python -m table_card_search.compare --golden … --alt <이 파일>  (엄격 / 완화 지표를 나란히)

실행 (저장소 루트, CSV 값 사전이 있어야 함: python -m backend.rag.csv_index build)
  python -m table_card_search.alt_gold --golden synthetic_gold_pipeline/outputs/datasets/synthetic_gold_dataset.jsonl
  python -m table_card_search.alt_gold --golden … --limit 10 --max-candidates 20      # 먼저 작게
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

TOTALS = {"계", "합계", "총계", "전체", "소계", "총", "전국", "계(전체)", "전체(계)", "합", "총수"}
REGION_OBJ = re.compile(r"행정구역|시도|시군구|지역|읍면동")


def _tid(x):
    m = re.match(r"^\d{2,4}_(.+)$", str(x))
    return m.group(1) if m else str(x)


def _dec(x):
    try:
        return Decimal(str(x).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _sample(xs, n):
    """앞·뒤·고르게 n개 (재현 가능)"""
    if len(xs) <= n:
        return list(xs)
    step = (len(xs) - 1) / (n - 1)
    return [xs[round(i * step)] for i in range(n)]


class Judge:
    def __init__(self, idx, max_candidates=40, max_facts=8, log=print):
        from backend.rag.csv_index.store import norm, variants
        from backend.rag.ingestion.normalize import std_geo_name
        self.idx, self.norm, self.variants, self.geo = idx, norm, variants, std_geo_name
        self.max_candidates, self.max_facts, self.log = max_candidates, max_facts, log
        self.region_tables = defaultdict(set)              # norm(지역 이름·표준명) → 표
        self.dim_tables = defaultdict(set)                 # norm(분류 값·항목 이름) → 표
        v = idx.v
        for name, std, slot, kind, t in zip(v["name"], v["std"], v["slot"], v["kind"], v["tbl_id"]):
            if kind not in ("dim", "item"):
                continue
            if slot == "지역":
                for k in {norm(name), norm(std or ""), norm(std_geo_name(name) or "")} - {""}:
                    self.region_tables[k].add(t)
            for k in {norm(name)} | (variants(name) if kind in ("item", "dim") else set()):
                if k:
                    self.dim_tables[k].add(t)
        self._con = None
        self._rows_cache = {}

    # ── 정답 사실 → 조건 ──
    def _fact_spec(self, f):
        c = f.get("coordinate") or {}
        gold_t = self.idx.table(_tid(f.get("parent_table_id") or c.get("TBL_ID") or ""))
        region_objs = {d["obj_nm"] for d in (gold_t or {}).get("dims") or [] if d.get("kind") == "regions"}
        region, labels = None, []
        for obj, lab in (f.get("coordinate_labels") or {}).items():
            if obj in region_objs or (not region_objs and REGION_OBJ.search(obj)):
                region = lab
            elif re.sub(r"\s+", "", str(lab)) not in TOTALS:
                labels.append(lab)
        item = c.get("ITM_NM") or f.get("item_name") or ""
        return {"prd_de": str(c.get("PRD_DE") or ""), "item": item, "region": region, "labels": labels,
                "value": _dec(c.get("normalized_value") if c.get("normalized_value") is not None else (f.get("value") or {}).get("raw")),
                "unit": c.get("normalized_unit") or f.get("unit") or c.get("UNIT_NM") or "",
                "digits": int((f.get("value") or {}).get("display_digits") or 0)}

    def _keys(self, text):
        return {self.norm(text)} | self.variants(text)

    def _tables_with(self, text):
        out = set()
        for k in self._keys(text):
            out |= self.dim_tables.get(k, set())
        return out

    def candidates(self, specs, exclude):
        cand = None
        for s in specs:
            ts = {t for t, r in self.idx.tables.items()
                  if any(s["prd_de"] in (ps or []) for ps in (r.get("periods") or {}).values())}
            ts &= self._tables_with(s["item"]) if s["item"] else ts
            if s["region"] and re.sub(r"\s+", "", s["region"]) not in TOTALS:
                ks = {self.norm(s["region"]), self.norm(self.geo(s["region"]) or "")} - {""}
                ts &= set().union(*[self.region_tables.get(k, set()) for k in ks])
            for lab in s["labels"]:
                ts &= self._tables_with(lab)
            cand = ts if cand is None else cand & ts
            if not cand:
                return []
        return sorted((cand or set()) - set(exclude))[: self.max_candidates]

    # ── 원본 값 확인 ──
    def _rows(self, tbl_id, periods):
        key = (tbl_id, tuple(sorted(periods)))
        if key in self._rows_cache:
            return self._rows_cache[key]
        import duckdb
        from backend.core.utils import sql_str
        t = self.idx.table(tbl_id) or {}
        path = t.get("raw_path")
        rows = []
        if path and Path(path).exists():
            self._con = self._con or duckdb.connect()
            cols = [c for c in t.get("columns") or [] if re.fullmatch(r"C\d_NM|ITM_NM|UNIT_NM|PRD_SE|PRD_DE|DT", c)]
            src = f"read_csv({sql_str(Path(path).as_posix())}, all_varchar=true, header=true)"
            plist = ", ".join(sql_str(p) for p in periods)
            try:
                res = self._con.execute(f"SELECT {', '.join(cols)} FROM {src} WHERE PRD_DE IN ({plist})")
                names = [d[0] for d in res.description]
                rows = [dict(zip(names, r)) for r in res.fetchall()]
            except Exception as e:  # noqa: BLE001
                self.log(f"    ! {tbl_id} 읽기 실패: {e.__class__.__name__}: {str(e)[:120]}")
        if len(self._rows_cache) > 64:
            self._rows_cache.clear()
        self._rows_cache[key] = rows
        return rows

    def _region_cols(self, tbl_id):
        t = self.idx.table(tbl_id) or {}
        return [f"C{d['level']}_NM" for d in t.get("dims") or [] if d.get("kind") == "regions"]

    def _value_match(self, row, s):
        from synthetic_gold_pipeline.tools.units import UnitIncompatible, conversion_factor, unit_info
        c, g = _dec(row.get("DT")), s["value"]
        if c is None or g is None:
            return None
        cu = row.get("UNIT_NM") or s["unit"]
        try:
            f = Decimal(1) if unit_info(cu).canonical == unit_info(s["unit"]).canonical else conversion_factor(cu, s["unit"])
        except UnitIncompatible:
            return None
        tol = Decimal("0.5") * (Decimal(10) ** -s["digits"]) + abs(g) * Decimal("1e-9")
        if abs(c * f - g) <= tol:
            return "exact"
        if f > 1 and abs(c - g / f) <= Decimal("0.5"):
            return "rounded"
        return None

    def fact_in_table(self, tbl_id, s):
        rows = [r for r in self._rows(tbl_id, [s["prd_de"]]) if str(r.get("PRD_DE")) == s["prd_de"]]
        if not rows:
            return None
        dim_cols = [k for k in rows[0] if re.fullmatch(r"C\d_NM", k)]
        reg_cols = self._region_cols(tbl_id)
        item_keys = self._keys(s["item"]) if s["item"] else set()
        want_region = s["region"] and re.sub(r"\s+", "", s["region"]) not in TOTALS
        rkeys = {self.norm(s["region"] or ""), self.norm(self.geo(s["region"] or "") or "")} - {""}
        best = []
        for r in rows:
            used = set()
            if item_keys:
                if self.norm(r.get("ITM_NM") or "") in item_keys:
                    used.add("ITM_NM")
                else:
                    hit = next((k for k in dim_cols if self.norm(r.get(k) or "") in item_keys), None)
                    if not hit:
                        continue
                    used.add(hit)
            if want_region:
                hit = next((k for k in (reg_cols or dim_cols) if k not in used and (
                    self.norm(r.get(k) or "") in rkeys or self.norm(self.geo(r.get(k) or "") or "") in rkeys)), None)
                if not hit:
                    continue
                used.add(hit)
            elif reg_cols and not all(re.sub(r"\s+", "", str(r.get(k) or "")) in TOTALS for k in reg_cols):
                continue                                       # 정답이 총계(전국)면 후보도 총계 행
            ok = True
            for lab in s["labels"]:
                lk = self._keys(lab)
                hit = next((k for k in dim_cols + ["ITM_NM"] if k not in used and self.norm(r.get(k) or "") in lk), None)
                if not hit:
                    ok = False
                    break
                used.add(hit)
            if not ok:
                continue
            extra = sum(1 for k in dim_cols if k not in used and re.sub(r"\s+", "", str(r.get(k) or "")) not in TOTALS)
            best.append((extra, r))
        if not best:
            return None
        low = min(e for e, _ in best)
        top = [r for e, r in best if e == low]
        if low > 0 and len(top) > 1:
            return None                                        # 남은 분류가 총계가 아닌 행이 여러 개 → 어느 행인지 모름
        for r in top:
            m = self._value_match(r, s)
            if m:
                return m
        return None

    # ── 레코드 하나 ──
    def judge(self, rec):
        re_ = rec.get("retrieval_eval") or {}
        gold = sorted({_tid(t) for t in re_.get("golden_table_ids") or []}
                      | {_tid(t) for g in (re_.get("required_evidence_groups") or {}).values()
                         for t in g.get("acceptable_table_ids") or []})
        facts = {f["fact_id"]: f for f in (rec.get("generation_eval") or {}).get("intermediate_facts") or []}
        out = {"dataset_id": rec.get("dataset_id"), "gold_tables": gold, "groups": {}, "status": "ok"}
        if rec.get("answerability_type") != "ANSWERABLE" or not facts:
            out["status"] = "skipped"
            return out
        groups = {g: v.get("required_fact_ids") or [] for g, v in (re_.get("required_evidence_groups") or {}).items()}
        groups = {g: ids for g, ids in groups.items() if ids} or {"ALL": list(facts)}
        for g, ids in groups.items():
            specs = [self._fact_spec(facts[i]) for i in _sample([i for i in ids if i in facts], self.max_facts)]
            specs = [s for s in specs if s["prd_de"] and s["value"] is not None]
            alts = []
            if specs:
                for t in self.candidates(specs, gold):
                    ms = [self.fact_in_table(t, s) for s in specs]
                    if all(ms):
                        alts.append({"tbl_id": t, "tbl_nm": (self.idx.table(t) or {}).get("tbl_nm", ""),
                                     "match": "rounded" if "rounded" in ms else "exact", "checked": len(ms)})
            out["groups"][g] = {"n_facts": len(ids), "checked": len(specs), "alternatives": alts}
        return out


def load_alt(path, include_rounded=True):
    """alt_positives.jsonl → {dataset_id: {group: [tbl_id, …]}} (compare.py 가 씀)"""
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        out[r["dataset_id"]] = {g: [a["tbl_id"] for a in v.get("alternatives") or []
                                    if include_rounded or a.get("match") == "exact"]
                                for g, v in (r.get("groups") or {}).items()}
    return out


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m table_card_search.alt_gold")
    ap.add_argument("--golden", required=True, help="synthetic_gold_dataset.jsonl")
    ap.add_argument("--csv-index", default=None, help="CSV 값 사전 폴더 (기본 storage/csv_index)")
    ap.add_argument("--out", default=None, help="기본: 골든셋 옆 alt_positives.jsonl")
    ap.add_argument("--max-candidates", type=int, default=40, help="근거 그룹마다 원본을 열어 볼 후보 표 수")
    ap.add_argument("--max-facts", type=int, default=8, help="근거 그룹마다 확인할 사실 수 (지역별 벡터는 고르게 뽑음)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--restart", action="store_true", help="이미 판정한 레코드도 다시")
    a = ap.parse_args(argv)
    from backend.rag.csv_index.store import load_index
    golden = Path(a.golden)
    out = Path(a.out) if a.out else golden.with_name("alt_positives.jsonl")
    idx = load_index(a.csv_index) if a.csv_index else load_index()
    done = set()
    if out.exists() and not a.restart:
        done = {json.loads(x)["dataset_id"] for x in out.read_text(encoding="utf-8").splitlines() if x.strip()}
    recs = [json.loads(x) for x in golden.read_text(encoding="utf-8").splitlines() if x.strip()]
    recs = [r for r in recs if r.get("dataset_id") not in done][: a.limit]
    print(f"[정답 판정] 레코드 {len(recs)}개 (이미 판정 {len(done)}) · CSV 값 사전 표 {len(idx.tables)}개 → {out}")
    judge = Judge(idx, a.max_candidates, a.max_facts)
    stat, t0 = Counter(), time.time()
    with out.open("w" if a.restart else "a", encoding="utf-8") as f:
        for i, r in enumerate(recs, 1):
            res = judge.judge(r)
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
            f.flush()
            stat[res["status"]] += 1
            n_alt = sum(len(g["alternatives"]) for g in res["groups"].values())
            stat["with_alt"] += bool(n_alt)
            if n_alt:
                stat["alt_tables"] += n_alt
            if i % 10 == 0 or i == len(recs):
                print(f"  {i}/{len(recs)} · 대체 정답이 있는 레코드 {stat['with_alt']} ({time.time() - t0:.0f}초)")
    print(f"[완료] {dict(stat)}")


if __name__ == "__main__":
    main()
