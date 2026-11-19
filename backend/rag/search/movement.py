"""인구 이동의 방향·범위 — 질문이 묻는 이동과 표가 담는 이동이 맞는가 (가능성 계수)

왜   '다른 시도로 이사 간'·'시도 간 전입' 을 물어도 이 조건이 검색 문장에만 들어가고 표 구조로는 확인되지 않아,
     '시군구별 이동자수' 같은 일반 이동 표가 '시도간' 항목이 있는 표보다 앞에 왔다 (쿼리 모듈 notes:
     "[이동] … View 모듈에 아직 없는 슬롯").

  질문 (원문 규칙)
    범위   시도간   '시도 간'·'다른 시도'·'타 시도'
           시군구간 '시군구 간'·'다른 시군구'
    방향   전입     '전입'(전입지 제외)·'이사 온'·'들어온'·'유입'      전출 '전출'·'이사 간'·'떠난'·'빠져나간'·'유출'
           순이동   '순이동'·'순유입'·'순유출'
    국제   '입국'·'출국'·'국제 이동'·'해외로'

  표 (이름·항목·분류 이름·분류 값)
    시도간·시군구간·전입·전출·순이동·입국·출국 이 글자로 있는가,
    전출지 × 전입지 분류가 함께 있는가 (행렬 — 시도간·방향을 계산으로 얻을 수 있음)

  계수 (이동 표에만; 이동 표가 아니면 1)
    범위를 물었는데 그 범위가 없음                → move_miss   (행렬 표면 move_derived)
    국제 이동을 물었는데 국내 표 / 그 반대        → move_miss
    방향을 물었는데 그 방향이 없음 (지역을 말했을 때만 — 전국 합계는 전입 = 전출)  → move_miss (행렬 표면 move_derived)
  여러 개가 걸려도 한 번만 곱함 (가장 작은 값)
"""
from __future__ import annotations

import re

from backend.rag.search.text import norm

SCOPE_RE = {
    "시도간": re.compile(r"시\s*[·ㆍ]?\s*도\s*간|(?:다른|타)\s*시\s*[·ㆍ]?\s*도|시도\s*밖"),
    "시군구간": re.compile(r"시\s*[·ㆍ]?\s*군\s*[·ㆍ]?\s*구\s*간|(?:다른|타)\s*시\s*[·ㆍ]?\s*군\s*[·ㆍ]?\s*구"),
}
DIR_RE = {
    "순이동": re.compile(r"순\s*이동|순\s*유입|순\s*유출"),
    "전입": re.compile(r"전입(?!지)|이사\s*(?:를\s*)?(?:온|와|오는|왔)|이주해\s*온|옮겨\s*(?:온|와)|들어온|유입"),
    "전출": re.compile(r"전출(?!지)|이사\s*(?:를\s*)?(?:간|가는|갔)|옮겨\s*(?:간|갔)|떠난|떠나간|빠져\s*나간|유출"),
}
INTL_RE = re.compile(r"입국|출국|국제\s*(?:인구\s*)?이동|국제\s*순이동|해외로|외국으로\s*(?:나간|떠난)")
MOVE_Q_RE = re.compile(r"이동|이사|전입|전출|유입|유출|옮기|옮긴|옮겨|떠나|떠난|들어온|빠져\s*나|이주|입국|출국")
MOVE_T_RE = re.compile(r"이동|전입|전출|입국|출국")


def question_move(text) -> dict | None:
    """질문 → {"scope": 시도간|시군구간|None, "dir": 전입|전출|순이동|None, "intl": bool} · 이동 질문이 아니면 None"""
    q = str(text or "")
    if not MOVE_Q_RE.search(q):
        return None
    scope = next((k for k, r in SCOPE_RE.items() if r.search(q)), None)
    d = next((k for k, r in DIR_RE.items() if r.search(q)), None)
    intl = bool(INTL_RE.search(q))
    if not (scope or d or intl):
        return None
    return {"scope": scope, "dir": d, "intl": intl}


def table_move(f) -> dict:
    """표 단면 → {"move": 이동 표인가, "codes": {시도간, 시군구간, 전입, 전출, 순이동, 국제}, "od": 전출지×전입지 행렬인가}"""
    names = [f.tbl_nm, *f.items]
    objs = [obj for obj, _, _ in f.dims]
    vals = [n for _, _, ns in f.dims for n in ns[:300]]
    head = norm(" ".join(names))
    blob = norm(" ".join(names + objs + vals))
    move = bool(MOVE_T_RE.search(head)) or any(MOVE_T_RE.search(str(o)) for o in objs)
    codes = {k for k in ("시도간", "시군구간", "전입", "전출", "순이동") if k in blob}
    if re.search(r"입국|출국|국제이동|국제순이동", blob):
        codes.add("국제")
    od_text = norm(" ".join([f.tbl_nm, *objs]))
    od = "전출지" in od_text and "전입지" in od_text
    return {"move": move, "codes": codes, "od": od}


def move_factor(qm, tm, fz, regional=False):
    """질문 이동(question_move) × 표 이동(table_move) → (계수, 이유 또는 None)"""
    if not qm or not tm or not tm["move"]:
        return 1.0, None
    miss, derived = float(fz.get("move_miss", 0.6)), float(fz.get("move_derived", 0.9))
    if miss >= 1.0 and derived >= 1.0:
        return 1.0, None
    codes, od = tm["codes"], tm["od"]
    out, why = [], []
    domestic = bool(codes & {"시도간", "시군구간", "전입", "전출"}) or od
    if qm["intl"] and "국제" not in codes:
        out.append(miss)
        why.append("국제 이동 없음")
    elif not qm["intl"] and "국제" in codes and not domestic:
        out.append(miss)
        why.append("국내 이동 없음")
    if qm["scope"] and qm["scope"] not in codes:
        out.append(derived if (od and qm["scope"] == "시도간") else miss)
        why.append(f"{qm['scope']} {'계산' if od and qm['scope'] == '시도간' else '없음'}")
    if qm["dir"] and regional and qm["dir"] not in codes:
        out.append(derived if od else miss)
        why.append(f"{qm['dir']} {'계산' if od else '없음'}")
    if not out:
        return 1.0, None
    return min(out), "이동 " + "·".join(why)
