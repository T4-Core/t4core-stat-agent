"""
전체 뷰 facts 를 raw 에서 독립 재계산해 대조 (팀 기준 C2 원본 수치 추출, LLM 호출 없음)

베이스라인 facts_* 를 import 해 raw 를 넣으면 데이터 경로만 검사되고 계산 규칙의 버그는 통과한다.
그래서 같은 단면을 raw 에서 다시 뽑고, 팀 기준에 맞는 정의로 따로 계산해 비교한다.

검사
  값        facts 값 = raw 로 다시 계산한 값 (뷰와 같은 범주 집합)
  소계 혼입  순위 대상에 다른 범주를 포함하는 코드가 섞였나 (연령 구간 포함 · 지역 깊이 혼합 · 합계류 이름)  B-7
  순위 변경  소계를 빼고 다시 매긴 1위·최하위가 facts 와 다른가                                     B-7
  %p        단위가 % 인 지표의 변화량을 % 로 표기했나                                              B-8
  제목 단위  breakdown 제목의 지역 단위(시도/시군구)와 실제 범주 수가 맞나                            R-7
범위: trend · breakdown · breakdown_trend (items_trend · pyramid 는 미검사)

출력  output/check_facts.csv (뷰 × 검사 1행), output/check_facts.md
실행  python -m profiling.check_facts [--tables DT_...] [--max-tables N] [--force]
"""
import argparse
import json
import math
import re
from collections import defaultdict

import pandas as pd

from profiling import baseline as b
from profiling import config
from profiling.check_records import md_table
from profiling.io_utils import cached, connect, log, read_csv_sql, setup_logging, write_csv

VIEW_TYPES = {"trend", "breakdown", "breakdown_trend"}
TOTAL_NAMES = {"계", "소계", "합계", "총계", "전체", "전국"}
RANGE_PATS = [(re.compile(r"(\d+)\s*[~\-]\s*(\d+)\s*세"), lambda m: (int(m[1]), int(m[2]))),
              (re.compile(r"(\d+)\s*세\s*이상"), lambda m: (int(m[1]), 999)),
              (re.compile(r"(\d+)\s*세\s*미만"), lambda m: (0, int(m[1]) - 1)),
              (re.compile(r"(\d+)\s*세\s*이하"), lambda m: (0, int(m[1]))),
              (re.compile(r"^(\d+)\s*세$"), lambda m: (int(m[1]), int(m[1])))]
GEO_SIDO_MAX = 20                  # 시도는 17개 + 전국·국외 정도. 이보다 많으면 시군구 이하


def close(x, y):
    return x is not None and y is not None and math.isclose(x, y, rel_tol=1e-6, abs_tol=6e-5)


def age_range(name):
    for pat, f in RANGE_PATS:
        m = pat.search(str(name))
        if m:
            return f(m)
    return None


def aggregates(codes, lv):
    """순위 대상 코드 중 다른 대상을 포함하는 묶음 코드 → {code: 근거}"""
    meta = {c["code"]: c for c in lv["codes"]}
    out = {}
    for c in codes:
        m = meta.get(c, {})
        if m.get("is_total") or str(m.get("name", "")).strip() in TOTAL_NAMES:
            out[c] = "합계류 이름"
    rng = {c: age_range(meta.get(c, {}).get("name", "")) for c in codes}
    for c, r in rng.items():
        if r and c not in out:
            inner = [meta[o]["name"] for o, ro in rng.items()
                     if o != c and ro and r[0] <= ro[0] and ro[1] <= r[1] and ro != r]
            if inner:
                out[c] = f"구간 포함 ({meta[c]['name']} ⊃ {', '.join(inner[:3])}{' …' if len(inner) > 3 else ''})"
    if lv["kind"] == "geo":
        depths = {c: meta.get(c, {}).get("depth", 0) for c in codes}
        deep = max(depths.values(), default=0)
        for c, d in depths.items():
            if d < deep and c not in out:
                out[c] = f"지역 깊이 혼합 (깊이 {d} < {deep})"
    return out


def view_codes(dim, lv):
    """뷰 좌표의 분류 선택자 → 코드 목록 (깊이 선택자는 profile 의 코드 깊이로 풀어 쓴다)"""
    if "codes" in dim:
        return list(dim["codes"])
    return [c["code"] for c in lv["codes"] if c["depth"] == dim["depth"]
            and not (dim.get("exclude_total") and c["is_total"])]


def clause(src, levels):
    cond = [f"ITM_ID IN ({', '.join(map(b.sql_str, src['itm_id']))})", f"se = {b.sql_str(src['prd_se'])}"]
    for key, dim in src["dims"].items():
        lv = levels.get(int(key[1:]))
        if lv:
            cond.append(f"C{key[1:]} IN ({', '.join(map(b.sql_str, view_codes(dim, lv)))})")
    p = src.get("period") or {}
    if "in" in p:
        cond.append(f"PRD_DE IN ({', '.join(map(b.sql_str, p['in']))})")
    if "from" in p:
        cond.append(f"PRD_DE >= {b.sql_str(p['from'])}")
    if "to" in p:
        cond.append(f"PRD_DE <= {b.sql_str(p['to'])}")
    return "(" + " AND ".join(cond) + ")"


def load_union(con, raw, views, levels):
    """표의 뷰들이 쓰는 단면만 raw 에서 한 번에 읽는다 (큰 표를 뷰마다 다시 훑지 않게)"""
    lv_cols = [f"C{i}" for i in sorted(levels)]
    sel = ", ".join(lv_cols + [f"{c}_NM" for c in lv_cols])
    where = " OR ".join(clause(v["source"], levels) for v in views)
    return con.execute(f"""
        SELECT {sel}, ITM_ID, se, PRD_DE, try_cast(replace(DT, ',', '') AS DOUBLE) AS value
        FROM (SELECT *, {b.SE_NORM} AS se FROM (
                SELECT *, trim(coalesce(PRD_SE, '')) AS p FROM {read_csv_sql(raw)}))
        WHERE {where}""").df()


def slice_of(df, src, levels):
    m = df["ITM_ID"].isin(src["itm_id"]) & (df["se"] == src["prd_se"])
    for key, dim in src["dims"].items():
        lv = levels.get(int(key[1:]))
        if lv:
            m &= df[f"C{key[1:]}"].isin(view_codes(dim, lv))
    p = src.get("period") or {}
    if "in" in p:
        m &= df["PRD_DE"].isin(p["in"])
    if "from" in p:
        m &= df["PRD_DE"] >= p["from"]
    if "to" in p:
        m &= df["PRD_DE"] <= p["to"]
    return df[m]


def varying_level(src, levels):
    for key, dim in src["dims"].items():
        lv = levels.get(int(key[1:]))
        if lv and ("depth" in dim or len(dim.get("codes", [])) > 1):
            return lv
    return None


def row(v, check, ok, fact="", view_value=None, raw_value=None, note=""):
    return {"view_id": v["id"], "tbl_id": v["source"]["tbl_id"], "category": v["category"],
            "view_type": v["view_type"], "title": v["title"], "check": check, "fact": fact, "ok": ok,
            "view_value": view_value, "raw_value": raw_value, "note": note}


def check_trend(v, d):
    f = {x["label"]: x for x in v.get("facts") or []}
    s = d.dropna(subset=["value"]).sort_values("PRD_DE")["value"].tolist()
    if not s or not f:
        return []
    a, z = s[0], s[-1]
    exp = {"시작": a, "최근": z}
    if len(s) >= 2:
        exp.update({"변화량": z - a, "최대": max(s), "최소": min(s)})
        if a:
            exp["변화율"] = (z - a) / abs(a) * 100
        if len(s) >= 3 and s[-2]:
            exp["직전대비"] = (z - s[-2]) / abs(s[-2]) * 100
    out = [row(v, "값", close(f[k]["value"], val), k, f[k]["value"], val) for k, val in exp.items() if k in f]
    unit = str(v["filters"].get("unit") or "")
    if "변화량" in f and "%" in unit:
        txt = f["변화량"]["text"]
        out.append(row(v, "%p", "%p" in txt, "변화량", note=txt))
    return out


def rank_checks(v, last, lv, xcol, f):
    """last: 한 시점의 범주별 값. 뷰와 같은 집합으로 값 대조 + 소계를 뺀 순위와 비교"""
    d = last.dropna(subset=["value"]).sort_values("value", ascending=False)
    out = []
    if d.empty:
        return out
    exp = {"범주수": len(d)}
    for k in range(min(3, len(d))):
        exp[f"{k + 1}위"] = d["value"].iloc[k]
    if len(d) > 3:
        exp["최하위"] = d["value"].iloc[-1]
    out += [row(v, "값", close(f[k]["value"], val), k, f[k]["value"], val) for k, val in exp.items() if k in f]
    agg = aggregates(d[xcol].tolist(), lv)
    out.append(row(v, "소계 혼입", not agg, note="; ".join(f"{d.loc[d[xcol] == c, xcol + '_NM'].iloc[0]}: {why}"
                                                         for c, why in agg.items())))
    if agg:
        clean = d[~d[xcol].isin(agg)]
        for k, idx in (("1위", 0), ("최하위", -1)):
            if k in f and len(clean):
                was, now = d[xcol + "_NM"].iloc[0 if idx == 0 else -1], clean[xcol + "_NM"].iloc[idx]
                out.append(row(v, "순위 변경", was == now, k, f[k]["value"], clean["value"].iloc[idx],
                               note=f"facts {was} → 소계 제외 시 {now}"))
    if lv["kind"] == "geo":
        n, title = len(d), v["title"]
        bad = ("시군구" in title and n <= GEO_SIDO_MAX) or ("시도" in title and n > GEO_SIDO_MAX)
        if "시군구" in title or "시도" in title:
            out.append(row(v, "제목 단위", not bad, note=f"제목 '{title}' · 범주 {n}개"))
    return out


def check_view(v, df, levels):
    src = v["source"]
    d = slice_of(df, src, levels)
    f = {x["label"]: x for x in v.get("facts") or []}
    if v["view_type"] == "trend":
        return check_trend(v, d)
    lv = varying_level(src, levels)
    if lv is None or d.empty:
        return []
    xcol = f"C{lv['level']}"
    if v["view_type"] == "breakdown":
        return rank_checks(v, d, lv, xcol, f)
    last = d[d["PRD_DE"] == d["PRD_DE"].max()]
    out = rank_checks(v, last, lv, xcol, f)
    if "최대증가" in f:
        first = d[d["PRD_DE"] == d["PRD_DE"].min()].set_index(xcol)["value"]
        ch = (last.set_index(xcol)["value"] - first).dropna()
        if len(ch):
            out.append(row(v, "값", close(f["최대증가"]["value"], ch.max()), "최대증가", f["최대증가"]["value"], ch.max()))
    return out


def check_table(con, r, views):
    prof = json.loads(b.profile_path(r).read_text(encoding="utf-8"))
    levels = {lv["level"]: lv for lv in prof["levels"]}
    df = load_union(con, b.raw_path(r), views, levels)
    out = []
    for v in views:
        try:
            out += check_view(v, df, levels)
        except Exception as e:  # noqa: BLE001  (뷰 하나의 실패로 표 전체를 버리지 않게)
            out.append(row(v, "오류", False, note=f"{e.__class__.__name__}: {str(e)[:120]}"))
    return out


def report(res, n_tables, n_views):
    md = ["# facts 재계산 대조 (check_facts, 팀 기준 C2)", "",
          f"- 대상: 표 {n_tables}개, 뷰 {n_views}개 (trend·breakdown·breakdown_trend) · raw CSV 독립 재계산 · LLM 없음", ""]
    if res.empty:
        return md + ["_(결과 없음)_"]
    s = res.groupby("check").agg(검사수=("ok", "size"), 통과=("ok", "sum")).reset_index()
    s["통과율"] = (s["통과"] / s["검사수"]).map(lambda x: f"{x:.1%}")
    md += ["## 검사별 요약", "", md_table(s, ["check", "검사수", "통과", "통과율"])]
    fail = res[~res["ok"]]
    by_cat = fail.groupby(["category", "check"]).size().unstack(fill_value=0).reset_index()
    md += ["## 카테고리별 실패 건수", "", md_table(by_cat, list(by_cat.columns)) if len(by_cat) else "_(없음)_\n"]
    for chk in ["값", "순위 변경", "소계 혼입", "%p", "제목 단위", "오류"]:
        ex = fail[fail["check"] == chk].drop_duplicates("view_id").head(6)
        if len(ex):
            md += [f"## 사례: {chk} (실패 {int((fail['check'] == chk).sum())}건, 앞 6개)", "",
                   md_table(ex, ["tbl_id", "title", "fact", "view_value", "raw_value", "note"])]
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", nargs="*")
    ap.add_argument("--max-tables", type=int)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    setup_logging()
    tables = b.load_tables(tables=args.tables, max_tables=args.max_tables)
    vbp = defaultdict(list)
    vpath = config.VIEWS_DIR / "views.jsonl"
    for line in vpath.open(encoding="utf-8"):
        v = json.loads(line)
        if v["view_type"] in VIEW_TYPES:
            vbp[v["source"]["tbl_id"]].append(v)
    con = connect()
    res, n_views = [], 0
    for i, r in enumerate(tables.itertuples(), 1):
        views = vbp.get(r.tbl_id, [])
        if not views or not b.raw_path(r).exists() or not b.profile_path(r).exists():
            continue
        n_views += len(views)
        try:
            res += cached("check_facts", b.table_key(r), [b.raw_path(r), b.profile_path(r), vpath],
                          lambda: check_table(con, r, views), force=args.force)
        except Exception as e:  # noqa: BLE001
            log.warning("✗ %s: %s", r.tbl_id, e)
        if i % 20 == 0 or i == len(tables):
            log.info("[check_facts] %d/%d 표", i, len(tables))
    df = pd.DataFrame(res)
    write_csv(df, "check_facts")
    md = report(df, len(vbp.keys() & set(tables["tbl_id"])), n_views)
    p = config.OUTPUT_DIR / "check_facts.md"
    p.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:12]))
    print(f"→ {p}")


if __name__ == "__main__":
    main()
