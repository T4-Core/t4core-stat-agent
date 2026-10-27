"""
kosis_views.py all 결과(rag_views/)가 RAG 에 쓸 수 있는 상태인지 검사

입력  kosis_data/rag_views/{tables,views}.jsonl, profiles/*.json  +  catalog(담당 범위)
출력  profiling/output/records_check.csv   표 1개 = 1행
      profiling/output/records_check.md    검사 8개의 결과와 판정 (한계 후보 표시)

실행  python -m profiling.check_records
"""
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher

import pandas as pd

from profiling import baseline as b
from profiling import config
from profiling.io_utils import write_csv

EMBED_CHAR_WARN = 6000          # HCX 임베딩 v2 입력 한도(약 8k 토큰)에 비해 여유를 둔 경고선 (한국어 ≈ 1~1.5자/토큰)
NEAR_DUP_SIM = 0.92             # 표 레코드 embed_text 유사도가 이 이상이면 '거의 같은 텍스트'


def load_jsonl(p):
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()] if p.exists() else []


def norm_text(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def table_rows(tables, trecs, views_by_parent):
    rows = []
    for r in tables.itertuples():
        key = b.table_key(r)
        raw = b.raw_path(r)
        pf = b.profile_path(r)
        prof = json.loads(pf.read_text(encoding="utf-8")) if pf.exists() else None
        trec = trecs.get(f"table::{key}")
        views = views_by_parent.get(f"table::{key}", [])
        items_all = [i["itm_id"] for i in (prof or {}).get("items", [])]
        items_in_views = {i for v in views for i in v["source"].get("itm_id", [])}
        no_total = [lv["obj_nm"] for lv in (prof or {}).get("levels", [])
                    if lv["n_codes"] > 1 and not lv["total_code"]]
        lens = [len(x["embed_text"]) for x in ([trec] if trec else []) + views]
        rows.append({
            "category": r.category, "tbl_id": r.tbl_id, "tbl_nm": r.tbl_nm,
            "raw_mb": round(raw.stat().st_size / 1e6, 1) if raw.exists() else None,
            "has_raw": raw.exists(), "has_profile": prof is not None, "has_table_rec": trec is not None,
            "schema_prd_se": r.prd_se, "prd_se": ",".join((prof or {}).get("periods", {}).keys()),
            "n_rows": (prof or {}).get("n_rows"), "n_symbols": (prof or {}).get("n_symbols"),
            "n_views": len(views),
            "n_items": len(items_all), "n_items_in_views": len(items_in_views & set(items_all)),
            "item_coverage": round(len(items_in_views & set(items_all)) / len(items_all), 3) if items_all else None,
            "n_views_unit_empty": sum(1 for v in views if not v["filters"].get("unit")),
            "levels_without_total": " | ".join(no_total),
            "max_embed_chars": max(lens) if lens else None,
        })
    return pd.DataFrame(rows)


def dup_groups(recs):
    """embed_text 가 완전히 같은 레코드 묶음 (서로 다른 표끼리만)"""
    by_text = defaultdict(list)
    for x in recs:
        by_text[norm_text(x["embed_text"])].append(x)
    out = []
    for t, xs in by_text.items():
        parents = {x.get("parent_id") or x["id"] for x in xs}
        if len(parents) > 1:
            out.append({"n": len(xs), "tables": sorted(p.split("::")[1] for p in parents), "title": xs[0]["title"]})
    return sorted(out, key=lambda d: -d["n"])


def near_dup_tables(trecs):
    """같은 카테고리 표 레코드끼리 embed_text 유사도 (형제 표가 텍스트로 구분되는지)"""
    by_cat = defaultdict(list)
    for x in trecs:
        by_cat[x["category"]].append(x)
    pairs = []
    for xs in by_cat.values():
        for i in range(len(xs)):
            for j in range(i + 1, len(xs)):
                a, c = norm_text(xs[i]["embed_text"]), norm_text(xs[j]["embed_text"])
                sm = SequenceMatcher(None, a, c, autojunk=False)
                if sm.quick_ratio() < NEAR_DUP_SIM:
                    continue
                s = sm.ratio()
                if s >= NEAR_DUP_SIM:
                    pairs.append({"sim": round(s, 3), "a": xs[i]["source"]["tbl_id"], "a_nm": xs[i]["title"],
                                  "b": xs[j]["source"]["tbl_id"], "b_nm": xs[j]["title"]})
    return sorted(pairs, key=lambda d: -d["sim"])


def md_table(df, cols):
    if df.empty:
        return "_(없음)_\n"
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df[cols].itertuples(index=False)]
    return "\n".join(lines) + "\n"


def main():
    vd = config.VIEWS_DIR
    tables = b.load_tables()
    trec_list = load_jsonl(vd / "tables.jsonl")
    views = load_jsonl(vd / "views.jsonl")
    cats = set(config.CATEGORIES)
    trec_list = [x for x in trec_list if x["category"] in cats]
    views = [v for v in views if v["category"] in cats]
    trecs = {x["id"]: x for x in trec_list}
    vbp = defaultdict(list)
    for v in views:
        vbp[v["parent_id"]].append(v)

    df = table_rows(tables, trecs, vbp)
    write_csv(df, "records_check")
    recs = trec_list + views
    dups = dup_groups(recs)
    near = near_dup_tables(trec_list)
    lens = pd.Series([len(x["embed_text"]) for x in recs]) if recs else pd.Series(dtype=int)
    vunit = pd.Series([v["filters"].get("prd_se") for v in views]).value_counts().to_dict()
    n_unit_empty = sum(1 for v in views if not v["filters"].get("unit"))
    has_raw = df[df.has_raw]
    zero = df[df.has_table_rec & (df.n_views == 0)]
    low_cov = df[df.item_coverage.notna() & (df.item_coverage < 1)]
    flags = []

    md = ["# 검색 레코드 점검 (records_check)", "",
          f"- 대상: 담당 {len(config.CATEGORIES)}개 카테고리, catalog 표 {len(df)}개",
          f"- 레코드: 표 {len(trec_list)}개 + 뷰 {len(views)}개 = {len(recs)}개", ""]

    # 1) 표 누락
    lost = has_raw[~has_raw.has_profile | ~has_raw.has_table_rec]
    md += ["## 1. 표 누락 (raw → profile → 표 레코드)", "",
           f"raw {int(df.has_raw.sum())} → profile {int(df.has_profile.sum())} → 표 레코드 {int(df.has_table_rec.sum())}"
           f" (raw 없음 {int((~df.has_raw).sum())}개)", "",
           md_table(pd.concat([df[~df.has_raw], lost]), ["category", "tbl_id", "tbl_nm", "has_raw", "has_profile"])]
    if len(lost):
        flags.append(f"변환 중 사라진 표 {len(lost)}개")

    # 2) 뷰 0개
    md += ["## 2. 뷰가 0개인 표", "",
           "answer() 는 뷰만 답변 근거로 쓰므로, 이 표가 정답인 질문은 숫자를 줄 수 없다.", "",
           f"**{len(zero)}개** / 표 레코드 {int(df.has_table_rec.sum())}개", "",
           md_table(zero, ["category", "tbl_id", "tbl_nm", "prd_se", "n_items"])]
    if len(zero):
        flags.append(f"뷰가 없는 표 {len(zero)}개 → 검색돼도 숫자 답변 불가")

    # 3) 항목 커버리지
    tot_i, in_i = int(df.n_items.sum()), int(df.n_items_in_views.sum())
    md += [f"## 3. 항목 커버리지 (MAX_ITEMS = {b.MAX_ITEMS})", "",
           f"뷰에 등장한 항목 {in_i} / 전체 {tot_i} ({in_i / max(tot_i, 1):.1%}). "
           f"항목이 일부만 담긴 표 {len(low_cov)}개", "",
           md_table(low_cov.sort_values("item_coverage").head(15),
                    ["category", "tbl_id", "tbl_nm", "n_items", "n_items_in_views", "item_coverage"])]
    if len(low_cov):
        flags.append(f"뷰에 빠진 항목 {tot_i - in_i}개 (표 {len(low_cov)}개)")

    # 4) 주기 표기
    mism = df[df.has_profile & (df.prd_se != df.schema_prd_se)]
    md += ["## 4. 주기 표기 (schema ↔ 정제 결과)", "",
           f"뷰의 prd_se 분포: {vunit}. schema 와 표기가 다른 표 {len(mism)}개", "",
           md_table(mism.groupby(["schema_prd_se", "prd_se"]).size().reset_index(name="n_tables"),
                    ["schema_prd_se", "prd_se", "n_tables"])]
    if len(mism):
        flags.append(f"주기 표기 불일치 {len(mism)}개 표 (예: 연간 A ↔ Y)")

    # 5) 단위
    md += ["## 5. 단위가 빈 뷰", "",
           f"**{n_unit_empty} / {len(views)}** ({n_unit_empty / max(len(views), 1):.1%}) 뷰의 filters.unit 이 비어 있음", "",
           md_table(df[df.n_views_unit_empty > 0].groupby("category")
                    .agg(tables=("tbl_id", "size"), views_unit_empty=("n_views_unit_empty", "sum")).reset_index(),
                    ["category", "tables", "views_unit_empty"])]
    if n_unit_empty:
        flags.append(f"단위 없는 뷰 {n_unit_empty}개 → 답변 단위 누락·추측 위험")

    # 6) 임베딩 호출 수
    md += ["## 6. 임베딩 호출 수 (3단계 비용)", "",
           f"dense-mode single 기준 **{len(recs)}회** (표 {len(trec_list)} + 뷰 {len(views)}). "
           f"multi 는 질문·바꿔쓰기 문장마다 추가", ""]

    # 7) embed_text 길이
    if len(lens):
        over = int((lens > EMBED_CHAR_WARN).sum())
        md += ["## 7. embed_text 길이 (글자 수)", "",
               f"중앙값 {int(lens.median())}, p99 {int(lens.quantile(.99))}, 최대 {int(lens.max())}. "
               f"{EMBED_CHAR_WARN}자 초과 {over}개", ""]
        if over:
            flags.append(f"임베딩 입력 한도 근접 {over}개")

    # 8) 중복
    md += ["## 8. embed_text 중복 (서로 다른 표 사이)", "",
           f"완전 중복 묶음 {len(dups)}개, 표 레코드 근접 중복(유사도 ≥ {NEAR_DUP_SIM}) {len(near)}쌍", "",
           "**완전 중복 (상위 10)**", "",
           md_table(pd.DataFrame(dups[:10]).assign(tables=lambda d: d.tables.str.join(", ")) if dups
                    else pd.DataFrame(), ["n", "title", "tables"]),
           "**근접 중복 (상위 10)**", "",
           md_table(pd.DataFrame(near[:10]), ["sim", "a", "a_nm", "b", "b_nm"])]
    if dups or near:
        flags.append(f"검색 텍스트로 구분 안 되는 형제 표: 완전 중복 {len(dups)}묶음, 근접 {len(near)}쌍")

    md = md[:5] + ["## 한계 후보 요약", ""] + [f"- {f}" for f in flags] + [""] + md[5:]
    p = config.OUTPUT_DIR / "records_check.md"
    p.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(f"- {f}" for f in flags) or "한계 후보 없음")
    print(f"→ {p}")


if __name__ == "__main__":
    main()
