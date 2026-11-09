"""
1-4 조건 검증·되묻기 — 필수 슬롯 3개 (시점·지역·대상)

  시점 규칙 (configs/query_v4.yaml)
    - 시점이 비었는데 질문에 '최근·요즘·현재…' → base_year (2026년)
    - 시점이 비었는데 '추이·변화…' 또는 의도 '추이' → 최근 trend_years 년 (2022~2026년)   ('추이'가 '최근'보다 우선)
    - 표에 그 해가 없으면 되묻지 않고 View 단계(resolve·build_view)의 '최신 자료 대체'와 메모로 처리
  대상 = 대상 또는 지표 중 하나라도 CSV 의 행(항목·분류 값)에 접지되면 충족
  지역 = 지역 슬롯 값이 있으면 충족 ('전국' 포함). 없으면 되묻기

  누락이 있으면 검색을 멈추고 Clarification 목록 반환. 후보는 CSV 값 사전에서:
    지역 : 접지된 대상의 표들이 가진 지역 (전국 → 시도 → 그 밖, 표 수 순)
    시점 : 그 표들에 실제로 있는 연도 (최신 순) + '최근 N년' 범위
    대상 : 질문 속 대상 표현과 비슷한 CSV 이름 (포함 → 유사도), 없으면 많이 쓰이는 항목
  사용자가 고른 값은 apply_selections 로 슬롯에 넣고 다시 접지 (HCX 다시 안 부름)
"""
import re

from backend.rag.ingestion.normalize import SIDO_CANON
from backend.rag.query_analyzer.v4.grounding import target_tables, target_values


# 질문에 시점이 '명시'됐는가 — 연도·작년·N년 전·최근 N년·월·분기 등. 명시가 없으면 재작성 모듈의 시점 추정('요즘' → 최신 연도)을
# 설정 규칙('요즘' → base_year, '추이' → 최근 N년)으로 바꿈. '최근 3년'처럼 기간이 명시된 표현은 재작성 모듈 해석을 그대로 둠
EXPLICIT_TIME_RE = re.compile(r"\d{4}|\d+\s*(?:년|개년)|작년|올해|금년|전년|내년|재작년|지난\s*해|\d+\s*월|분기|반기|"
                              r"(?:일|이|삼|사|오|육|칠|팔|구|십)\s*년\s*(?:간|전|동안)")


def apply_time_rules(raw_slots, question, intents, s):
    """시점 규칙 → (raw_slots, 적용한 규칙 목록). 질문에 시점이 명시돼 있으면 그대로"""
    if EXPLICIT_TIME_RE.search(question or ""):
        return raw_slots, []
    q = re.sub(r"\s+", "", question or "")
    trend = any(w in q for w in s.trend_words) or any(i in s.trend_intents for i in intents or [])
    recent = next((w for w in s.recent_words if w in q), None)
    prev = raw_slots.get("시점")
    tag = f" (재작성 모듈 추정 {prev} 대신)" if prev else ""
    if trend:
        yrs = s.trend_range()
        why = next((w for w in s.trend_words if w in q), None) or "의도 추이"
        return ({**raw_slots, "시점": [f"{y}년" for y in yrs]},
                [f"'{why}' → 최근 {s.trend_years}년 ({yrs[0]}~{yrs[-1]}년){tag}"])
    if recent:
        return {**raw_slots, "시점": [f"{s.base_year}년"]}, [f"'{recent}' → {s.base_year}년{tag}"]
    return raw_slots, []


def missing_required(grounded, raw_slots, s):
    """→ [(슬롯, 이유)]"""
    out = []
    if "시점" in s.required_slots and not grounded.get("시점"):
        out.append(("시점", "시점이 없음 (연도·'최근'·'추이' 같은 표현이 없음)"))
    if "지역" in s.required_slots and not grounded.get("지역"):
        out.append(("지역", "지역이 없음"))
    if "대상" in s.required_slots and not target_values(grounded):
        raw = [v for k in ("지표", "대상") for v in raw_slots.get(k) or []]
        out.append(("대상", f"대상·지표 {raw} 를 CSV 의 항목·분류에서 찾지 못함" if raw else "무엇의 통계인지(대상·지표)가 없음"))
    return out


def _region_order(v):
    n = v["value"]
    return (0 if n == "전국" else 1 if n in SIDO_CANON else 2, -v["n_tables"], n)


def options_for(slot, grounded, raw_slots, lex, s):
    tbls = target_tables(grounded)
    tbl_ids = sorted(tbls) if tbls else None
    if slot == "지역":
        vals = sorted(lex.idx.values("지역", tbl_ids=tbl_ids, scope=lex.scope), key=_region_order)
        return [{"option_id": f"지역-{i}", "value": v["value"], "label": v["value"], "n_tables": v["n_tables"],
                 "example_tables": v["example_tables"]} for i, v in enumerate(vals[:s.n_options], 1)], True
    if slot == "시점":
        yc = lex.idx.years(set(tbl_ids) if tbl_ids else None, scope=lex.scope)
        years = sorted(yc, reverse=True)
        opts = []
        if len(years) >= 2:
            span = years[:s.trend_years]
            opts.append({"option_id": "시점-range", "value": f"{span[-1]}~{span[0]}년",
                         "label": f"최근 {len(span)}개 연도 ({span[-1]}~{span[0]}년)", "n_tables": min(yc[y] for y in span),
                         "example_tables": []})
        opts += [{"option_id": f"시점-{y}", "value": f"{y}년", "label": f"{y}년", "n_tables": yc[y], "example_tables": []}
                 for y in years[:s.n_options - len(opts)]]
        return opts, True
    if slot == "대상":
        raw = [v for k in ("지표", "대상") for v in raw_slots.get(k) or []]
        names = []
        for r in raw:
            names += lex.suggest(r, "대상", k=s.n_options)
        if not names:
            names = lex.suggest("", "대상", k=s.n_options)
        out = []
        for i, n in enumerate(dict.fromkeys(names), 1):
            h = lex.best(n, "지표")
            out.append({"option_id": f"대상-{i}", "value": n, "label": n, "n_tables": h.n_tables if h else 0,
                        "example_tables": (h.tables if h else [])[:3]})
        return out[:s.n_options], True
    return [], False


def check(grounded, raw_slots, lex, s):
    """→ Clarification 목록 (빈 목록 = 필수 슬롯 충족)"""
    out = []
    for slot, reason in missing_required(grounded, raw_slots, s):
        opts, multi = options_for(slot, grounded, raw_slots, lex, s)
        out.append({"slot": slot, "reason": reason, "options": opts, "multi": multi,
                    "answer_hint": f"POST /api/v1/rag/v4/clarify  selections={{\"{slot}\": [<option.value>, …]}}"})
    return out


def apply_selections(raw_slots, selections):
    """사용자가 고른 값 → 슬롯 (문자열 목록, 재작성 모듈 슬롯과 같은 모양). 대상 선택은 지표 슬롯으로 (CSV 이름이므로)"""
    out = {k: list(v) for k, v in (raw_slots or {}).items()}
    for slot, vals in (selections or {}).items():
        vals = [vals] if isinstance(vals, str) else list(vals or [])
        if not vals:
            continue
        if slot == "대상":
            out["지표"] = vals
        elif slot == "시점":
            out["시점"] = vals
        else:
            out[slot] = vals
    return out

