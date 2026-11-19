"""기간 묶음 · 이어붙이기 — 같은 통계가 연도별로 나뉜 표들을 한 묶음으로 보고, 요청 연도를 여러 표로 채운다

출처  feature/kos14/RAG-hybrid 의 table_card_search/period_groups.py (Saige, 11-17·18) 를 지금 검색 구조로 옮김.
      그때는 카드 파일(table_card_expend/out/full)을 읽었고, 여기서는 검색 엔진이 이미 만든 표 단면(Facet)을 읽는다
      → 따로 만들 산출물 없이 TableSearch 가 처음 뜰 때 한 번 계산 (표 ~1,100개, 수 ms)

형제 표(siblings.py)와의 차이
  siblings      '어느 판 하나를 앞에 둘까' — 성별 (계)/(남)/(여) · 연도판 · 지역 수준판 중 질문 좌표에 맞는 표 하나 (순위)
  period_groups '요청 연도를 다 담으려면 어느 판들을 이어야 하나' — 연도판만 (성별·지역 수준이 다르면 다른 통계)
                순위는 바꾸지 않고 결과에 계획(stitch)만 붙인다. View 단계가 view_stitch 일 때 그 계획으로 View 를 더 만듦

묶는 기준 (모두 만족)
  · 조사명이 같음
  · 제목에서 연도 표기 '(2007~2015)' '(~2007)' '(2008~)' '(2006)' '(2011년~)' 와 '(신)' '(구)' 를 지우고
    띄어쓰기 · 해마다 바뀐 표기(/ , · - – 및 의) · 끝의 '수' 를 지운 제목이 같음
      예) 시도/직업별(~2007) 혼인 + 시도/직업별(2008~) 혼인
          연령/성별 인구-읍면동 (2005) + 연령 및 성별 인구 - 읍면동 (2010)
  · 이름 자체가 바뀐 경우(국제결혼 이주자 ↔ 결혼이민자)는 사람이 확인한 연결 configs/period_links.csv 로 합침
    (A–B, B–C 면 A·B·C 한 묶음)

  groups = build_groups(facets)                    # {tbl_id: 묶음}
  stitch_plan("DT_1IN9501", [1990, 1995], groups)  # → {group, tables[{tbl_id, title, years}], years_have, years_missing, mixed_cycle}

  python -m backend.rag.search.period_groups [--csv 경로]   # 지금 코퍼스로 묶음을 만들어 요약 (사람이 볼 CSV 도)
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

_YEAR_PAREN = re.compile(r"\(\s*~?\s*\d{4}\s*년?\s*(~\s*(\d{4}\s*년?)?)?\s*\)")
_OLD_NEW = re.compile(r"\((신|구)\)")
_MARKS = re.compile(r"[/,·\-–—]|및|의")       # 해마다 바뀐 표기 (성/연령 ↔ 성 및 연령, - ↔ –, 거처의종류 ↔ 거처종류)
_SU_END = re.compile(r"수(?=$|\(|-)")          # 끝의 '수' (외국인수 ↔ 외국인)


def links_path():
    from backend.core.config import CONFIGS_DIR
    return CONFIGS_DIR / "period_links.csv"


def title_key(title):
    """원래 제목 → 연도 표기·표기 차이를 지운 비교용 제목"""
    t = _YEAR_PAREN.sub("", title or "")
    t = _OLD_NEW.sub("", t)
    t = re.sub(r"\s+", "", t)
    t = _SU_END.sub("", t)                       # '-' 를 지우기 전에 ('외국인수-시도')
    return _MARKS.sub("", t)


def load_links(path=None):
    """사람이 확인한 연결 [(옛 표 ID, 새 표 ID)]. 파일이 없으면 빈 목록"""
    path = Path(path) if path else links_path()
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as f:
        return [(r["옛 표 ID"].strip(), r["새 표 ID"].strip()) for r in csv.DictReader(f)
                if r.get("옛 표 ID") and r.get("새 표 ID")]


def facet_years(f):
    """표 단면 → 수록 연도 목록. 값 사전이 있으면 실제 연도, 없으면 정의된 기간을 펼침"""
    if f.years:
        return sorted(f.years)
    return sorted({y for a, b in f.spans if a and b for y in range(int(a), int(b) + 1)})


def build_groups(facets, links=None):
    """facets {tbl_id: Facet} → {tbl_id: 묶음}. 표가 둘 이상인 묶음만
    묶음 = {group, survey, key, members: [{tbl_id, title, years, cycle}] (오래된 표부터), links?}"""
    links = load_links() if links is None else links
    g = defaultdict(list)
    for f in facets.values():
        if f.tbl_nm:
            g[(f.survey_nm or "", title_key(f.tbl_nm))].append(f)
    key_of = {f.tbl_id: k for k, fs in g.items() for f in fs}
    parent = {k: k for k in g}

    def root(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    used = defaultdict(list)
    for a, b in links:
        if a in key_of and b in key_of:
            ra, rb = root(key_of[a]), root(key_of[b])
            if ra != rb:
                parent[rb] = ra
            used[a].append(b)
    merged = defaultdict(list)
    for k in g:
        merged[root(k)].append(k)
    out, n = {}, 0
    for keys in sorted(merged.values(), key=lambda ks: sorted(ks)):
        keys.sort(key=lambda k: -len(g[k]))     # 표가 많은 키를 대표로
        fs = [f for k in keys for f in g[k]]
        if len(fs) < 2:
            continue
        members = sorted(({"tbl_id": f.tbl_id, "title": f.tbl_nm, "years": facet_years(f), "cycle": sorted(f.cycles)}
                          for f in fs), key=lambda m: (m["years"][-1] if m["years"] else 0, m["years"][0] if m["years"] else 0))
        n += 1
        grp = {"group": f"G{n:03d}", "survey": " + ".join(dict.fromkeys(k[0] for k in keys)),
               "key": " + ".join(k[1] for k in keys), "members": members}
        ids = {m["tbl_id"] for m in members}
        if len(keys) > 1:
            grp["links"] = [[a, b] for a, bs in used.items() if a in ids for b in bs]
        for m in members:
            out[m["tbl_id"]] = grp
    return out


def year_split(years, want):
    """표의 수록 연도 + 요청 연도 → (있는 연도, 없는 연도). 표에 기간 정보가 없으면 (None, None)"""
    want = sorted({y for y in want or [] if isinstance(y, int)})
    if not want or not years:
        return None, None
    ys = set(years)
    return [y for y in want if y in ys], [y for y in want if y not in ys]


def stitch_plan(tbl_id, want, groups):
    """검색된 표 + 요청 연도 → 이어붙이기 계획. 묶음이 없거나 이 표만으로 충분하면 None
    {"group", "tables": [{"tbl_id", "title", "years"}], "years_have", "years_missing", "mixed_cycle"}"""
    g = (groups or {}).get(tbl_id)
    want = sorted({y for y in want or [] if isinstance(y, int)})
    if not g or not want:
        return None
    by_id = {m["tbl_id"]: m for m in g["members"]}
    if set(want) <= set(by_id[tbl_id]["years"]):
        return None                              # 이 표 하나로 다 있음
    order = [by_id[tbl_id]] + [m for m in reversed(g["members"]) if m["tbl_id"] != tbl_id]  # 검색된 표 → 최신 표부터
    pick = {}
    for y in want:
        m = next((m for m in order if y in m["years"]), None)
        if m:
            pick.setdefault(m["tbl_id"], []).append(y)
    if set(pick) <= {tbl_id}:
        return None                              # 다른 표로 더 채울 연도가 없음
    tables = [{"tbl_id": t, "title": by_id[t]["title"], "years": ys} for t, ys in sorted(pick.items(), key=lambda kv: kv[1][0])]
    have = sorted(y for ys in pick.values() for y in ys)
    cycles = {c for t in pick for c in by_id[t]["cycle"]}
    return {"group": g["group"], "tables": tables, "years_have": have,
            "years_missing": [y for y in want if y not in have], "mixed_cycle": len(cycles) > 1}


def summary(groups):
    uniq = {id(g): g for g in groups.values()}
    return {"n_groups": len(uniq), "n_tables": len(groups), "n_linked": sum(bool(g.get("links")) for g in uniq.values())}


def save_csv(groups, path):
    """사람이 보는 용 (엑셀에서 한글 안 깨지게 utf-8-sig). 표 한 줄씩, 묶음 안은 오래된 표부터"""
    uniq = sorted({id(g): g for g in groups.values()}.values(), key=lambda g: g["group"])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["묶음", "조사명", "묶음 제목(연도 지움)", "표 수", "표 ID", "원래 제목", "시작 연도", "끝 연도", "연도 수", "주기"])
        for g in uniq:
            for m in g["members"]:
                ys = m["years"]
                w.writerow([g["group"], g["survey"], g["key"], len(g["members"]), m["tbl_id"], m["title"],
                            ys[0] if ys else "", ys[-1] if ys else "", len(ys), "·".join(m["cycle"])])
    return path


def main(argv=None):
    import argparse
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.rag.search.period_groups")
    ap.add_argument("--csv", default=None, help="묶음을 사람이 볼 CSV 로 (기본 storage/indices/period_groups.csv)")
    a = ap.parse_args(argv)
    from backend.core.config import STORAGE_DIR
    from backend.rag.search.facets import build_facets
    from backend.rag.search.index import table_corpus
    groups = build_groups(build_facets(table_corpus().docs()))
    out = save_csv(groups, a.csv or STORAGE_DIR / "indices" / "period_groups.csv")
    print(summary(groups), "→", out)


if __name__ == "__main__":
    main()
