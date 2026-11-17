"""형제 표 해소 — 같은 조사·같은 통계의 (계)/(남)/(여) 분할 · 연도판 · 전국/시도/시군구판 가운데
질문의 좌표(성별 · 지역 수준 · 연도)에 맞는 표 하나를 고른다

왜   1위 실패의 절반 이상이 형제 표다. 형제는 제목·설명이 거의 같아 BM25·dense·LLM 점수가 구분하지 못한다
     ('거제시 한국 국적을 가지지 않은 자의 인구 수' → (계) 가 답인데 (여) 가 1위). 이 선택은 점수보다 좌표 규칙이 정확하다
어떻게
  1) 묶기 (색인 때 한 번)   같은 조사명 + 제목에서 성별 괄호·연도 괄호·지역 수준 꼬리를 뗀 이름이 같으면 한 무리
       '한국국적을 가지지 않은 자-유학생(계)' · '…(남)' · '…(여)'      → 한 무리
       '한국국적을 취득한 자-기타(계)(2007~2015)' · '…(계)'             → 한 무리 (연도판)
       '가구주의 성/연령별 추계가구-전국' · '…-시도'                     → 한 무리 (지역 수준판)
  2) 고르기 (질문마다)      상위 후보에 든 무리마다, 그 무리의 표 전부(상위 밖 형제 포함)에 좌표 점수를 매겨
                            무리가 차지한 자리 중 가장 앞 자리에 점수가 가장 높은 표를 둔다 (무리 사이의 순서는 그대로)
       성별      질문에 남·여가 없으면 (계)·분할 없는 표 / '남성' 이면 (남) / '남녀·성별' 이면 성별 분류가 있는 (계)
       지역 수준 시군구 이름 → 그 이름이 있는 표 / 시도 → 시도판 / 지역이 없으면 전국판
       연도      요청 연도를 담은 비율. 연도가 없으면 최신 자료가 있는 판
       간결      분류가 적은 표를 조금 앞에
  LLM 재정렬 뒤에 한 번 더 적용한다 (LLM 은 무리 사이의 순서를, 이 규칙은 무리 안의 선택을 맡음)
"""
from __future__ import annotations

import re

from backend.rag.search.text import norm

SEX_PAREN = re.compile(r"\((계|남|여|남자|여자|전체|합계|총계)\)")
YEAR_PAREN = re.compile(r"\(\s*~?\s*(?:19|20)\d{2}\s*년?\s*(?:~\s*(?:(?:19|20)\d{2})?\s*년?)?\s*\)|\(\s*~\s*(?:19|20)\d{2}\s*\)")
LEVEL_TAIL = re.compile(r"\s*[-–—]\s*(전국|시도|시군구|읍면동)(?:\s*\(.*)?(?:,.*)?$")
LEVELS = ("전국", "시도", "시군구", "읍면동")
Q_MALE = re.compile(r"남자|남성|남아|남학생|남자아이|(?<![가-힣])남(?=\s|$|\)|의|은|는|이)")
Q_FEMALE = re.compile(r"여자|여성|여아|여학생|여자아이|(?<![가-힣])여(?=\s|$|\)|의|은|는|이)")
Q_BOTH = re.compile(r"남녀|성별|남자와\s*여자|남성과\s*여성|남녀별")


def core_title(nm: str) -> str:
    t = SEX_PAREN.sub("", str(nm or ""))
    t = YEAR_PAREN.sub("", t)
    t = LEVEL_TAIL.sub("", t)
    return norm(t)


def table_sex(nm: str):
    m = SEX_PAREN.search(str(nm or ""))
    if not m:
        return None
    g = m.group(1)
    return "남" if g.startswith("남") else "여" if g.startswith("여") else "계"


def table_level(f) -> str:
    m = LEVEL_TAIL.search(f.tbl_nm or "")
    if m:
        return m.group(1)
    for lv in ("읍면동", "시군구", "시도"):
        if lv in f.geo:
            return lv
    return "전국"


def build_groups(facets: dict, max_size=12) -> tuple[dict, dict]:
    """→ ({tbl_id: 무리 키}, {무리 키: [tbl_id…]}) 두 개 이상인 무리만"""
    by = {}
    for tid, f in facets.items():
        c = core_title(f.tbl_nm)
        if len(c) < 3:
            continue
        by.setdefault((norm(f.survey_nm), c), []).append(tid)
    groups = {f"{k[0]}|{k[1]}": sorted(v) for k, v in by.items() if 2 <= len(v) <= max_size}
    of = {t: g for g, ts in groups.items() for t in ts}
    return of, groups


def question_sex(question: str, filters=None):
    q = str(question or "")
    want = [str(x) for x in (filters or {}).get("성별") or []]
    if Q_BOTH.search(q):
        return "both"
    m, w = bool(Q_MALE.search(q)) or "남자" in want, bool(Q_FEMALE.search(q)) or "여자" in want
    return "both" if m and w else "남" if m else "여" if w else None


def question_level(qv) -> str | None:
    from backend.rag.search.facets import URBAN
    subs = [x for x in qv.subs if x not in URBAN]
    if subs:
        return "읍면동" if any(re.search(r"(읍|면|동|리)$", x) for x in subs) else "시군구"
    if qv.subs:  # 동부·읍부만 → 수준을 정하지 않음
        return None
    if qv.axis in LEVELS:
        return qv.axis
    if qv.sido:
        return "시도"
    if qv.axis == "지역":
        return None
    return "전국"


def score(f, qv, q_sex, q_level, newest=None) -> tuple[float, list]:
    """형제 사이 좌표 점수 (클수록 질문에 맞음) → (점수, 이유)"""
    s, why = 0.0, []
    ts = table_sex(f.tbl_nm)
    if q_sex in ("남", "여"):
        if ts == q_sex:
            s += 2.0
            why.append(f"성별 {q_sex}")
        elif ts in ("남", "여"):
            s -= 3.0
        elif f.has_sex:
            s += 0.8
    elif q_sex == "both":
        s += 1.0 if ts in ("계", None) and f.has_sex else (-1.5 if ts in ("남", "여") else 0.0)
    else:
        if ts in ("계", None):
            s += 1.5
            why.append("성별 계")
        else:
            s -= 1.5
    tl = table_level(f)
    rank = {lv: i for i, lv in enumerate(LEVELS)}
    if q_level == "전국":
        s += 1.0 if tl == "전국" else 0.0
    elif q_level == "시도":
        s += 1.0 if tl == "시도" else (-2.0 if tl == "전국" else 0.3)
    elif q_level in ("시군구", "읍면동"):
        named = [x for x in qv.subs if x not in ("동부", "읍부", "면부", "시부", "군부", "읍면부")]
        if named and all(x in f.regions for x in named):
            s += 2.0
            why.append("지역 이름 있음")
        elif rank.get(tl, 0) >= rank[q_level]:
            s += 0.8
        else:
            s -= 2.0
    if q_level and tl == q_level:
        why.append(f"수준 {tl}")
    if qv.years:
        c = f.year_cover(qv.years)
        s += 2.0 * c - (2.0 if c == 0 else 0.0)
        if c:
            why.append(f"연도 {round(c, 2)}")
    elif newest is not None and f.last_year() == newest:
        s += 0.5
        why.append("최신판")
    s -= 0.05 * len(f.dims)
    return s, why


class SiblingResolver:
    def __init__(self, facets: dict, margin=0.75, max_outside=3):
        self.facets = facets
        self.of, self.groups = build_groups(facets)
        self.margin, self.max_outside = margin, max_outside

    def info(self):
        return {"groups": len(self.groups), "tables": len(self.of)}

    def siblings(self, tid):
        g = self.of.get(tid)
        return [t for t in self.groups.get(g, []) if t != tid] if g else []

    def resolve(self, ids: list, qv, question: str, filters=None, window=12, allowed=None):
        """ids = 순위대로의 tbl_id. → (새 순서, {tbl_id: 메모}). allowed: 상위 밖 형제를 넣어도 되는 표 (계수가 0 이 아닌 표)"""
        q_sex, q_level = question_sex(question, filters), question_level(qv)
        head, tail = list(ids[:window]), list(ids[window:])
        notes, done = {}, set()
        for tid in list(head):
            g = self.of.get(tid)
            if not g or g in done:
                continue
            done.add(g)
            members = self.groups[g]
            newest = max((self.facets[t].last_year() or 0) for t in members)
            sc = {t: score(self.facets[t], qv, q_sex, q_level, newest) for t in members}
            inside = [t for t in head if t in sc]
            outside = sorted((t for t in members if t not in head and (allowed is None or t in allowed)),
                             key=lambda t: -sc[t][0])[:self.max_outside]
            ranked = sorted(inside + outside, key=lambda t: (-sc[t][0], inside.index(t) if t in inside else 99))
            best = ranked[0]
            if best == inside[0] or sc[best][0] - sc[inside[0]][0] < self.margin:
                continue
            seq = [best] + [t for t in ranked[1:] if t in inside]
            pos = [i for i, t in enumerate(head) if t in sc]
            if best not in inside:
                tail = [t for t in tail if t != best]
                pos = pos + [pos[-1] + 0.5]
            new = {p: t for p, t in zip(pos, seq)}
            rest = [(i, t) for i, t in enumerate(head) if t not in sc]
            head = [t for _, t in sorted(rest + list(new.items()), key=lambda x: x[0])]
            notes[best] = {"from": inside[0], "why": sc[best][1], "score": round(sc[best][0], 2),
                           "was": round(sc[inside[0]][0], 2)}
        return head + [t for t in tail if t not in head], notes
