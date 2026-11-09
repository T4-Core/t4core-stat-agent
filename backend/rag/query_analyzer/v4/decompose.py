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
"""
from backend.rag.csv_index.store import norm
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
        if not sv["grounded"]:
            continue
        same = next((c for c in out if _overlap(c["name"], sv["value"])), None)
        if same:
            same["raws"].append(sv["raw"])
            same["tables"] |= set(sv["tables"])
        else:
            out.append({"name": sv["value"], "raws": [sv["raw"]], "tables": set(sv["tables"])})
    for sv in grounded.get("대상") or []:
        if not sv["grounded"]:
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


def _text(raw_slots, name):
    parts = [*(raw_slots.get("시점") or [])[:1], *(raw_slots.get("지역") or []), *(raw_slots.get("성별") or []),
             *(raw_slots.get("연령") or []), name]
    return " ".join(str(p) for p in parts if p)


def decompose(grounded, raw_slots, sub_slots, intents, sub_intents, lex, s):
    intent = (intents or [None])[0]
    if sub_slots and len(sub_slots) >= 2:
        out = []
        for i, ss in enumerate(sub_slots[:s.max_sub_queries], 1):
            g, _ = ground_slots(ss, lex)
            tv = target_values(g)
            out.append({"id": f"S{i}", "text": _text(ss, " ".join(v["value"] for v in tv) or " ".join(ss.get("지표") or [])),
                        "slots": ss, "intent": (sub_intents or [None] * len(sub_slots))[i - 1] or intent,
                        "reason": "재작성 모듈 하위 질문", "candidate_tables": sorted({t for v in tv for t in v["tables"]})[:20]})
        return out, f"재작성 모듈이 하위 질문 {len(sub_slots)}개로 나눔"
    cs = concepts(grounded)
    if len(cs) < 2:
        return [], "지표(대상)가 하나 → 나누지 않음"
    common = set.intersection(*[c["tables"] for c in cs]) if all(c["tables"] for c in cs) else set()
    if common or not s.split_when_no_common_table:
        return [], f"지표 {[c['name'] for c in cs]} 를 함께 가진 표 {len(common)}개 → 한 표에서 같이 자름"
    out = []
    for i, c in enumerate(cs[:s.max_sub_queries], 1):
        ss = {k: list(v) for k, v in raw_slots.items() if k not in ("대상", "지표", "의도")}
        ss["지표"] = [c["name"]]
        out.append({"id": f"S{i}", "text": _text(raw_slots, c["name"]), "slots": ss, "intent": intent,
                    "reason": f"'{c['name']}' 이(가) 있는 표 {len(c['tables'])}개 — 다른 지표와 함께 가진 표 없음",
                    "candidate_tables": sorted(c["tables"])[:20]})
    return out, f"지표 {[c['name'] for c in cs]} 를 함께 가진 표가 없음 → {len(out)}개로 나눔"
