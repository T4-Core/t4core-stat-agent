"""
[NEW 11-17] 기간 이어붙이기 — 같은 통계가 연도별로 나뉜 표들을 한 묶음으로

묶는 기준 (모두 만족)
  · 조사명이 같음
  · 원래 제목에서 연도 표기 '(2007~2015)' '(~2007)' '(2008~)' '(2006)' '(2011년~)' 와 '(신)' '(구)' 를 지우고
    띄어쓰기를 없앤 제목이 같음
  · [NEW 11-18] 해마다 바뀐 표기도 무시: / , · - – 및 의 , 끝의 '수'  (88 → 101묶음, 모두 인구총조사·연도 겹침 0 확인)
  예) 시도/직업별(~2007) 혼인 + 시도/직업별(2008~) 혼인
      성별 외국인-시군구 (2010) + 성별 외국인 - 시군구 (2015~2025)
      시도별 외국인주민 현황(2006) + (2007~2015) + 시도별 외국인주민 현황 (2015~2024)
      연령/성별 인구-읍면동 (2005) + 연령 및 성별 인구 - 읍면동 (2010) + 연령 및 성별 인구 – 읍면동 (2015~2025)
  못 잡는 것: 이름 자체가 바뀐 경우 (국제결혼 이주자 ↔ 결혼이민자)

이어붙이기 (stitch_plan)
  요청 연도마다 그 연도를 담은 표를 고름 — 지금 검색된 표를 먼저, 없으면 같은 묶음에서 최신 표
  → [{tbl_id, years}] + 끝내 없는 연도. 주기(년·월 등)가 다르면 표시

  python -m table_card_search.period_groups            묶음 파일 만들기 + 요약
  from table_card_search.period_groups import load_groups, stitch_plan
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
CARD_DIR = PACKAGE.parent / "table_card_expend" / "out" / "full"
OUT = CARD_DIR / "period_groups.json"

_YEAR_PAREN = re.compile(r"\(\s*~?\s*\d{4}\s*년?\s*(~\s*(\d{4}\s*년?)?)?\s*\)")
_OLD_NEW = re.compile(r"\((신|구)\)")


_MARKS = re.compile(r"[/,·\-–—]|및|의")             # [NEW 11-18] 해마다 바뀐 표기 (성/연령 ↔ 성 및 연령, - ↔ –, 거처의종류 ↔ 거처종류)
_SU_END = re.compile(r"수(?=$|\(|-)")                # [NEW 11-18] 끝의 '수' (외국인수 ↔ 외국인, 부인수 ↔ 부인)


def title_key(title):
    """원래 제목 → 연도 표기·표기 차이를 지운 비교용 제목"""
    t = _YEAR_PAREN.sub("", title or "")
    t = _OLD_NEW.sub("", t)
    t = re.sub(r"\s+", "", t)
    t = _SU_END.sub("", t)                           # '-' 를 지우기 전에 ('외국인수-시도')
    return _MARKS.sub("", t)


def build(card_dir=CARD_DIR):
    cards = [json.loads(x) for x in (card_dir / "cards.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    years, cycles = {}, {}
    for line in (card_dir / "conditions.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            ps = c.get("시점") or []
            years[c["tbl_id"]] = sorted({y for p in ps for y in (p.get("연도") or range(p["시작"], p["끝"] + 1))})
            cycles[c["tbl_id"]] = sorted({p.get("주기", "") for p in ps})
    g = defaultdict(list)
    for c in cards:
        g[(c["조사명"], title_key(c["제목_원래"]))].append(c)
    groups = []
    for (survey, key), cs in g.items():
        if len(cs) < 2:
            continue
        members = sorted(({"tbl_id": c["tbl_id"], "title": c["제목_원래"], "years": years.get(c["tbl_id"], []),
                           "cycle": cycles.get(c["tbl_id"], [])} for c in cs),
                         key=lambda m: (m["years"][-1] if m["years"] else 0, m["years"][0] if m["years"] else 0))
        groups.append({"group": f"G{len(groups) + 1:03d}", "survey": survey, "key": key, "members": members})
    return groups


def save(groups, path=OUT):
    path.write_text(json.dumps(groups, ensure_ascii=False, indent=1), encoding="utf-8")


def save_csv(groups, path=OUT.with_suffix(".csv")):
    """사람이 보는 용 (엑셀에서 한글 안 깨지게 utf-8-sig). 표 한 줄씩, 묶음 안은 오래된 표부터"""
    import csv
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["묶음", "조사명", "묶음 제목(연도 지움)", "표 수", "표 ID", "원래 제목", "시작 연도", "끝 연도", "연도 수",
                    "주기", "연도 목록"])
        for g in groups:
            for m in g["members"]:
                ys = m["years"]
                w.writerow([g["group"], g["survey"], g["key"], len(g["members"]), m["tbl_id"], m["title"],
                            ys[0] if ys else "", ys[-1] if ys else "", len(ys), "·".join(m["cycle"]),
                            " ".join(map(str, ys))])
    return path


_cache = {}


def load_groups(path=OUT):
    """→ {tbl_id: 묶음}. 파일이 없으면 만들어 저장"""
    if path not in _cache:
        if not path.exists():
            save(build())
        groups = json.loads(path.read_text(encoding="utf-8"))
        _cache[path] = {m["tbl_id"]: g for g in groups for m in g["members"]}
    return _cache[path]


def stitch_plan(tbl_id, want, groups=None):
    """검색된 표 + 요청 연도 → 이어붙이기 계획. 묶음이 없거나 이 표만으로 충분하면 None
    {"group", "tables": [{"tbl_id", "title", "years"}], "years_have", "years_missing", "mixed_cycle"}"""
    groups = groups if groups is not None else load_groups()
    g = groups.get(tbl_id)
    want = sorted({y for y in want or [] if isinstance(y, int)})
    if not g or not want:
        return None
    by_id = {m["tbl_id"]: m for m in g["members"]}
    if set(want) <= set(by_id[tbl_id]["years"]):
        return None                                           # 이 표 하나로 다 있음
    # 우선순위: 검색된 표 → 같은 묶음의 최신 표부터
    order = [by_id[tbl_id]] + [m for m in reversed(g["members"]) if m["tbl_id"] != tbl_id]
    pick = {}
    for y in want:
        m = next((m for m in order if y in m["years"]), None)
        if m:
            pick.setdefault(m["tbl_id"], []).append(y)
    if set(pick) == {tbl_id}:
        return None                                           # 다른 표로 더 채울 연도가 없음
    tables = [{"tbl_id": t, "title": by_id[t]["title"], "years": ys}
              for t, ys in sorted(pick.items(), key=lambda kv: kv[1][0])]
    have = sorted(y for ys in pick.values() for y in ys)
    cycles = {c for t in pick for c in by_id[t]["cycle"]}
    return {"group": g["group"], "tables": tables, "years_have": have,
            "years_missing": [y for y in want if y not in have], "mixed_cycle": len(cycles) > 1}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    groups = build()
    save(groups)
    csv_path = save_csv(groups)
    n = sum(len(g["members"]) for g in groups)
    print(f"묶음 {len(groups)}개 · 표 {n}개 → {OUT}\n표로 보기 → {csv_path}")
    mixed = [g for g in groups if len({c for m in g["members"] for c in m["cycle"]}) > 1]
    print(f"주기가 섞인 묶음 {len(mixed)}개: {[g['key'] for g in mixed][:5]}")


if __name__ == "__main__":
    main()
