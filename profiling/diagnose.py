"""
E2E·스모크 검색에서 나온 한계를 담당 표 전체 규모로 측정 (LLM 호출 없음)

D1 조용한 오답 위험 (G-2·B-6·R-2)  apply_conditions 가 다루지 못하는 분류 조건이 '경고 없이' 무시되는 뷰
D2 문맥 숫자 반올림 (G-1)          fmt_v(소수 둘째 자리 고정)로 정밀도가 깎이는 값
D3 단위 문자열 섞임 (B-4)          여러 단위가 한 문자열로 붙은 항목
D4 BM25 형태소 어긋남 (R-6)        질문형 표현과 문서 표현의 토큰 교집합
D5 뷰 제목 맥락 부족 (R-4)         제목에 표 이름의 핵심 단어가 하나도 없는 뷰
D6 수록 끝난 옛 표 (R-5)           마지막 시점이 오래됐고 같은 이름의 최신 표가 있는지

출력  output/diagnose.md, output/diagnose.csv (표 1개 = 1행)
실행  python -m profiling.diagnose
"""
import argparse
import json
import os
import re
from collections import defaultdict
from datetime import date

import duckdb
import pandas as pd

from profiling import baseline as b
from profiling import config
from profiling.check_records import md_table
from profiling.io_utils import write_csv

os.chdir(config.REPO_ROOT)
import kosis_rag_qa as qa  # noqa: E402

qa.VIEWS_DIR = config.VIEWS_DIR

HANDLED_KINDS = {"geo", "sex"}                  # apply_conditions 가 코드로 바꿔 끼우는 분류 (연도는 시점으로 처리)
YEAR_LIKE = re.compile(r"^(19|20)\d{2}$")
GENERIC = {"추이", "시도", "시군구", "전국", "연령", "성", "별", "비율", "항목", "통계", "현황", "행정구역", "구분",
           "계", "합계", "기준", "자료"}
TOKEN_PAIRS = [("순이동자 수", "순이동"), ("이동자 수", "이동자수"), ("출생아 수", "출생아수"),
               ("혼인 건수", "혼인건수"), ("1인 가구", "1인"), ("합계 출산율", "합계출산율")]
STALE_BEFORE = date.today().year - config.STALE_YEARS


def tbl(df):
    return md_table(df, list(df.columns))


def load_jsonl(p):
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def fixed_level_code(src, lv):
    """뷰 좌표에서 이 분류가 코드 하나로 고정돼 있으면 그 코드"""
    codes = src["dims"].get(f"c{lv['level']}", {}).get("codes") or []
    return codes[0] if len(codes) == 1 else None


def d1_silent(prof, views):
    """분류 L 이 코드 하나로 고정된 뷰에, L 의 다른 코드를 묻는 질문을 넣고 실제 apply_conditions 를 돌린다.
    L 이 바뀌지 않았는데 missing 이 비면 '조용한 무시' — LLM 은 고정 코드의 값을 질문 대상 값으로 읽게 된다."""
    out = []
    for lv in prof["levels"]:
        if lv["n_codes"] < 2 or lv["kind"] in HANDLED_KINDS:
            continue
        for v in views:
            fixed = fixed_level_code(v["source"], lv)
            if fixed is None:
                continue
            target = next((c for c in lv["codes"] if c["code"] != fixed and not c["is_total"]), None)
            if target is None:
                continue
            q = f"{target['name']} {v['filters']['items'][0] if v['filters']['items'] else ''}".strip()
            src, applied, missing = qa.apply_conditions(v, q)
            if fixed_level_code(src, lv) == fixed and not missing:
                out.append({"view_id": v["id"], "level": lv["obj_nm"], "kind": lv["kind"],
                            "fixed_is_total": fixed == lv["total_code"], "probe": q,
                            "year_like": bool(YEAR_LIKE.match(target["name"]))})
    return out


def d2_precision(con):
    """소수 셋째 자리 이하가 있는 값과, 반올림 상대오차 0.5% 초과 값 (표별)"""
    pq = (config.VIEWS_DIR / "processed").as_posix()
    return con.execute(f"""
        SELECT table_key, count(value) AS n_values,
               count(*) FILTER (WHERE abs(value - round(value, 2)) > 1e-9) AS n_lossy,
               count(*) FILTER (WHERE value <> 0 AND abs(value - round(value, 2)) / abs(value) > 0.005) AS n_lossy_05pct
        FROM read_parquet('{pq}/*.parquet') WHERE value IS NOT NULL GROUP BY table_key""").df()


def is_mixed_unit(u):
    toks = set(str(u).split())
    return str(u).count("명당") >= 2 or len(toks & {"명", "건", "가구", "%", "세", "쌍", "호", "개", "원"}) >= 2


def keywords(text):
    return {t for t in qa.tokenize(text) if len(t) >= 2 and t not in GENERIC and not t.isdigit()}


def name_skeleton(nm):
    return re.sub(r"\(.*?\)|\s|[-–_]", "", str(nm))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conditions", choices=["base", "v2"], default="base",
                    help="v2: D1 을 profiling/conditions_v2.apply_conditions_v2 로 측정")
    args = ap.parse_args()
    sfx = "" if args.conditions == "base" else f"_{args.conditions}"
    if args.conditions == "v2":
        from profiling.conditions_v2 import apply_conditions_v2
        qa.apply_conditions = apply_conditions_v2
    tables = b.load_tables()
    trecs = {x["source"]["tbl_id"]: x for x in load_jsonl(config.VIEWS_DIR / "tables.jsonl")}
    vbp = defaultdict(list)
    for v in load_jsonl(config.VIEWS_DIR / "views.jsonl"):
        vbp[v["source"]["tbl_id"]].append(v)
    con = duckdb.connect()
    prec = d2_precision(con).set_index("table_key")

    rows, silent_all, ctx_poor_ex = [], [], []
    for r in tables.itertuples():
        pf = b.profile_path(r)
        if not pf.exists():
            continue
        prof = json.loads(pf.read_text(encoding="utf-8"))
        views = vbp.get(r.tbl_id, [])
        sil = d1_silent(prof, views)
        silent_all += [dict(s, tbl_id=r.tbl_id, tbl_nm=r.tbl_nm, category=r.category) for s in sil]
        kw = keywords(r.tbl_nm)
        poor = [v for v in views if kw and not (keywords(v["title"]) & kw)]
        ctx_poor_ex += [(r.tbl_nm, v["title"]) for v in poor[:2]]
        mixed = [i for i in prof["items"] if is_mixed_unit(i["unit"])]
        last = max((int(p["prd_de"][:4]) for ps in prof["periods"].values() for p in ps if p["prd_de"][:4].isdigit()),
                   default=None)
        pr = prec.loc[prof["table_key"]] if prof["table_key"] in prec.index else None
        rows.append({
            "category": r.category, "tbl_id": r.tbl_id, "tbl_nm": r.tbl_nm, "n_views": len(views),
            "d1_silent_views": len({s["view_id"] for s in sil}),
            "d1_levels": " | ".join(sorted({s["level"] for s in sil})),
            "d1_first_code_fixed": any(not s["fixed_is_total"] for s in sil),
            "d1_year_like_level": any(sum(bool(YEAR_LIKE.match(c["name"])) for c in lv["codes"]) >= 0.6 * lv["n_codes"]
                                      and lv["n_codes"] >= 3 for lv in prof["levels"]),
            "d2_values": int(pr.n_values) if pr is not None else 0,
            "d2_lossy": int(pr.n_lossy) if pr is not None else 0,
            "d2_lossy_05pct": int(pr.n_lossy_05pct) if pr is not None else 0,
            "d3_mixed_unit_items": len(mixed), "d3_unit_example": mixed[0]["unit"] if mixed else "",
            "d5_ctx_poor_views": len(poor),
            "last_year": last, "d6_stale": last is not None and last < STALE_BEFORE,
            "skeleton": name_skeleton(r.tbl_nm),
        })
    df = pd.DataFrame(rows)
    newest = df.groupby(["category", "skeleton"]).last_year.max()
    df["d6_has_newer_sibling"] = [bool(s) and newest.get((c, k), 0) >= STALE_BEFORE
                                  for c, k, s in zip(df.category, df.skeleton, df.d6_stale)]
    write_csv(df.drop(columns="skeleton"), f"diagnose{sfx}")
    sil = pd.DataFrame(silent_all)
    write_csv(sil, f"diagnose_d1_silent{sfx}")

    n_t, n_v = len(df), int(df.n_views.sum())
    md = ["# 한계 진단 (diagnose)", "", f"- 대상: 표 {n_t}개, 뷰 {n_v}개 (담당 4개 카테고리) · LLM 호출 없음 · 조건 적용 `{args.conditions}`", ""]

    # D1
    sv = sil.drop_duplicates("view_id") if len(sil) else sil
    md += ["## D1. 조용한 오답 위험 (G-2 · B-6 · R-2)", "",
           "분류가 코드 하나로 고정된 뷰에 그 분류의 **다른 값**을 묻는 질문을 넣고 실제 `apply_conditions`를 실행했다. "
           "고정이 그대로인데 `missing`이 비면 LLM은 경고 없이 고정된 칸의 값을 받는다 (Q4와 같은 경로).", "",
           f"- 위험 뷰 **{len(sv)} / {n_v}** ({len(sv) / max(n_v, 1):.1%}), 위험 표 **{int((df.d1_silent_views > 0).sum())} / {n_t}**",
           f"- 그중 합계가 아닌 **첫 코드로 고정**된 경우(B-6, 질문과 무관한 특정 값이 나감): 표 {int(df.d1_first_code_fixed.sum())}개",
           f"- 분류값이 연도처럼 생긴 분류(년생 등)가 있는 표(R-2): {int(df.d1_year_like_level.sum())}개", ""]
    if len(sil):
        by = (sil.drop_duplicates(["view_id", "level"]).groupby(["category", "kind"]).size()
              .unstack(fill_value=0).reset_index())
        md += ["분류 종류별 위험 뷰 수 (age = 연령, other = 그 밖의 분류):", "", by.pipe(tbl), "",
               "예시 (검사 질문 → 무시된 분류):", ""]
        ex = sil.drop_duplicates("tbl_id").head(6)
        md += [f"- `{x.tbl_id}` {x.tbl_nm}: 질문 `{x.probe}` → **{x.level}** 무시"
               f" ({'합계' if x.fixed_is_total else '첫 코드'}로 고정)" for x in ex.itertuples()] + [""]

    # D2
    tv, tl, t5 = int(df.d2_values.sum()), int(df.d2_lossy.sum()), int(df.d2_lossy_05pct.sum())
    top = df.sort_values("d2_lossy_05pct", ascending=False).head(5)
    md += ["## D2. 문맥 숫자 반올림 (G-1)", "",
           f"- 소수 셋째 자리 이하가 있어 `fmt_v`에서 깎이는 값: **{tl:,} / {tv:,}** ({tl / max(tv, 1):.2%}), "
           f"표 {int((df.d2_lossy > 0).sum())}개",
           f"- 반올림 상대오차 0.5% 초과 (예: 0.748 → 0.75 = 0.27%, 0.004 → 0.00): **{t5:,}**개 값, "
           f"표 {int((df.d2_lossy_05pct > 0).sum())}개", "",
           top[["category", "tbl_id", "tbl_nm", "d2_values", "d2_lossy_05pct"]].pipe(tbl), ""]

    # D3
    mx = df[df.d3_mixed_unit_items > 0]
    md += ["## D3. 단위 문자열 섞임 (B-4)", "",
           f"- 여러 단위가 붙은 항목 **{int(df.d3_mixed_unit_items.sum())}개**, 표 **{len(mx)}개**", "",
           mx.groupby("d3_unit_example").agg(tables=("tbl_id", "size"), items=("d3_mixed_unit_items", "sum"))
           .reset_index().sort_values("tables", ascending=False).head(8).pipe(tbl), ""]

    # D4
    md += ["## D4. BM25 형태소 어긋남 (R-6)", "", "| 질문 표현 | 문서 표현 | 질문 토큰 | 문서 토큰 | 교집합 |",
           "|---|---|---|---|---|"]
    for qtxt, dtxt in TOKEN_PAIRS:
        qt, dt = qa.tokenize(qtxt), qa.tokenize(dtxt)
        md.append(f"| {qtxt} | {dtxt} | {qt} | {dt} | {sorted(set(qt) & set(dt)) or '**없음**'} |")
    md.append("")

    # D5
    md += ["## D5. 뷰 제목 맥락 부족 (R-4)", "",
           f"- 제목에 표 이름의 핵심 단어가 하나도 없는 뷰 **{int(df.d5_ctx_poor_views.sum())} / {n_v}** "
           f"({df.d5_ctx_poor_views.sum() / max(n_v, 1):.1%}), 표 {int((df.d5_ctx_poor_views > 0).sum())}개", "",
           "| 표 이름 | 뷰 제목 |", "|---|---|"] + [f"| {a} | {t} |" for a, t in ctx_poor_ex[:8]] + [""]

    # D6
    st = df[df.d6_stale]
    md += ["## D6. 수록 끝난 옛 표 (R-5)", "",
           f"- 마지막 시점이 {STALE_BEFORE}년 이전인 표 **{len(st)} / {n_t}**, 그중 이름이 같은 최신 형제 표가 있는 표 "
           f"{int(st.d6_has_newer_sibling.sum())}개", "",
           st.groupby("category").agg(stale_tables=("tbl_id", "size"), oldest_last=("last_year", "min"))
           .reset_index().pipe(tbl), ""]

    p = config.OUTPUT_DIR / f"diagnose{sfx}.md"
    p.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"→ {p}")


if __name__ == "__main__":
    main()
