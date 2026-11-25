"""하위 질문 검증 — 재작성(HCX)이 낸 하위 질문 중 표를 가르지 못하는 것을 뺀다 (코드, HCX 호출 없음)

왜   단일 표 질문인데 하위 질문이 붙어 단위가 3~4개가 되는 경우가 많았다 (합성 셋 hard: 44문항).
     '2017년 전국 이동자수' + '2017년 전국 인구' 처럼 '본 질문 지표' + '분모 같은 일반 말' 로 나뉘면,
     일반 말 단위의 1위(가장 흔한 표)가 정답 표 바로 뒤에 끼어 Hit@3·MRR 을 깎는다.
     LLM 이 '수' 를 한자 '수(水)' 로 적어 '2025년 전국 수(水)' 같은 단위가 생기기도 했다.

  값 다듬기    '수(水)' → '수' (괄호 안이 한자뿐인 주석은 뗌)
  뜻 없는 값   한 글자('수') · 기호뿐 → 그 값만 뺌. 하위 질문의 대상·지표가 다 빠지면 그 하위 질문을 뺌
  일반 말 단위 대상·지표가 모두 일반 말('인구'·'가구'·'인구수'·'건수' …)인 하위 질문은,
               구체 지표를 가진 다른 하위 질문과 시점·지역·성별·연령이 같고(= 같은 자리의 분모처럼 보임)
               질문에 비율·나누기 신호(비율·비중·차지·천 명당·…로 나눈)가 없으면 뺌
               ('서울 출생아수와 부산 인구' 처럼 자리가 다르면 따로 묻는 것이라 남김)
               (비율 질문의 분모 단위는 roles.py 가 원문 규칙으로 따로 더함 — 역할 단위는 여기서 건드리지 않음)
  하나만 남음  남은 하위 질문이 하나이고 그 대상·지표가 본 질문에 다 들어 있으면 뺌 (본 질문과 같은 검색)
               단 역할 단위가 함께 있으면 남김 (roles.py 가 본 질의를 복사해 둔 단위 — 지우면 본 질의가 검색되지 않음)

  prune_sub_slots(question, main_slots, sub_slots) → (남길 하위 슬롯, 내역)     validate.validate_slots 에서
  prune_units(question, units)                    → (남길 검색 단위, 내역)     compare / tune 이 캐시된 분석에 다시 적용
"""
from __future__ import annotations

import re

from backend.rag.query_analyzer.measures import GENERIC_INDICATORS, squash

HANJA_NOTE = re.compile(r"\s*[(（]\s*[㐀-䶿一-鿿豈-﫿]+\s*[)）]")
GENERIC = set(GENERIC_INDICATORS) | {"수", "총수", "규모", "사람", "주민", "세대", "주택", "주택수", "총인구", "총인구수",
                                     "총가구", "총가구수", "전체인구", "인구 수", "가구 수"}
GENERIC_SQ = {squash(x) for x in GENERIC}
RATIO_RE = re.compile(r"비율|퍼센트|%|비중|차지|구성비|몇\s*할|(?:천|1,?000|만|10,?000|백|100)\s*(?:명|가구|호)\s*(?:당|을\s*기준|기준)|"
                      r"(?:으로|로)\s*나[눈누]|대비\s*(?:인구|가구)|1인당|인구당|가구당")


def clean_value(v):
    """'수(水)' → '수' · 앞뒤 공백 정리"""
    return HANJA_NOTE.sub("", str(v or "")).strip()


def clean_text(t):
    """검색 문장의 한자 주석을 떼고 같은 낱말이 이어 나오면 하나로 ('남편 수 수(水)' → '남편 수')"""
    toks = clean_value(t).split()
    out = []
    for x in toks:
        if not out or out[-1] != x:
            out.append(x)
    return " ".join(out)


def meaningless(v):
    """값으로 표를 가를 수 없음: 한 글자 이하 · 글자 없음"""
    s = squash(clean_value(v))
    return len(re.sub(r"[^0-9A-Za-z가-힣]", "", s)) <= 1


def is_generic_value(v):
    return squash(clean_value(v)) in GENERIC_SQ


def content(slots):
    """하위 질문(또는 단위 filters)의 대상·지표 값 (다듬은 것, 뜻 없는 값 뺌)"""
    out = []
    for k in ("대상", "지표"):
        for v in (slots or {}).get(k) or []:
            c = clean_value(v)
            if c and not meaningless(c):
                out.append(c)
    return list(dict.fromkeys(out))


FRAME_KEYS = ("시점", "지역", "전출지", "전입지", "성별", "연령")


def frame(slots):
    """하위 질문의 자리 (시점·지역·성별·연령) — 같으면 같은 자리를 다른 지표로 묻는 것"""
    return tuple(tuple(sorted(str(v) for v in ((slots or {}).get(k) or []))) for k in FRAME_KEYS)


def ratio_question(question):
    return bool(RATIO_RE.search(str(question or "")))


def _covered(vals, main_vals, main_text=""):
    """vals 가 모두 본 질문의 대상·지표(또는 본 질문 문장)에 들어 있는가 (띄어쓰기·괄호 무시, 서로 포함이면 같음)"""
    mv = [squash(x) for x in main_vals if squash(x)]
    mt = squash(main_text)
    for v in vals:
        s = squash(v)
        if not s:
            continue
        if not (any(s in m or m in s for m in mv) or (mt and s in mt)):
            return False
    return True


def _prune(question, main_vals, main_text, subs):
    """subs = [(이름, 값 목록, 역할 단위인가, 자리)] → (남길 이름 목록, 내역)"""
    log, kept = [], []
    for x in subs:
        name, vals, role = x[0], x[1], x[2]
        if not role and not vals:
            log.append(f"하위 질문 삭제(뜻 없는 대상·지표만): {name}")
        else:
            kept.append(x)
    specific = {x[3] for x in kept if not x[2] and any(not is_generic_value(v) for v in x[1])}
    if specific and not ratio_question(question):
        out = []
        for x in kept:
            if not x[2] and x[1] and all(is_generic_value(v) for v in x[1]) and x[3] in specific:
                log.append(f"하위 질문 삭제(일반 말뿐, 비율 질문 아님): {x[0]} {x[1]}")
                continue
            out.append(x)
        kept = out
    llm = [x for x in kept if not x[2]]
    # 역할 단위가 함께 남으면 지우지 않음 — roles.py 가 본 질의를 첫 하위 단위로 복사해 둔 것 (지우면 run_query 가 main 을 건너뛰어
    # 역할 단위만 검색됨). 앱 경로(prune_sub_slots)는 역할 단위를 더하기 전이라 해당 없음, 캐시에 다시 적용하는 prune_units 용
    if len(llm) == 1 and not any(x[2] for x in kept) and _covered(llm[0][1], main_vals, main_text):
        log.append(f"하위 질문 삭제(하나만 남았고 본 질문과 같음): {llm[0][0]} {llm[0][1]}")
        kept = [x for x in kept if x is not llm[0]]
    return [x[0] for x in kept], log


def prune_sub_slots(question, main_slots, sub_slots):
    """재작성 하위 슬롯 목록 → (남길 하위 슬롯, 내역). 남는 하위 질문의 대상·지표 값도 다듬음 ('수(水)' → 뺌)"""
    subs = [dict(s) for s in sub_slots or []]
    for s in subs:
        for k in ("대상", "지표"):
            if s.get(k):
                s[k] = [c for c in dict.fromkeys(clean_value(v) for v in s[k]) if c and not meaningless(c)]
    main_vals = content(main_slots)
    items = [(i, content(s), False, frame(s)) for i, s in enumerate(subs)]
    names, log = _prune(question, main_vals, "", items)
    return [subs[i] for i in names], log


def prune_units(question, units):
    """검색 단위 [{unit, text, search_query, filters, …}] → (남길 단위, 내역). 본 단위(main)는 늘 남기고 문장만 다듬음.
    역할 단위(filters.역할 = 분모·조건 — roles.py 의 원문 규칙)는 그대로"""
    units = [dict(u) for u in units or []]
    if not units:
        return units, []
    for u in units:
        for k in ("text", "search_query"):
            if u.get(k):
                u[k] = clean_text(u[k]) or u[k]
        f = u.get("filters")
        if isinstance(f, dict):
            f = dict(f)
            for k in ("대상", "지표"):
                if f.get(k):
                    f[k] = [c for c in dict.fromkeys(clean_value(v) for v in f[k]) if c and not meaningless(c)] or []
            u["filters"] = f
    main = next((u for u in units if (u.get("unit") or "main") == "main"), units[0])
    subs = [u for u in units if u is not main]
    if not subs:
        return units, []
    main_vals = content(main.get("filters")) or [main.get("search_query") or ""]

    def vals(u):
        f = u.get("filters")
        if isinstance(f, dict) and (f.get("대상") or f.get("지표") or "대상" in f or "지표" in f):
            return content(f)
        t = u.get("search_query") or u.get("text") or ""
        return [] if meaningless(t) else [t]

    items = [(k, vals(u), bool((u.get("filters") or {}).get("역할")), frame(u.get("filters"))) for k, u in enumerate(subs)]
    keep_ids, log = _prune(question, main_vals, main.get("search_query") or main.get("text") or "", items)
    return [main] + [subs[k] for k in keep_ids], log
