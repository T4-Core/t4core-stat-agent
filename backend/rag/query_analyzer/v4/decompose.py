"""
1-5 서브쿼리 분리 — 검색 단위 = 통계표 하나

  decompose(grounded, raw_slots, sub_slots, intents, sub_intents, lex, s) → (sub_queries, reason)

  1) 재작성 모듈(v3)이 하위 질문을 냈으면 그대로 씀 (하위마다 지역·시점·의도가 다를 수 있음). 하위마다 다시 접지해 후보 표를 붙임
  2) 아니면 접지된 대상·지표 '개념'이 2개 이상일 때 CSV 값 사전으로 판단
       - 모든 개념을 함께 가진 표가 있음 → 나누지 않음 (한 표에서 같이 자름)
       - 없음 → 개념마다 서브쿼리 (다른 슬롯은 공통). 근거를 reason 에
  3) 개념이 하나 → 나누지 않음

  개념 묶기: 대상 '출생아' 와 지표 '출생아수' 처럼 같은 것을 가리키면 하나로
    (이름이 서로를 포함하거나, 한쪽 표 집합이 다른 쪽에 들어 있으면 같은 개념)

  [NEW 11-12] 분리 정책 s.split_policy
    no_common_table : 위 2) 그대로 (함께 가진 표가 있으면 나누지 않음)
    always          : 개념이 2개 이상이면 함께 가진 표가 있어도 개념마다 서브쿼리 → 같은 표에서도 지표별 View.
                      후보 표는 함께 가진 표를 앞에 둠
  [CHANGED 11-12] 숫자뿐인 값('2021')은 개념에서 뺌 / 서브쿼리 문장의 시점은 범위('2021~2025년'),
    접지 못 한 지역 값은 문장에서 뺌 / max_sub_queries 로 잘리면 빠진 지표를 reason 에 적음
"""
import re

from backend.rag.csv_index.store import norm
from backend.rag.ingestion.normalize import std_geo_name
from backend.rag.query_analyzer.v4.grounding import ground_slots, target_values


def _overlap(a, b):
    a, b = norm(a), norm(b)
    return bool(a and b) and (a in b or b in a)


def concepts(grounded):
    """접지된 대상·지표 → 개념 목록 [{name, raws, tables}]
    지표 값마다 개념 하나. 대상 값은 이름이 겹치거나(인구 ⊂ 인구수) 표 집합이 지표 쪽을 포함(더 넓은 말)하면 그 지표에 흡수,
    아니면 따로 개념 (재작성 결과에서 대상만 있고 지표가 다른 경우)"""
    out = []
    for sv in grounded.get("지표") or []:
        if not sv["grounded"] or _numeric(sv["raw"]):              # [NEW 11-12] '2021' 같은 숫자는 지표가 아님
            continue
        same = next((c for c in out if _overlap(c["name"], sv["value"])), None)
        if same:
            same["raws"].append(sv["raw"])
            same["tables"] |= set(sv["tables"])
        else:
            out.append({"name": sv["value"], "raws": [sv["raw"]], "tables": set(sv["tables"])})
    for sv in grounded.get("대상") or []:
        if not sv["grounded"] or _numeric(sv["raw"]):
            continue
        ts = set(sv["tables"])
        host = next((c for c in out if _overlap(c["name"], sv["value"]) or _overlap(c["name"], sv["raw"])
                     or any(_overlap(r, sv["raw"]) for r in c["raws"])
                     or (c["tables"] and ts >= c["tables"])), None)
        if host:
            host["raws"].append(sv["raw"])
        else:
            out.append({"name": sv["value"], "raws": [sv["raw"]], "tables": ts})
    return out


REGION_SLOTS = ("지역", "전출지", "전입지")


def _numeric(v):
    """숫자·연도 표기뿐인 값 ('2021', '2021년', '2021~2025')"""
    return bool(re.fullmatch(r"[\d\s.,~\-년월]+", str(v or ""))) and any(ch.isdigit() for ch in str(v))


def time_text(values):
    """시점 목록 → 문장용 표기. 연도만 이어지면 '2021~2025년', 띄엄띄엄이면 '2020년 2023년', 월은 처음~끝
    [CHANGED 11-12] 이전: 첫 시점 하나만 ('2021년') → 기간을 묻는 서브쿼리 문장에 첫 해만 들어가던 문제"""
    vals = [str(v) for v in values or [] if str(v).strip()]
    if len(vals) <= 1:
        return " ".join(vals)
    years = [re.fullmatch(r"((?:19|20)\d{2})\s*년?", v) for v in vals]
    if all(years):
        ys = sorted({int(m.group(1)) for m in years})
        if len(ys) >= 2 and ys == list(range(ys[0], ys[-1] + 1)):
            return f"{ys[0]}~{ys[-1]}년"
        return " ".join(f"{y}년" for y in ys)
    return f"{vals[0]}~{vals[-1]}" if len(vals) > 2 else " ".join(vals)


def ungrounded_regions(grounded):
    """접지 못 한 지역·전출지·전입지 값 (지표 이름이 지역 칸에 들어간 경우 등) → 문장에서 뺌"""
    return {sv["raw"] for k in REGION_SLOTS for sv in grounded.get(k) or [] if not sv["grounded"]}


def _text(raw_slots, name, drop=()):
    regions = [v for v in (raw_slots.get("지역") or []) if v not in drop and std_geo_name(v) not in drop]
    parts = [time_text(raw_slots.get("시점")), *regions, *(raw_slots.get("성별") or []),
             *(raw_slots.get("연령") or []), name]
    return " ".join(str(p) for p in parts if p)


def _cut_note(names, n):
    """max_sub_queries 로 잘린 것 → reason 에 붙일 말"""
    return f" (최대 {n}개라 빠짐: {names[n:]})" if len(names) > n else ""


def decompose(grounded, raw_slots, sub_slots, intents, sub_intents, lex, s):
    intent = (intents or [None])[0]
    n = s.max_sub_queries
    if sub_slots and len(sub_slots) >= 2:
        out = []
        for i, ss in enumerate(sub_slots[:n], 1):
            g, _ = ground_slots(ss, lex)
            tv = [v for v in target_values(g) if not _numeric(v["raw"])]
            out.append({"id": f"S{i}", "text": _text(ss, " ".join(v["value"] for v in tv) or " ".join(ss.get("지표") or []),
                                                     ungrounded_regions(g)),
                        "slots": ss, "intent": (sub_intents or [None] * len(sub_slots))[i - 1] or intent,
                        "reason": "재작성 모듈 하위 질문", "candidate_tables": sorted({t for v in tv for t in v["tables"]})[:20]})
        cut = f" (최대 {n}개라 {len(sub_slots) - n}개 빠짐)" if len(sub_slots) > n else ""
        return out, f"재작성 모듈이 하위 질문 {len(sub_slots)}개로 나눔{cut}"
    cs = concepts(grounded)
    if len(cs) < 2:
        return [], "지표(대상)가 하나 → 나누지 않음"
    names = [c["name"] for c in cs]
    common = set.intersection(*[c["tables"] for c in cs]) if all(c["tables"] for c in cs) else set()
    always = getattr(s, "split_policy", "no_common_table") == "always"
    if not always and (common or not s.split_when_no_common_table):
        return [], f"지표 {names} 를 함께 가진 표 {len(common)}개 → 한 표에서 같이 자름"
    drop = ungrounded_regions(grounded)
    out = []
    for i, c in enumerate(cs[:n], 1):
        ss = {k: list(v) for k, v in raw_slots.items() if k not in ("대상", "지표", "의도")}
        ss["지표"] = [c["name"]]
        if common:
            why = f"'{c['name']}' 이(가) 있는 표 {len(c['tables'])}개 — 지표별 분리 정책 (함께 가진 표 {len(common)}개)"
            cand = sorted(common) + sorted(c["tables"] - common)
        else:
            why = f"'{c['name']}' 이(가) 있는 표 {len(c['tables'])}개 — 다른 지표와 함께 가진 표 없음"
            cand = sorted(c["tables"])
        out.append({"id": f"S{i}", "text": _text(raw_slots, c["name"], drop), "slots": ss, "intent": intent,
                    "reason": why, "candidate_tables": cand[:20]})
    head = (f"지표 {names} 를 함께 가진 표 {len(common)}개 — 분리 정책 always 라 지표별로" if common
            else f"지표 {names} 를 함께 가진 표가 없음")
    return out, f"{head} → {len(out)}개로 나눔{_cut_note(names, n)}"
