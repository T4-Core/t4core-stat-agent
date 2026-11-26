"""시계열 묶음 후보 — 같은 통계인데 수록 기간만 나뉜 표 (예: 1970~2004 표 + 2005~2025 표)

KOSIS 는 같은 통계를 기간별로 다른 표(다른 tbl_id)로 나눠 두는 경우가 있다. 지금 검색·View 는 그중 한 표만 써서
'2000~2025년' 을 물으면 한쪽 기간이 빠진다. 이어 붙이기 전에 어떤 표끼리 묶을지 사람이 확정하도록 후보를 뽑는다.

  python -m backend.rag.ingestion.series mine  [--out series_candidates.csv] [--check-values 200] [--min-score 3]
      메타 프로필(meta_profiles.jsonl) + 개념 카탈로그(concepts.json, 있으면) → 후보 쌍 검토표
      (엑셀 등에서 '판정' 열에 Y / N 을 채운다)
  python -m backend.rag.ingestion.series build --review series_candidates.csv
      판정 Y 인 쌍 → 묶음(이어지는 표 사슬) → <VIEW_OUT_DIR>/series.json
  python -m backend.rag.ingestion.series show

후보 조건 (쌍 a, b — a 가 먼저 시작)
  · 같은 주기(년·월 …)가 있고, 기간이 엇갈림: a.시작 < b.시작, a.끝 < b.끝 (한쪽이 다른 쪽을 덮으면 기간판이 아님)
  · 틈은 --max-gap 년 이하(기본 2), 겹침은 --max-overlap 년 이하(기본 10)
  · 다음 중 하나로 같은 묶음 후보에 들어야 함 (모든 쌍을 비교하지 않으려고 먼저 묶음)
      제목 핵심이 같음 — 성별 괄호·연도 괄호('(1970~2004)')·'(구)'·지역 수준 꼬리를 뗀 이름 (search/siblings.core_title 과 같은 규칙 + α)
      항목 이름 집합이 같음 (단위·괄호를 뗀 이름)
      같은 조사 안에서 항목 이름이 절반 이상 겹침
      개념 카탈로그의 같은 개념
빼는 쌍 (구조가 달라 이어 붙일 수 없음)
  · 성별이 다름 — '(계)' 와 '(남)' · '(여)' (괄호가 없으면 계). search/siblings.table_sex 와 같은 규칙
  · 연령 구간이 다름 — '연령(1세)' 와 '연령(5세)' (합계만 같고 연령별 값은 짝이 안 맞음)
  · 실적과 장래추계 — 한쪽만 '장래'·'추계'
점수 (검토 순서용, 판정은 사람이)
  제목 핵심 같음 +3 · 개념 같음 +2 · 항목 겹침 ×2 · 분류 겹침 ×1 · 같은 조사 +1 · 단위 같음 +0.5 (배수 아님 −1)
  제목에서 양쪽에만 있는 말이 둘 다 있음(혼인↔이혼, 외국인 근로자↔기타 외국인) −3 → diff_terms 열
  (지역 수준 '시도별·시군구별', 연도, 성별·기간 괄호는 비교에서 뺌. 이름이 통째로 바뀐 표
   — '국제결혼가정 자녀' → '부모의 국적별 외국인주민 자녀' — 도 여기서 깎이므로 --min-score 1 로 따로 볼 수 있음)
  --check-values N: 점수 상위 N 쌍은 원본을 정규화해 합계 행의 값을 비교 (겹치는 해의 차이 · 이어지는 해의 비율)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path

SE_ORDER = ["Y", "H", "Q", "M", "D", "F", "IR"]
PERIOD_HINT = re.compile(
    r"\(\s*(?:구|舊|이전|폐지|중지|종료|구자료|구\s*자료)\s*\)|\[\s*구\s*\]|_구$|"
    r"\(?\s*(?:19|20)\d{2}\s*년?\s*(?:이전|이후|부터|까지|~)\s*(?:(?:19|20)\d{2}\s*년?)?\s*\)?|"
    r"(?:19|20)\d{2}\s*년?\s*[~\-–]\s*(?:(?:19|20)\d{2})?\s*년?")
UNIT_PAREN = re.compile(r"\s*\([^()]*\)\s*$")
GENERIC_ITEMS = {"계", "합계", "총계", "전체", "값", "수", "인구", "건수", "비율", "구성비"}
MAX_BLOCK = 300      # 이보다 큰 묶음(흔한 항목 이름 하나 등)은 근거로 쓰지 않음
COLS = ["group", "score", "a_tbl", "a_name", "a_period", "b_tbl", "b_name", "b_period", "union", "overlap", "gap",
        "same_title", "diff_terms", "concept", "item_sim", "dim_sim", "same_survey", "units", "a_survey", "b_survey",
        "value_check", "판정", "메모"]


def _norm(s):
    return re.sub(r"[\s·_\-()（）\[\]:,]", "", str(s or ""))


def title_core(nm):
    from backend.rag.search.siblings import core_title
    return core_title(PERIOD_HINT.sub(" ", str(nm or "")))


AGE_WIDTH = re.compile(r"(\d+)\s*세\s*\)")
PROJECTION = re.compile(r"장래|추계")
LEVEL_WORD = re.compile(r"^(?:전국|시도|시군구|읍면동|시|군|구|동|읍|면|행정구역|지역)(?:별|단위)?$")
TERM_SPLIT = re.compile(r"[\s/·,\-–_]+|및|과|와")


def sex_tag(nm):
    from backend.rag.search.siblings import table_sex
    return table_sex(nm) or "계"


def age_width(nm):
    """'연령(5세)별' → '5' (제목에 없으면 None)"""
    m = AGE_WIDTH.search(str(nm or ""))
    return m.group(1) if m else None


def is_projection(p):
    return bool(PROJECTION.search(f"{p.get('tbl_nm') or ''} {p.get('survey_nm') or ''}"))


def title_terms(nm):
    """비교용 제목 낱말 — 괄호(성별·기간·단위)·연도·지역 수준 말을 뺀 것"""
    s = re.sub(r"\([^()]*\)", " ", str(nm or ""))
    s = re.sub(r"(?:19|20)\d{2}\s*년?", " ", s)
    out = set()
    for t in TERM_SPLIT.split(s):
        t = t.strip()
        if len(t) >= 2 and not LEVEL_WORD.match(t):
            out.add(t.removesuffix("별") if len(t) > 2 else t)
    return out


def diff_terms(a_nm, b_nm):
    """양쪽에만 있는 낱말이 둘 다 있으면 'x / y' (다른 통계일 가능성), 아니면 ''"""
    ta, tb = title_terms(a_nm), title_terms(b_nm)
    da, db = ta - tb, tb - ta
    return f"{' '.join(sorted(da))} / {' '.join(sorted(db))}" if da and db else ""


def structural_mismatch(a, b):
    """이어 붙일 수 없는 구조 차이 (없으면 None)"""
    if sex_tag(a["tbl_nm"]) != sex_tag(b["tbl_nm"]):
        return "성별"
    wa, wb = age_width(a["tbl_nm"]), age_width(b["tbl_nm"])
    if wa and wb and wa != wb:
        return "연령 구간"
    if is_projection(a) != is_projection(b):
        return "실적·추계"
    return None


def item_names(p):
    return {_norm(UNIT_PAREN.sub("", i["name"])) for i in p.get("items") or [] if i.get("name")}


def dim_names(p):
    out = set()
    for lv in p.get("levels") or []:
        k = lv.get("kind")
        out.add(f"<{k}>" if k in ("regions", "sex", "ages", "scenario", "cohort") else _norm(lv.get("obj_nm")).removesuffix("별"))
    return out


def jaccard(a, b):
    return len(a & b) / len(a | b) if a or b else 1.0


def spans(p):
    """{주기: (시작 해, 끝 해)} — 같은 주기가 여러 줄이면 합침"""
    out = {}
    for pr in p.get("periods") or []:
        se, a, b = pr.get("se"), pr.get("year_from"), pr.get("year_to")
        if se and a and b:
            lo, hi = out.get(se, (a, b))
            out[se] = (min(lo, a), max(hi, b))
    return out


def _unit_rel(ua, ub):
    """'same' · 'multiple'(명/천명) · 'diff'"""
    if not ua or not ub or set(ua) == set(ub):
        return "same"
    strip = lambda u: re.sub(r"^(?:천|만|백만|십억|억)", "", u)
    return "multiple" if {strip(u) for u in ua} == {strip(u) for u in ub} else "diff"


def _concept_of(path=None):
    try:
        from backend.rag.search.concepts import load
        groups = load(path)
    except Exception:  # noqa: BLE001  (카탈로그가 없으면 이 근거만 빠짐)
        return {}
    return {t: i for i, g in enumerate(groups) for t in g}


def _blocks(profs, concept_of):
    """같은 묶음 후보로 볼 표 목록들 (key → tbl_id 목록)"""
    blocks = defaultdict(set)
    by_survey = defaultdict(list)
    for p in profs:
        t = p["tbl_id"]
        blocks[("title", title_core(p["tbl_nm"]))].add(t)
        items = item_names(p)
        if items and not items <= GENERIC_ITEMS:
            blocks[("items", tuple(sorted(items)))].add(t)
        if t in concept_of:
            blocks[("concept", concept_of[t])].add(t)
        by_survey[p.get("survey_nm") or ""].append(p)
    for s, ps in by_survey.items():             # 같은 조사 안에서 항목이 절반 이상 겹치는 표
        for a, b in combinations(ps, 2):
            ia, ib = item_names(a) - GENERIC_ITEMS, item_names(b) - GENERIC_ITEMS
            if ia and ib and jaccard(ia, ib) >= 0.5:
                blocks[("survey", s, a["tbl_id"])].update((a["tbl_id"], b["tbl_id"]))
    return [ts for ts in blocks.values() if 1 < len(ts) <= MAX_BLOCK]


def _pair(a, b, max_gap, max_overlap):
    """(먼저 시작하는 표, 뒤 표, 주기, 겹침 해 수, 틈 해 수) 또는 None"""
    sa, sb = spans(a), spans(b)
    for se in SE_ORDER + sorted(set(sa) - set(SE_ORDER)):
        if se not in sa or se not in sb:
            continue
        (a0, a1), (b0, b1) = sa[se], sb[se]
        if (b0, b1) < (a0, a1):
            a, b, (a0, a1), (b0, b1) = b, a, (b0, b1), (a0, a1)
        if not (a0 < b0 and a1 < b1):           # 한쪽이 다른 쪽을 덮음 → 기간판이 아님
            return None
        overlap, gap = max(0, a1 - b0 + 1), max(0, b0 - a1 - 1)
        if gap > max_gap or overlap > max_overlap:
            return None
        return a, b, se, overlap, gap
    return None


def score_pair(a, b, concept_of):
    same_title = title_core(a["tbl_nm"]) == title_core(b["tbl_nm"])
    dt = "" if same_title else diff_terms(a["tbl_nm"], b["tbl_nm"])
    concept = a["tbl_id"] in concept_of and concept_of.get(a["tbl_id"]) == concept_of.get(b["tbl_id"])
    item_sim, dim_sim = jaccard(item_names(a), item_names(b)), jaccard(dim_names(a), dim_names(b))
    same_survey = (a.get("survey_nm") or "") == (b.get("survey_nm") or "")
    units = _unit_rel(a.get("units"), b.get("units"))
    s = (3 * same_title + 2 * concept + 2 * item_sim + dim_sim + same_survey
         + {"same": 0.5, "multiple": 0, "diff": -1}[units] - 3 * bool(dt))
    return round(s, 2), {"same_title": int(same_title), "diff_terms": dt, "concept": int(concept),
                         "item_sim": round(item_sim, 2),
                         "dim_sim": round(dim_sim, 2), "same_survey": int(same_survey), "units": units}


# ── 값 비교 (선택) ───────────────────────────────────────────────
def _total_series(con, tbl_id, se):
    """정규화 parquet 에서 모든 분류가 합계(없으면 기본값)인 행 → {(해, 항목): 값}"""
    from backend.core.config import VIEW_OUT_DIR
    from backend.core.utils import sql_str
    from backend.rag.ingestion.normalize import ensure_normalized
    prof = ensure_normalized(con, tbl_id)
    where = [f"prd_se = {sql_str(se)}"] + [f"c{lv['level']}_code = {sql_str(lv['default_code'])}"
                                            for lv in prof["levels"] if lv.get("default_code")]
    from backend.data_engine import stat_store
    rel = stat_store.relation(con, prof, where + ["value IS NOT NULL"], base=VIEW_OUT_DIR)   # parquet 또는 PostgreSQL
    rows = con.execute(f"SELECT year, itm_nm, avg(value) FROM {rel} "
                       f"WHERE {' AND '.join(where)} AND value IS NOT NULL GROUP BY year, itm_nm").fetchall()
    first_only = sum(1 for lv in prof["levels"] if not lv.get("total_code"))
    return {(int(y), _norm(UNIT_PAREN.sub("", n))): float(v) for y, n, v in rows}, first_only


def value_check(con, a_id, b_id, se):
    """겹치는 해가 있으면 그 해들의 최대 상대 차이, 없으면 이어지는 해의 값 비율 (b 첫 해 / a 끝 해)"""
    try:
        va, fa = _total_series(con, a_id, se)
        vb, fb = _total_series(con, b_id, se)
    except Exception as e:  # noqa: BLE001
        return f"확인 못 함: {e.__class__.__name__}: {str(e)[:80]}"
    items = {i for _, i in va} & {i for _, i in vb}
    if not items and len({i for _, i in va}) == 1 and len({i for _, i in vb}) == 1:   # 항목이 하나씩이면 이름이 달라도 짝
        ia, ib = next(iter({i for _, i in va})), next(iter({i for _, i in vb}))
        vb = {(y, ia): v for (y, i), v in vb.items() if i == ib}
        items = {ia}
    if not items:
        return "같은 항목 없음"
    tail = " (합계 없는 분류는 첫 코드로 비교)" if fa or fb else ""
    both = sorted({y for y, i in va if i in items} & {y for y, i in vb if i in items})
    if both:
        diffs = [abs(va[(y, i)] - vb[(y, i)]) / max(abs(va[(y, i)]), 1e-9)
                 for y in both for i in items if (y, i) in va and (y, i) in vb]
        if not diffs:
            return "겹치는 해에 같은 항목 값 없음"
        m = max(diffs)
        return f"겹치는 {len(both)}개 해 최대 차이 {m:.1%}" + (" — 같은 값" if m < 0.005 else "") + tail
    a_last = max(y for y, i in va if i in items)
    b_first = min(y for y, i in vb if i in items)
    ratios = [vb[(b_first, i)] / va[(a_last, i)] for i in items if (a_last, i) in va and (b_first, i) in vb and va[(a_last, i)]]
    if not ratios:
        return "이어지는 해 값 없음"
    r = sorted(ratios)[len(ratios) // 2]
    flag = " — 단위 배수?" if r > 50 or r < 0.02 else (" — 크게 다름" if not 0.67 <= r <= 1.5 else "")
    return f"이어지는 해 {a_last}→{b_first} 비율 {r:.2f}{flag}{tail}"


# ── mine ─────────────────────────────────────────────────────────
def _period_text(p, se):
    a, b = spans(p)[se]
    return f"{se} {a}~{b}"


def mine(out="series_candidates.csv", min_score=3.0, max_gap=2, max_overlap=10, check_values=0, concepts=None,
         profiles=None):
    from backend.rag.ingestion.meta_profile import load_meta_profiles
    profs = [p for p in (profiles if profiles is not None else load_meta_profiles()) if p.get("periods")]
    by_id = {p["tbl_id"]: p for p in profs}
    concept_of = _concept_of(concepts)
    seen, recs, dropped = set(), [], {}
    for ts in _blocks(profs, concept_of):
        for x, y in combinations(sorted(ts), 2):
            if (x, y) in seen:
                continue
            seen.add((x, y))
            got = _pair(by_id[x], by_id[y], max_gap, max_overlap)
            if not got:
                continue
            a, b, se, overlap, gap = got
            if (why := structural_mismatch(a, b)):
                dropped[why] = dropped.get(why, 0) + 1
                continue
            s, ev = score_pair(a, b, concept_of)
            if s < min_score:
                continue
            ua, ub = spans(a)[se], spans(b)[se]
            recs.append({"score": s, "a_tbl": a["tbl_id"], "a_name": a["tbl_nm"], "a_period": _period_text(a, se),
                         "b_tbl": b["tbl_id"], "b_name": b["tbl_nm"], "b_period": _period_text(b, se),
                         "union": f"{se} {ua[0]}~{max(ua[1], ub[1])}", "overlap": overlap, "gap": gap, **ev,
                         "a_survey": a.get("survey_nm"), "b_survey": b.get("survey_nm"), "value_check": "",
                         "판정": "", "메모": "", "_se": se})
    recs.sort(key=lambda r: (-r["score"], r["a_tbl"], r["b_tbl"]))
    if check_values:
        from backend.data_engine.duckdb_client import connect
        con = connect()
        try:
            for r in recs[:check_values]:
                r["value_check"] = value_check(con, r["a_tbl"], r["b_tbl"], r["_se"])
        finally:
            con.close()
    for gid, members in enumerate(_chains([(r["a_tbl"], r["b_tbl"]) for r in recs]), 1):
        for r in recs:
            if r["a_tbl"] in members:
                r["group"] = f"G{gid:03d}"
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(recs)
    n_groups = len({r.get("group") for r in recs})
    print(f"[시계열 후보] 표 {len(profs)}개 → 후보 쌍 {len(recs)}개 · 사슬 {n_groups}개 → {out}"
          + (f"  (구조가 달라 뺀 쌍: {', '.join(f'{k} {v}' for k, v in dropped.items())})" if dropped else ""))
    for r in recs[:10]:
        print(f"  {r['score']:>5} {r.get('group')} {r['a_tbl']}({r['a_period']}) + {r['b_tbl']}({r['b_period']})"
              f" | {r['a_name'][:30]} / {r['b_name'][:30]}" + (f" | {r['value_check']}" if r["value_check"] else ""))
    return recs


def _chains(pairs):
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in pairs:
        parent[find(a)] = find(b)
    groups = defaultdict(set)
    for x in list(parent):
        groups[find(x)].add(x)
    return sorted(groups.values(), key=lambda g: sorted(g))


# ── build / show ─────────────────────────────────────────────────
YES = {"Y", "YES", "O", "예", "1", "TRUE", "맞음"}


def series_path():
    from backend.core.config import VIEW_OUT_DIR
    return VIEW_OUT_DIR / "series.json"


def build(review, out=None, profiles=None):
    """검토표의 판정 Y 쌍 → 사슬 → series.json {series: [{id, name, se, tables[{tbl_id, tbl_nm, from, to}], union}]}"""
    from backend.rag.ingestion.meta_profile import load_meta_profiles
    rows = list(csv.DictReader(open(review, encoding="utf-8-sig")))
    ok = [r for r in rows if str(r.get("판정") or "").strip().upper() in YES]
    by_id = {p["tbl_id"]: p for p in (profiles if profiles is not None else load_meta_profiles())}
    se_of = {(r["a_tbl"], r["b_tbl"]): r["a_period"].split()[0] for r in ok}
    out_series = []
    for i, members in enumerate(_chains([(r["a_tbl"], r["b_tbl"]) for r in ok]), 1):
        se = next(se_of[k] for k in se_of if k[0] in members)
        tables = sorted(({"tbl_id": t, "tbl_nm": by_id[t]["tbl_nm"], "from": spans(by_id[t])[se][0],
                          "to": spans(by_id[t])[se][1]} for t in members if t in by_id and se in spans(by_id[t])),
                        key=lambda x: (x["from"], x["to"]))
        if len(tables) < 2:
            continue
        out_series.append({"id": f"S{i:03d}", "name": tables[-1]["tbl_nm"], "se": se, "tables": tables,
                           "union": [tables[0]["from"], max(t["to"] for t in tables)],
                           "notes": [r["메모"] for r in ok if r["a_tbl"] in members and r.get("메모")]})
    path = Path(out) if out else series_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"created": datetime.now().isoformat(timespec="seconds"), "from": str(review),
                                "series": out_series}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[시계열 묶음] 판정 Y {len(ok)}/{len(rows)}쌍 → 묶음 {len(out_series)}개 → {path}")
    return out_series


def show(path=None):
    p = Path(path) if path else series_path()
    if not p.exists():
        print(f"없음: {p} (먼저 mine → 검토 → build)")
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    for s in d["series"]:
        print(f"{s['id']} {s['name']} [{s['se']} {s['union'][0]}~{s['union'][1]}] "
              + " + ".join(f"{t['tbl_id']}({t['from']}~{t['to']})" for t in s["tables"]))
    return d["series"]


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.rag.ingestion.series")
    ap.add_argument("cmd", choices=["mine", "build", "show"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--review", default="series_candidates.csv", help="build: 판정을 채운 검토표")
    ap.add_argument("--min-score", type=float, default=3.0)
    ap.add_argument("--max-gap", type=int, default=2, help="두 표 사이 비어 있어도 되는 해 수")
    ap.add_argument("--max-overlap", type=int, default=10, help="두 표가 겹쳐도 되는 해 수")
    ap.add_argument("--check-values", type=int, default=0, help="점수 상위 N 쌍의 값을 원본으로 비교 (정규화가 돌아 느림)")
    ap.add_argument("--concepts", default=None, help="개념 카탈로그 경로 (기본 <CSV 값 사전>/concepts.json)")
    a = ap.parse_args(argv)
    if a.cmd == "mine":
        return mine(a.out or "series_candidates.csv", a.min_score, a.max_gap, a.max_overlap, a.check_values, a.concepts)
    if a.cmd == "build":
        return build(a.review, a.out)
    return show(a.out)


if __name__ == "__main__":
    main()
