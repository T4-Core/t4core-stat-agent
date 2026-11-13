"""
[3] 조립 — 카드 재료 + 설명 → 검색 카드(cards.jsonl) + 보고서

검색 글을 두 개로 나눔 (table_card 와 같은 구분, 들어가는 재료가 다름)
  bm25_text   표 고유 단어: 조사명 · 제목(2번) · 주제(메뉴 경로) · 대상 · 지표 · 이동 · 축(표준·원래) · 항목 · 작은 축 값
              · 모집단 · 지역 수준 단어 · 두 번째 지역 역할 · 용어 정의의 용어
              (지역 이름·연도는 넣지 않음 — 조건표가 맡음. 지역 수준 단어는 모든 표에 같은 규칙으로 넣어 치우침 없음)
  dense_text  '조사명 | 제목' + 설명 + 볼 수 있는 것(관점) + 조사 목적 한 줄
보고서: 숫자 요약 + (있으면) 같은 표의 table_card 결과와 비교 (table_card 파일은 읽기만)
"""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

from table_card_expend import rules as R

REPO_ROOT = Path(__file__).resolve().parents[1]
TABLE_CARD_DIRS = {"full": REPO_ROOT / "table_cards" / "full", "sample": REPO_ROOT / "table_cards" / "sample_cards"}
SMALL_AXIS = 40


def bm25_text(p, c):
    axis_vals = [v for a in p["축"] if a["kind"] not in ("ages", "cohort", "regions_like") and a["값_수"] <= SMALL_AXIS
                 for v in a["값"]]
    axis_names = [x for a in p["축"] for x in dict.fromkeys([a["표준"], a["원래"]]) if x]
    rest = [*p["주제"], *p["대상"], *p["지표"], *p["이동"], *axis_names, *p["항목"][:60], *axis_vals, *p["모집단"],
            *[x for x in p["지역수준"] if x != "전국"],
            *([c["지역2"]["역할"]] if c.get("지역2") and c["지역2"].get("역할") else []),
            *[d["용어"] for d in p["정의"]]]
    rest = [w for w in dict.fromkeys(rest) if w and not R.SIDO_RE.search(str(w))]
    # 조사명은 그대로 (세종시 특별센서스 등), 제목은 두 번 (항목이 많은 표에서 제목 단어가 묻히지 않게)
    return " ".join([p["조사명"] or "", p["제목"], p["제목"], *rest]).strip()


def dense_text(p, d):
    lines = [f"{p['조사명']} | {p['제목']}", d["설명"]]
    if p["관점"]:
        lines.append("볼 수 있는 것: " + ", ".join(p["관점"][:6]))
    purp = (p.get("조사설명") or {}).get("조사목적")
    if purp:
        lines.append("조사 목적: " + purp[:120])
    return "\n".join(x for x in lines if x)[:1200]


def run(P, C, D, out_dir, set_name, log=print, table_card_dir=None):
    cards = []
    for tid, p in P.items():
        c, d = C[tid], D[tid]
        card = {"tbl_id": tid, "set": set_name, "조사명": p["조사명"], "제목": p["제목"], "제목_원래": p["제목_원래"],
                "대상": p["대상"], "지표": p["지표"], "축": [a["표준"] or a["원래"] for a in p["축"]],
                "지역수준": p["지역수준"], "모집단": p["모집단"], "관점": p["관점"],
                "설명": d["설명"], "설명_출처": d["설명_출처"], "조사구분": c.get("조사구분"),
                "bm25_text": bm25_text(p, c), "dense_text": dense_text(p, d), "검사": d.get("검사", [])}
        card["재료_해시"] = hashlib.sha1(json.dumps([p, d.get("재료_해시")], ensure_ascii=False, sort_keys=True,
                                                 default=str).encode()).hexdigest()[:16]
        cards.append(card)
    with (out_dir / "cards.jsonl").open("w", encoding="utf-8") as f:
        for k in cards:
            f.write(json.dumps(k, ensure_ascii=False) + "\n")
    report = summary(cards, P, C) + compare_table_card(P, C, set_name, table_card_dir)
    (out_dir / "report.txt").write_text("\n".join(report), encoding="utf-8")
    log("\n".join(report))
    return cards


def summary(cards, P, C):
    n = len(cards) or 1
    src = collections.Counter(k["설명_출처"] for k in cards)
    leak = [k["tbl_id"] for k in cards if R.SIDO_RE.search(k["bm25_text"])]
    return [f"카드 {len(cards)}개",
            f"설명 출처: {dict(src)}",
            f"검사 걸린 카드: {sum(bool(k['검사']) for k in cards)}",
            f"bm25_text 평균 {sum(len(k['bm25_text']) for k in cards) / n:.0f}자 · "
            f"dense_text 평균 {sum(len(k['dense_text']) for k in cards) / n:.0f}자",
            f"bm25_text 에 지역 이름 남은 카드: {len(leak)} {leak[:5]}"]


def _load(path):
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["tbl_id"]] = r
    return out


def compare_table_card(P, C, set_name, table_card_dir=None):
    """같은 표의 table_card 결과와 차이 (table_card 파일이 있을 때만)"""
    d = Path(table_card_dir) if table_card_dir else TABLE_CARD_DIRS.get(set_name)
    tk, tc = _load(d / "cards.jsonl"), _load(d / "conditions.jsonl")
    common = [t for t in P if t in tk and "오류" not in tk[t]]
    if not common:
        return ["", f"[table_card 비교] {d} 에 같은 표 카드 없음 — 건너뜀"]
    added, removed = collections.Counter(), collections.Counter()
    ex_rm = collections.defaultdict(list)
    no_period_tc = no_period_ex = nat_only_tc = nat_only_ex = 0
    for t in common:
        a, b = set(tk[t].get("지표") or []), set(P[t]["지표"])
        for x in b - a:
            added[x] += 1
        for x in a - b:
            removed[x] += 1
            if len(ex_rm[x]) < 3:
                ex_rm[x].append(f"{t}({P[t]['제목'][:20]})")
        if t in tc:
            no_period_tc += not tc[t].get("시점")
            nat_only_tc += tc[t].get("지역") == ["전국"]
        no_period_ex += not C[t]["시점"]
        nat_only_ex += C[t]["지역"] == ["전국"]
    lines = ["", f"[table_card 비교] 같은 표 {len(common)}개 ({d})",
             f"  시점 없는 표       table_card {no_period_tc} → expend {no_period_ex}",
             f"  지역이 '전국'뿐인 표 table_card {nat_only_tc} → expend {nat_only_ex}",
             "  지표 빠짐(table_card 에만): " + ", ".join(f"{k} {v}" for k, v in removed.most_common(8)),
             "  지표 더함(expend 에만): " + ", ".join(f"{k} {v}" for k, v in added.most_common(8))]
    for k, v in removed.most_common(4):
        lines.append(f"    빠진 {k} 예: {', '.join(ex_rm[k])}")
    return lines
