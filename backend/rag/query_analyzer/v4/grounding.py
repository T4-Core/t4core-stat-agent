"""
1-3 슬롯 접지 — 재작성 모듈(v3)이 낸 슬롯 값(문자열)을 CSV 값 사전의 실제 값·표에 맞춤

  ground_slots(raw_slots, lex) → {슬롯: [SlotValue dict]}, notes
    시점  : '2025년' · '2021~2025년' → 연도 int (query_bundle.parse_years). 근거 = 그 해 자료가 있는 표 수
    지역  : std_geo_name + rule_dict → 표준명. 근거 = CSV 지역 분류에 그 이름이 있는 표
    성별  : rule_dict → 남자/여자. 근거 = 성별 분류(또는 항목 이름)에 있는 표
    연령  : parse_ages → {from, to}. 근거 = 연령 분류 값이 그 범위와 겹치는 표
    대상·지표 : lexicon.resolve → CSV 항목·분류 값 ('행'에 있는가). 대상 또는 지표 하나라도 접지되면 '대상' 필수 슬롯 충족
    그 밖 (국적·조건·이동·비교축·전출지·전입지) : lexicon.resolve 로 근거만 붙이고 값은 유지

SlotValue = {raw, value, source, grounded, n_tables, tables, csv(근거 행 상위 8개), candidates(다른 해석)}
"""
from backend.rag.ingestion.normalize import std_geo_name
from backend.rag.query_analyzer.query_bundle import parse_ages, parse_years

TARGET_SLOTS = ("대상", "지표")
MAX_TABLES_OUT = 50


def _sv(raw, value, source, tables=(), csv=(), candidates=(), note="", match=""):
    tables = sorted(set(tables))
    return {"raw": raw, "value": value, "source": source, "match": match, "grounded": bool(tables), "n_tables": len(tables),
            "tables": tables[:MAX_TABLES_OUT], "csv": list(csv)[:8], "candidates": list(candidates)[:5], "note": note}


def _from_hit(raw, h, alts=()):
    return _sv(raw, h.value, h.source, h.tables, h.csv,
               [{"value": a.value, "source": a.source, "n_tables": a.n_tables} for a in alts if a.value != h.value],
               match=h.match)


def ground_time(values, lex, notes):
    years = parse_years(values, notes) or []
    have = lex.idx.years(scope=lex.scope)
    out = []
    for y in years:
        tables = [t for t in lex.idx.table_ids(lex.scope) if y in (lex.idx.table(t).get("years") or [])]
        out.append(_sv(f"{y}년", y, "rule", tables, note="" if have.get(y) else f"{y}년 자료가 있는 표가 없음"))
    return out


def ground_ages(values, lex, notes):
    rng = parse_ages(values, notes)
    if not rng:
        return []
    lo, hi = rng["from"], rng["to"]
    tables = set()
    for r in lex.idx.v[(lex.idx.v["slot"] == "연령") & (lex.idx.v["kind"] == "dim")].to_dict("records"):
        if lex.scope == "selected" and not r["selected"]:
            continue
        a, _, b = str(r.get("std") or "").partition("-")
        if not a:
            continue
        a, b = int(a), (int(b) if b else None)
        if (hi is None or a <= hi) and (b is None or b >= lo):          # 범위가 겹치는 연령 코드
            tables.add(r["tbl_id"])
    return [_sv(", ".join(values), rng, "rule", tables)]


def ground_slots(raw_slots, lex):
    notes, out = [], {}
    for slot, values in (raw_slots or {}).items():
        if slot == "의도" or not values:
            continue
        values = [values] if isinstance(values, str) else list(values)
        if slot == "시점":
            out[slot] = ground_time(values, lex, notes)
        elif slot == "연령":
            out[slot] = ground_ages(values, lex, notes)
        else:
            res = []
            for v in values:
                if slot in ("지역", "전출지", "전입지"):
                    v = std_geo_name(v)
                hits = lex.resolve(v, slot)
                if hits:
                    res.append(_from_hit(v, hits[0], hits[1:]))
                    if not hits[0].grounded:
                        notes.append(f"[{slot}] '{v}' → '{hits[0].value}' (CSV 에 근거 없음)")
                else:
                    res.append(_sv(v, v, "llm", note="CSV·사전에서 찾지 못함"))
                    notes.append(f"[{slot}] '{v}' 를 CSV·사전에서 찾지 못함")
            out[slot] = res
    return out, notes


def target_values(grounded):
    """대상·지표 중 접지된 값 (지표 먼저). 필수 슬롯 '대상' 충족 판단과 서브쿼리 분리에 씀"""
    return [sv for k in ("지표", "대상") for sv in grounded.get(k) or [] if sv["grounded"]]


def target_tables(grounded):
    ts = None
    for sv in target_values(grounded):
        ts = set(sv["tables"]) if ts is None else ts | set(sv["tables"])
    return ts
