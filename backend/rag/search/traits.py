"""
표 구분 줄 — LLM 재정렬 카드에 '후보끼리 다른 점' 을 붙인다 (search.yaml llm_rerank.traits)

왜   남은 1위 실패는 대부분 2~5위의 '비슷한 표' 다 (11/24 hard·easy 분석):
       총괄표 ↔ 상세표 (인구동향 총괄 DT_1B8000G ↔ 시도별 출생 DT_1B80A03)
       비율을 직접 주는 표 ↔ 건수 표 (이동률 DT_1B26006 ↔ 이동자수)
       같은 말 다른 집계 기준 ('외국인 수': 주민등록 · 지자체 외국인주민현황 · 인구총조사)
       (계)/(남)/(여) 형제 · 연도판 형제
     표 이름·항목만 나열하면 LLM 이 그 차이를 스스로 찾아야 한다. 그래서 구분에 쓰이는 성질을 꺼내 '구분:' 한 줄로 준다
무엇  표 메타데이터(facets)에서 — 골든셋을 보지 않으므로 dev·heldout 모두에서 평가해도 됨
       총괄표          제목이 '(출생,사망,혼인,이혼)' 처럼 여러 통계를 묶거나 '총괄'
       비율 직접 제공  항목·단위에 률·율·비율·% (예: 이동률, 합계출산율)
       성별            (계)/(남)/(여) 분할 표 · 성별 분류 있음 · 성별 없음
       연령            연령 분류 있음 · 없음
       주기            월·분기·반기·연
       집계 기준       OKF 빌드의 표 정의(KOSIS 주석). 표에 없으면 같은 조사의 다른 표 2개 이상이 공유하는 정의('조사 공통')
     후보 모두가 같은 값인 성질은 빼고 다른 것만 보인다 (모두 '연간' 이면 주기를 안 씀) — 카드가 길어지지 않게
형제 차이  같은 형제 무리(siblings.py)가 후보에 둘 이상이면 제목에서 그 표에만 있는 말 ('여', '2007~2015')
"""
from __future__ import annotations

import re
import threading
from collections import Counter

RATE = re.compile(r"률|율|비율|%|퍼센트|구성비|지수")
SUMMARY = re.compile(r"총괄|\([^()]*,[^()]*,[^()]*\)")
CYCLE_NM = {"M": "월", "Q": "분기", "H": "반기", "Y": "연"}
_lock, _survey_cache = threading.Lock(), {}


def _rates(f):
    names = [str(x) for x in f.items] + [str(u) for u in (f.units or [])]
    hit = [n for n in dict.fromkeys(names) if RATE.search(n)]
    return hit[:3]


def basic(f) -> dict:
    """표 하나 → {성질: 글} (후보끼리 비교 전)"""
    from backend.rag.search.siblings import table_sex
    out = {}
    out["유형"] = "총괄표(여러 통계를 한 표에)" if SUMMARY.search(f.tbl_nm or "") else "단일 통계 표"
    r = _rates(f)
    out["비율"] = f"비율 직접 제공({', '.join(r)})" if r else "건수·인원 표(비율 없음)"
    sx = table_sex(f.tbl_nm)
    out["성별"] = f"성별 분할 표({sx})" if sx else "성별 분류 있음" if f.has_sex else "성별 구분 없음"
    out["연령"] = "연령 분류 있음" if f.has_age else "연령 구분 없음"
    if f.cycles:
        out["주기"] = "·".join(CYCLE_NM.get(c, c) for c in sorted(f.cycles, key="MQHY".find)) + " 자료"
    return out


def survey_definitions(cat) -> dict:
    """OKF 빌드 → {조사 이름: [그 조사의 표 2개 이상이 공유하는 정의 줄]} (빌드마다 한 번)"""
    key = getattr(cat, "hash", None)
    with _lock:
        if key in _survey_cache:
            return _survey_cache[key]
    by = {}
    for t in (cat._j("catalog.json") or {}).values():
        for d in t.get("definitions") or []:
            by.setdefault(str(t.get("survey") or ""), Counter())[d] += 1
    out = {s: [d for d, n in c.most_common(2) if n >= 2] for s, c in by.items() if s}
    with _lock:
        _survey_cache.clear()
        _survey_cache[key] = out
    return out


def definitions(tbl_ids, facets, settings=None, own=True) -> dict:
    """{tbl_id: '집계 기준: …' | '집계 기준(조사 공통): …'} — OKF 빌드가 없으면 {}
    own=False: 표 자신의 정의는 빼고 조사 공통만 (llm_rerank.okf 가 '정의:' 줄로 이미 붙일 때)"""
    try:
        from backend.core.settings import get_settings
        from backend.rag.okf.catalog import Catalog
        cat = Catalog.current(settings or get_settings())
    except Exception:  # noqa: BLE001  (보조 정보 — OKF 가 없어도 계속)
        return {}
    if cat is None:
        return {}
    sv = survey_definitions(cat)
    out = {}
    for t in tbl_ids:
        c = cat.table(t) or {}
        mine = c.get("definitions") or []
        if mine:
            if own:
                out[t] = "집계 기준: " + mine[0][:150]
            continue
        f = facets.get(t)
        common = sv.get(str(c.get("survey") or (f.survey_nm if f else "")))
        if common:
            out[t] = "집계 기준(조사 공통): " + common[0][:150]
    return out


def _tokens(nm):
    return re.findall(r"[가-힣A-Za-z0-9~·]+", str(nm or ""))


def sibling_diffs(head, facets, sib_of) -> dict:
    """후보 중 같은 형제 무리끼리 제목에서 그 표에만 있는 말 → {tbl_id: "이 표만 '여'"} (무리 안 공통 말은 뺌)"""
    groups = {}
    for h in head:
        g = (sib_of or {}).get(h["tbl_id"])
        if g:
            groups.setdefault(g, []).append(h["tbl_id"])
    out = {}
    for ts in groups.values():
        toks = {t: _tokens(facets[t].tbl_nm) for t in ts}
        common = set.intersection(*(set(v) for v in toks.values()))
        for t in ts:
            only = [w for w in dict.fromkeys(toks[t]) if w not in common]
            out[t] = ("이 표만 " + ", ".join(f"'{w}'" for w in only[:4])) if only else "무리에서 가장 일반적인 이름"
    return out


def traits_lines(head, facets, sib_of=None, settings=None, own_defs=True) -> dict:
    """후보 → {tbl_id: ['구분: …', '형제 차이: …', '집계 기준…']} — 후보 모두가 같은 성질은 뺌"""
    ids = [h["tbl_id"] for h in head if h["tbl_id"] in facets]
    if len(ids) < 2:
        return {}
    b = {t: basic(facets[t]) for t in ids}
    keys = [k for k in ("유형", "비율", "성별", "연령", "주기") if len({b[t].get(k) for t in ids}) > 1]
    sd = sibling_diffs(head, facets, sib_of)
    dd = definitions(ids, facets, settings, own=own_defs)
    out = {}
    for t in ids:
        lines = []
        parts = [b[t][k] for k in keys if b[t].get(k)]
        if parts:
            lines.append("구분: " + " · ".join(parts))
        if t in sd:
            lines.append("형제 차이: " + sd[t])
        if t in dd:
            lines.append(dd[t])
        if lines:
            out[t] = lines
    return out
