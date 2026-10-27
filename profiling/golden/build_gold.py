"""
골든셋 정답 채우기: golden_set.jsonl(이름 좌표) → 정답 값·지표 · 정답 레코드 id · 맞는 뷰 · facts 대조

정답은 RAG 산출물(processed parquet)이 아니라 raw CSV 에서 직접 계산한다.
RAG 가 만든 데이터로 RAG 를 채점하면, 같은 버그가 양쪽에 있을 때 오답이 정답처럼 보이기 때문이다.

문항 유형 (type)
  lookup   정답 칸 1개                                  gold_value
  change   두 시점: start · end · diff · pct · diff_pp   gold_metrics
  rank     한 분류의 순위: top1 · bottom1 (소계는 exclude_names·code_len 으로 문항마다 명시)
  peak     시계열 최대: peak_period · peak_value
  compare  한 분류의 두 값: a · b · diff_pp

출력
  golden/golden_set.built.jsonl   E2E 채점용
  golden/qa_eval.jsonl            kosis_rag_qa.py eval --qa 형식 {"question", "gold": [id, ...]}
  output/golden_check.md          문항별 정답 확인표 (lookup / 지표형)

실행  python -m profiling.golden.build_gold
"""
import json
import math
import sys
from collections import defaultdict

import duckdb

from profiling import baseline as b
from profiling import config
from profiling.io_utils import csv_columns, read_csv_sql

GOLDEN_DIR = config.PROFILING_DIR / "golden"
FIT_SHARE = 0.9                   # rank·peak: 뷰가 순위 대상·시계열의 90% 이상을 담아야 '맞는 뷰'


class GoldError(Exception):
    """정답 좌표가 모호하거나 값이 없음 → 이 문항은 시험지로 쓸 수 없다"""


def load_jsonl(p):
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def to_num(dt):
    try:
        return float(str(dt).replace(",", ""))
    except ValueError:
        return None                                    # 통계부호(-, X 등) → 숫자 정답 없음


class Table:
    """raw 한 표의 이름 → 코드 해석기"""

    def __init__(self, con, row):
        self.con, self.raw = con, b.raw_path(row)
        if not self.raw.exists():
            raise GoldError(f"raw 없음: {self.raw.name}")
        self.cols = csv_columns(con, self.raw)
        self.src = read_csv_sql(self.raw)
        lv = [i for i in range(1, 9) if f"C{i}" in self.cols]
        self.obj_of = dict(zip(lv, con.execute(
            f"SELECT {', '.join(f'any_value(C{i}_OBJ_NM)' for i in lv)} FROM {self.src}").fetchone())) if lv else {}
        levels, self.items = b.meta_levels(b.load_meta(row))
        self.by_obj = {str(l["obj_nm"]).strip(): l for l in levels}

    def col(self, obj_nm):
        c = next((i for i, o in self.obj_of.items() if str(o).strip() == obj_nm), None)
        if c is None:
            raise GoldError(f"분류 '{obj_nm}' 없음. raw 분류: {list(self.obj_of.values())}")
        return f"C{c}"

    def code(self, obj_nm, name):
        col = self.col(obj_nm)
        codes = [c["code"] for c in (self.by_obj.get(obj_nm) or {}).get("codes", []) if c["name"] == name]
        if not codes:                                  # meta 에 없으면 raw 이름으로 (meta 누락 대비)
            codes = [r[0] for r in self.con.execute(
                f"SELECT DISTINCT {col} FROM {self.src} WHERE trim({col}_NM) = {b.sql_str(name)}").fetchall()]
        if len(codes) != 1:
            raise GoldError(f"'{obj_nm}={name}' 코드 {len(codes)}개 {codes[:5]}")
        return col, codes[0]

    def resolve(self, exp, free=()):
        """고정 좌표 → {컬럼: 코드}, 항목 코드. free 에 든 분류(순위·비교 대상)만 비워 둘 수 있다"""
        where = dict(self.code(o, n) for o, n in exp["dims"].items())
        free_cols = {self.col(o) for o in free}
        missing = [o for i, o in self.obj_of.items() if f"C{i}" not in where and f"C{i}" not in free_cols]
        if missing:
            raise GoldError(f"지정하지 않은 분류 {missing} (순위·비교 대상 외에는 모두 고정해야 함)")
        itm = [i["itm_id"] for i in self.items if str(i["nm"]).strip() == exp["item"]]
        if len(itm) != 1:
            raise GoldError(f"항목 '{exp['item']}' 코드 {len(itm)}개. 항목: {[i['nm'] for i in self.items][:10]}")
        return where, itm[0]

    def rows(self, where, itm_id, prd_se, prd_de=None, extra=""):
        cond = [f"{c} = {b.sql_str(v)}" for c, v in where.items()]
        cond += [f"ITM_ID = {b.sql_str(itm_id)}", f"PRD_SE = {b.sql_str(prd_se)}"]
        if prd_de:
            cond.append(f"PRD_DE IN ({', '.join(map(b.sql_str, prd_de))})")
        unit = "UNIT_NM" if "UNIT_NM" in self.cols else "NULL"
        return self.con.execute(f"SELECT *, {unit} AS _unit FROM {self.src} WHERE {' AND '.join(cond)} {extra}").df()

    def one(self, where, itm_id, prd_se, prd_de):
        df = self.rows(where, itm_id, prd_se, [prd_de])
        if len(df) != 1:
            raise GoldError(f"{where} {prd_de}: raw 행 {len(df)}개 (1개여야 함)")
        r = df.iloc[0]
        return to_num(r["DT"]), str(r["DT"]), r["_unit"], r["LST_CHN_DE"]


def metrics_change(t, exp, where, itm):
    p0, p1 = exp["periods"]
    a, b_ = t.one(where, itm, exp["prd_se"], p0)[0], t.one(where, itm, exp["prd_se"], p1)[0]
    diff = b_ - a
    return {"start": {"period": p0, "value": a}, "end": {"period": p1, "value": b_},
            "diff": {"value": diff}, "diff_pp": {"value": diff},
            "pct": {"value": diff / abs(a) * 100 if a else None}}


def ranked(t, exp, where, itm):
    col = t.col(exp["rank_over"])
    df = t.rows(where, itm, exp["prd_se"], [exp["prd_de"]])
    df = df[~df[f"{col}_NM"].str.strip().isin(exp.get("exclude_names", []))]
    if exp.get("code_len"):
        df = df[df[col].str.len() == exp["code_len"]]
    totals = {c["code"] for c in (t.by_obj.get(exp["rank_over"]) or {}).get("codes", []) if c.get("is_total")}
    df = df[~df[col].isin(totals)]
    out = sorted(((r[f"{col}_NM"].strip(), to_num(r["DT"]), r[col]) for _, r in df.iterrows()
                  if to_num(r["DT"]) is not None), key=lambda x: -x[1])
    if len(out) < 2:
        raise GoldError(f"순위 대상 {len(out)}개")
    return col, out


def metrics_rank(t, exp, where, itm):
    _, out = ranked(t, exp, where, itm)
    return {"top1": {"name": out[0][0], "value": out[0][1]}, "bottom1": {"name": out[-1][0], "value": out[-1][1]},
            "n_categories": {"value": len(out)}}


def metrics_peak(t, exp, where, itm):
    df = t.rows(where, itm, exp["prd_se"])
    s = [(r["PRD_DE"], to_num(r["DT"])) for _, r in df.iterrows() if to_num(r["DT"]) is not None]
    p, v = max(s, key=lambda x: x[1])
    return {"peak_period": {"value": p}, "peak_value": {"value": v}, "n_periods": {"value": len(s)}}


def metrics_compare(t, exp, where, itm):
    (obj, (na, nb)), = exp["compare"].items()
    col_a, ca = t.code(obj, na)
    _, cb = t.code(obj, nb)
    a = t.one({**where, col_a: ca}, itm, exp["prd_se"], exp["prd_de"])[0]
    b_ = t.one({**where, col_a: cb}, itm, exp["prd_se"], exp["prd_de"])[0]
    return {"a": {"name": na, "value": a}, "b": {"name": nb, "value": b_}, "diff_pp": {"value": b_ - a}}


METRICS = {"change": metrics_change, "rank": metrics_rank, "peak": metrics_peak, "compare": metrics_compare}


def free_dims(g):
    e = g["expect"]
    return ([e["rank_over"]] if g["type"] == "rank" else []) + list(e.get("compare", {}))


def fit_views(con, t, g, views, where, itm):
    """조건을 적용하지 않은 상태로 필요한 수치를 모두 담은 뷰 (C1 '맞는 뷰'의 정적 기준)"""
    exp, out = g["expect"], []
    need_col = None
    if g["type"] == "rank":
        need_col, rk = ranked(t, exp, where, itm)
        need_codes = {c for _, _, c in rk}
    for v in views:
        s = v["source"]
        if s["prd_se"] != exp["prd_se"] or itm not in s.get("itm_id", []):
            continue
        df = b.kv.load_view(s, config.VIEWS_DIR, con)
        m = df["itm_id"] == itm
        for c, code in where.items():
            m &= df[f"c{c[1:]}_code"] == code
        d = df[m]
        if g["type"] == "change":
            ok = set(exp["periods"]) <= set(d["prd_de"])
        elif g["type"] == "rank":
            got = set(d.loc[d["prd_de"] == exp["prd_de"], f"c{need_col[1:]}_code"])
            ok = len(got & need_codes) >= FIT_SHARE * len(need_codes)
        elif g["type"] == "peak":
            ok = d["prd_de"].nunique() >= FIT_SHARE * g["gold_metrics"]["n_periods"]["value"]
        else:                                          # compare: 두 칸 모두
            (obj, names), = exp["compare"].items()
            col = t.col(obj)
            codes = {t.code(obj, n)[1] for n in names}
            ok = codes <= set(d.loc[d["prd_de"] == exp["prd_de"], f"c{col[1:]}_code"])
        if ok:
            out.append({"id": v["id"], "view_type": v["view_type"], "title": v["title"],
                        "facts": {f["label"]: f for f in v.get("facts") or []}})
    return out


def close(x, y, tol):
    return x is not None and y is not None and math.isclose(x, y, rel_tol=0, abs_tol=tol + 1e-9)


def facts_check(g, fits):
    """맞는 뷰의 facts 가 raw 지표와 같은가 (C2 문항 단위). 첫 번째 맞는 뷰 기준"""
    if not fits:
        return "맞는 뷰 없음"
    f, gm, typ = fits[0]["facts"], g["gold_metrics"], g["type"]
    if typ == "rank":
        top = f.get("1위")
        res = "1위 일치" if top and gm["top1"]["name"] in top["text"] else f"1위 불일치 (facts: {top and top['text']})"
        if "bottom1" in g["metrics"]:
            lo = f.get("최하위") or f.get("2위")
            res += " / 최하위 " + ("일치" if lo and gm["bottom1"]["name"] in lo["text"] else
                                f"불일치 (facts: {lo and lo['text']})")
        return res
    if typ == "change":
        s, e = f.get("시작"), f.get("최근")
        if not (s and e):
            return "시계열 facts 없음"
        same = close(s["value"], gm["start"]["value"], 1e-4) and close(e["value"], gm["end"]["value"], 1e-4)
        res = "기간 일치" if same else f"기간 다름 (facts: {s['text']} → {e['text']})"
        prev = f.get("직전대비")                           # 최근 두 시점을 묻는 질문은 '직전대비' facts 로 답할 수 있음
        if not same and "pct" in g["metrics"] and prev and close(prev["value"], gm["pct"]["value"], 0.05):
            res = f"직전대비 일치 ({prev['text']})"
        d = f.get("변화량")
        if "diff_pp" in g["metrics"] and d and "%p" not in d["text"] and "%" in d["text"]:
            res += " / 변화량 단위 % (→ %p 여야 함)"
        return res
    if typ == "peak":
        mx = f.get("최대")
        return ("최대 일치" if mx and close(mx["value"], gm["peak_value"]["value"], 1e-4) and
                str(gm["peak_period"]["value"]) in mx["text"] else f"최대 불일치 (facts: {mx and mx['text']})")
    return "해당 facts 없음 (두 값의 차는 계산 필요)"


def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, str):
        return v
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.4g}"


def metric_text(g):
    gm = g["gold_metrics"]
    parts = []
    for k in g["metrics"]:
        m = gm[k]
        unit = "%p" if k == "diff_pp" else "%" if k == "pct" else ""
        parts.append(f"{k} {m.get('name', '')} {m.get('period', '')} {fmt(m['value'])}{unit}".replace("  ", " "))
    return " / ".join(parts)


def main():
    gold = load_jsonl(GOLDEN_DIR / "golden_set.jsonl")
    trecs = {x["id"]: x for x in load_jsonl(config.VIEWS_DIR / "tables.jsonl")}
    vbp = defaultdict(list)
    for v in load_jsonl(config.VIEWS_DIR / "views.jsonl"):
        vbp[v["parent_id"]].append(v)
    tables = b.load_tables(tables=sorted({t for g in gold for t in g["answer_tables"]}))
    rows = {r.tbl_id: r for r in tables.itertuples()}
    con = duckdb.connect()
    built, qa, rep_lookup, rep_metric = [], [], [], []

    for g in gold:
        exp, typ = g["expect"], g.get("type", "lookup")
        gold_ids = []
        for t in g["answer_tables"]:
            if t in rows:
                tid = f"table::{b.table_key(rows[t])}"
                gold_ids += ([tid] if tid in trecs else []) + [v["id"] for v in vbp.get(tid, [])]
        rec = dict(g, type=typ, gold_ids=gold_ids)
        try:
            r = rows.get(exp["tbl_id"])
            if r is None:
                raise GoldError(f"담당 범위 catalog 에 {exp['tbl_id']} 없음")
            t = Table(con, r)
            views = vbp.get(f"table::{b.table_key(r)}", [])
            where, itm = t.resolve(exp, free_dims(rec))
            if typ == "lookup":
                val, dt, unit, chn = t.one(where, itm, exp["prd_se"], exp["prd_de"])
                hits = lookup_views(con, views, where, itm, exp)
                for h in hits:
                    h["table"] = exp["tbl_id"]
                rec.update(status="ok", gold_value=val, gold_raw=dt, gold_unit=unit or "", lst_chn_de=chn)
                extra, rec["alt_tables"] = alt_views(con, rec, rows, vbp)
                hits += extra
                rec.update(coords={**where, "ITM_ID": itm}, answerable_views=hits)
                mism = [h["id"] for h in hits if val is not None and not close(h["value"], val, 0)]
                rep_lookup.append([g["qid"], g["question"], dt, unit or "(없음)", len(gold_ids), len(hits),
                                   ", ".join(sorted({h["view_type"] for h in hits})) or "-",
                                   f"불일치 {len(mism)}" if mism else "일치" if hits else "-"])
            else:
                rec["gold_metrics"] = METRICS[typ](t, exp, where, itm)
                unit = t.rows(where, itm, exp["prd_se"], extra="LIMIT 1")["_unit"]
                fits = fit_views(con, t, rec, views, where, itm)
                for f in fits:
                    f["table"] = exp["tbl_id"]
                extra, rec["alt_tables"] = alt_views(con, rec, rows, vbp)
                fits += extra
                rec.update(status="ok", gold_unit=(unit.iloc[0] if len(unit) else "") or "",
                           coords={**where, "ITM_ID": itm},
                           fit_views=[{k: v for k, v in f.items() if k != "facts"} for f in fits],
                           facts_check=facts_check(rec, fits))
                rep_metric.append([g["qid"], typ, g["question"], metric_text(rec), len(fits),
                                   " · ".join(f["title"] for f in fits[:2]) or "-", rec["facts_check"]])
        except GoldError as e:
            rec.update(status="error", error=str(e))
            (rep_lookup if typ == "lookup" else rep_metric).append([g["qid"], g["question"], f"✗ {e}"])
        built.append(rec)
        qa.append({"question": g["question"], "gold": gold_ids, "qid": g["qid"]})

    if "--preview" in sys.argv:                        # 파일을 쓰지 않고 이전 built 와의 차이만 본다
        print_preview(built, GOLDEN_DIR / "golden_set.built.jsonl")
        return
    with (GOLDEN_DIR / "golden_set.built.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(x, ensure_ascii=False, default=str) + "\n" for x in built)
    with (GOLDEN_DIR / "qa_eval.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in qa)

    def table(head, rows_):
        return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + \
               ["| " + " | ".join(str(c) for c in r) + " |" for r in rows_]
    md = ["# 골든셋 정답 확인", "", "## 단일 값 조회 (lookup)", ""]
    md += table(["qid", "질문", "정답(raw)", "단위(raw)", "정답 id 수", "답할 수 있는 뷰", "뷰 종류", "뷰 값 vs raw"],
                rep_lookup)
    md += ["", "## 지표형 (change · rank · peak · compare)", ""]
    md += table(["qid", "유형", "질문", "정답 지표 (raw)", "맞는 뷰 수", "맞는 뷰 (앞 2개)", "facts vs raw"], rep_metric)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (config.OUTPUT_DIR / "golden_check.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def print_preview(built, old_path):
    """--preview: 다른 정답 표의 맞는 뷰를 넣었을 때 문항별로 무엇이 바뀌는지 (파일은 쓰지 않는다)"""
    old = {x["qid"]: x for x in load_jsonl(old_path)} if old_path.exists() else {}

    def views(r):
        return (r.get("answerable_views") if r.get("type", "lookup") == "lookup" else r.get("fit_views")) or []
    rows_, same = [], 0
    for r in built:
        o = old.get(r["qid"], {})
        seen = {v["id"] for v in views(o)}
        added = [f"{v['id']} [{v.get('table', '')}]" for v in views(r) if v["id"] not in seen]
        fc = (o.get("facts_check", "-"), r.get("facts_check", "-"))
        if not added and fc[0] == fc[1] and not r.get("alt_tables"):
            same += 1
            continue
        bad = [v["id"] for v in views(r) if r.get("type") == "lookup" and v.get("value") is not None
               and not close(v["value"], r["gold_value"], 0)]                 # C2 가 0 이 되는 경우
        rows_.append([r["qid"], r.get("type"), len(views(o)), len(views(r)), "<br>".join(added) or "-",
                      (f"{fc[0]} → {fc[1]}" if fc[0] != fc[1] else "-") + (f" / 뷰 값≠raw {len(bad)}개" if bad else ""),
                      "<br>".join(f"{t}: {n}" for t, n in (r.get("alt_tables") or {}).items()) or "-"])
    head = ["qid", "유형", "이전 맞는 뷰", "이후 맞는 뷰", "추가된 뷰", "facts_check 변화", "다른 정답 표"]
    print("\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
                    + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows_]))
    print(f"\n변화 없는 문항 {same}개 / 전체 {len(built)}개")


def same_values(rec, t, exp, where, itm):
    """다른 정답 표의 raw 값이 주 표에서 계산한 정답과 같은가 (같을 때만 그 표의 뷰를 '맞는 뷰'로 인정)"""
    typ = rec["type"]
    if typ == "lookup":
        return close(t.one(where, itm, exp["prd_se"], exp["prd_de"])[0], rec["gold_value"], 1e-6)
    gm2 = METRICS[typ](t, exp, where, itm)
    for k in rec["metrics"]:
        m1, m2 = rec["gold_metrics"][k], gm2[k]
        if "name" in m1 and str(m1["name"]).strip() != str(m2["name"]).strip():
            return False
        v1, v2 = m1["value"], m2["value"]
        if isinstance(v1, str) or isinstance(v2, str):
            if v1 != v2:
                return False
        elif not close(v1, v2, 1e-6):
            return False
    return True


def alt_views(con, rec, rows, vbp):
    """주 표(expect.tbl_id)가 아닌 정답 표에서 같은 값을 담은 뷰. → (뷰 목록, {표: 사유})
    표마다 분류·항목 이름이 달라 alt_expect.json 에 좌표를 따로 적어 둔다. raw 값이 주 표와 같을 때만 인정하고,
    지표(항목)가 다른 뷰(예: 총전입 vs 시군구간전입)는 항목 코드가 달라 자연히 제외된다"""
    exp, out, notes = rec["expect"], [], {}
    specs = json.loads((GOLDEN_DIR / "alt_expect.json").read_text(encoding="utf-8")).get(rec.get("base_qid", rec["qid"]), {})
    for tid in rec["answer_tables"]:
        if tid == exp["tbl_id"] or tid not in rows:
            continue
        if tid not in specs:
            notes[tid] = "제외: alt_expect.json 에 좌표 없음"
            continue
        exp2 = {**exp, "tbl_id": tid, **specs[tid]}
        rec2 = {**rec, "expect": exp2}
        try:
            t = Table(con, rows[tid])
            where, itm = t.resolve(exp2, free_dims(rec2))
            if not same_values(rec2, t, exp2, where, itm):
                raise GoldError("raw 값이 주 표와 다름")
        except GoldError as e:
            notes[tid] = f"제외: {e}"
            continue
        views = vbp.get(f"table::{b.table_key(rows[tid])}", [])
        got = lookup_views(con, views, where, itm, exp2) if rec["type"] == "lookup" else fit_views(con, t, rec2, views, where, itm)
        for h in got:
            h["table"] = tid
        out += got
        notes[tid] = f"raw 값 일치, 맞는 뷰 {len(got)}개"
    return out, notes


def lookup_views(con, views, where, itm_id, exp):
    """정답 칸을 담은 뷰('답할 수 있는 뷰')와 그 값 — 베이스라인 정제가 값을 바꾸지 않았는지도 함께 본다"""
    out = []
    for v in views:
        if v["source"]["prd_se"] != exp["prd_se"] or itm_id not in v["source"].get("itm_id", []):
            continue
        df = b.kv.load_view(v["source"], config.VIEWS_DIR, con)
        m = (df["itm_id"] == itm_id) & (df["prd_de"] == exp["prd_de"])
        for c, code in where.items():
            m &= df[f"c{c[1:]}_code"] == code
        if m.any():
            out.append({"id": v["id"], "view_type": v["view_type"], "value": float(df.loc[m, "value"].iloc[0])
                        if df.loc[m, "value"].notna().any() else None, "unit": v["filters"].get("unit", "")})
    return out


if __name__ == "__main__":
    main()
