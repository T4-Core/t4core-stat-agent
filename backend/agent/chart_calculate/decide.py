"""
[NEW] 계획 결정 (HCX) — 질문 + View + 모듈 2 차트 계획 → Decision (무엇을 계산할지)

  decide(bundle, records, charts) → (Decision, notes)
    1. build_prompt   View 마다 id · 열 · 열별 값 목록을 보여 준다 (HCX 가 고를 수 있는 것은 여기 적힌 것뿐)
    2. chat           core.llm.chat(schema=CHART_PLAN_SCHEMA)
    3. parse_decision 응답을 planner.Decision 으로. 잘못된 항목은 그 항목만 버리고 notes 에 남긴다

  실패해도 예외를 던지지 않는다. 빈 Decision + 사유를 돌려주고, 그 뒤 단계는 "계획이 없어 만들지 않음"으로 흘러간다.
  (키가 없을 때 core.llm 이 내는 SystemExit 는 설정 오류라 잡지 않는다.)

  TODO: 프롬프트·스키마는 실제 HCX 응답으로 검증하지 못했다 (tests/ 는 가짜 chat 으로만 돈다).
        HCX 가 실패했을 때 규칙만으로 최소 계획을 세우는 대안은 아직 없다.
"""
from typing import Any, Callable, get_args

from pydantic import ValidationError

from backend.agent.chart_calculate.planner import (STAGE1_ID, AnswerDecision, ChartDecision, Decision,  # noqa: F401
                                                   sub_question_ids)
from backend.agent.chart_calculate.select import VALUE_COL
from backend.agent.prompts import CHART_PLAN_SCHEMA, CHART_PLAN_SYS
from backend.schemas.chart import ChartRequest, ChartType, Measure
from backend.schemas.query import Filters, QueryBundle
from backend.schemas.record import Record

MAX_VALUES = 40          # 열 하나에서 프롬프트에 보여 줄 값 수 (시군구처럼 값이 많은 열)
MAX_TOKENS = 4000       # [CHANGED 11-11] 이전: 2000 — 범주마다 계산을 따로 적은 응답이 6,036자에서 끊겼다
_AGGS = {"sum", "mean"}
_KINDS = {"max", "min"}
_ORDERS = {"desc", "asc"}
_CHART_TYPES = set(get_args(ChartType))      # [NEW 11-25 4단계] HCX 가 고를 수 있는 차트 이름


def _year_runs(years: list[str]) -> str:
    """연도 목록 → 연속 구간 요약 ('1970~1999, 2001~2025'). 빠진 해는 구간 사이에 그대로 드러난다 (불연속을 연속처럼 보이게 하지 않는다)"""
    nums = sorted(int(y) for y in years)
    runs, start = [], nums[0]
    for prev, cur in zip(nums, nums[1:] + [None]):
        if cur != prev + 1:
            runs.append(f"{start}" if start == prev else f"{start}~{prev}")
            start = cur
    return ", ".join(runs) + f" (모두 {len(nums)}개)"


def _values(rec: Record, col: str, hint: str) -> str:
    i = rec.table.columns.index(col)
    vals = list(dict.fromkeys(str(r[i]) for r in rec.table.rows))
    if col == "시점":               # [NEW 11-18] 시점은 자르지 않는다 (F12). 앞 40개만 보여 주면 HCX 가 1970~2009 만 골라 '가장 많은 해' 가 틀렸다 (Q33)
        return _year_runs(vals) if len(vals) > MAX_VALUES and all(len(v) == 4 and v.isdigit() for v in vals) else ", ".join(vals)
    if len(vals) > MAX_VALUES:      # 값이 많으면 질문에 나온 값을 앞에 두고 자른다 (HCX 는 보이는 값만 고를 수 있다)
        vals.sort(key=lambda v: v not in hint)
        return ", ".join(vals[:MAX_VALUES]) + f" … 외 {len(vals) - MAX_VALUES}개"
    return ", ".join(vals)


def _filters_text(f: Filters | None) -> tuple[str, str]:
    """(고정 조건, 참고 조건) 문장. 고정 = 시점·지역·대상 (시점·지역은 planner 가 코드로도 고정한다)"""
    if f is None:
        return "", ""
    fixed = [f"시점 {', '.join(map(str, f.시점))}" if f.시점 else "", f"지역 {', '.join(f.지역)}" if f.지역 else "",
             f"대상 {', '.join(f.대상)}" if f.대상 else ""]
    age = ""
    if f.연령 and (f.연령.from_ is not None or f.연령.to is not None):
        age = f"연령 {f.연령.from_ or 0}세 이상" if f.연령.to is None else f"연령 {f.연령.from_ or 0}~{f.연령.to}세"
    ref = [f"지표 {', '.join(f.지표)}" if f.지표 else "", f"성별 {', '.join(f.성별)}" if f.성별 else "", age,
           f"비교축 {f.비교축}" if f.비교축 else "", f"의도 {f.의도}" if f.의도 else ""]
    return " · ".join(x for x in fixed if x), " · ".join(x for x in ref if x)


def _hint(bundle: QueryBundle) -> str:
    return " ".join([bundle.original, bundle.rewritten or "", *bundle.sub_questions])


def _header_lines(bundle: QueryBundle) -> list[str]:
    fixed, ref = _filters_text(bundle.filters)
    return [f"[질문] {bundle.original}", f"[재작성] {bundle.rewritten or bundle.original}",
            f"[고정 조건] {fixed or '(없음)'}", f"[참고 조건] {ref or '(없음)'}"]


def _record_lines(rec: Record, hint: str) -> list[str]:
    """View 하나를 프롬프트에 소개하는 줄들 (기존 형식과 세트 형식이 같이 쓴다)"""
    lines = [f"- record_id={rec.id}", f"  설명: {rec.lexical_text[:120]}"]
    if rec.metadata.get("unit"):
        lines.append(f"  단위: {rec.metadata['unit']}  (표 전체의 단위 목록. 항목마다 맞는 것을 고른다)")
    for col in rec.table.columns:
        if col != VALUE_COL:
            lines.append(f"  열 '{col}': {_values(rec, col, hint)}")
    return lines + [f"  주의: {n.text}" for n in rec.notes]


def build_prompt(bundle: QueryBundle, records: list[Record], charts: list[ChartRequest]) -> str:
    """차트에 view_ids 가 하나라도 있으면 세트 형식, 하나도 없으면 기존 형식 (옛 입력·Swagger 예시는 글자 그대로 같다)"""
    if any(c.view_ids for c in charts):
        return _set_prompt(bundle, records, charts)
    subs = sub_question_ids(bundle)
    hint = _hint(bundle)
    lines = [*_header_lines(bundle), "", "[하위 질문]"]
    sub_filters = bundle.sub_filters or []
    for i, (sid, text) in enumerate(subs):
        sub_fixed = _filters_text(sub_filters[i])[0] if i < len(sub_filters) else ""
        lines.append(f"- {sid}: {text}" + (f"  [고정 조건] {sub_fixed}" if sub_fixed else ""))
    lines += ["", "[차트 계획]"]
    lines += [f"- chart_id={c.chart_id} chart_type={c.chart_type} measure={c.measure} "
              f"하위질문={','.join(c.sub_question_ids) or '-'}" for c in charts if c.chart_type] or ["- (없음)"]
    lines += ["", "[자료]"]
    for rec in records:
        lines += _record_lines(rec, hint)
    return "\n".join(lines)


def chart_candidates(c: ChartRequest) -> list[str]:
    """[NEW 11-25 4단계] 모듈 2 가 넘긴 차트 후보: 1순위(chart_type) + 대체 후보 (순서 그대로, 중복 없이)"""
    rest = c.fallback_charts or ([c.fallback_chart] if c.fallback_chart else [])
    return list(dict.fromkeys([x for x in [c.chart_type, *rest] if x]))


def _candidates_line(c: ChartRequest) -> str:
    """세트의 '차트 후보' 줄. 사용자가 질문에서 차트를 정했으면(request) 그 차트를 그대로 적게 한다 (planner.choose_chart 도 바꾸지 않는다)"""
    if c.request is not None:
        return f"차트 후보: 사용자가 질문에서 차트를 정했다 → charts 의 chart_type 에 {c.chart_type} 를 그대로 적는다"
    cands = chart_candidates(c)
    return ("차트 후보 (질문 의도에 가장 맞는 하나를 charts 의 chart_type 에): "
            + " · ".join(f"{x}(1순위)" if i == 0 else x for i, x in enumerate(cands)))


def _set_prompt(bundle: QueryBundle, records: list[Record], charts: list[ChartRequest]) -> str:
    """[NEW] 세트 형식: 세트 = (질문, 차트 유형, View). 세트마다 블록 하나에 질문 · 차트 · **그 세트의 View 만** 담는다.
    세트에 속하지 않는 View(하위 질문이 있을 때의 main View 등)는 나오지 않는다.
    view_ids 가 비어 있는 세트는 자료가 없다 (모듈 2 가 건너뛴 하위 질문 — 이유는 reason 에 있다) → 계산하지 않는다"""
    subs = sub_question_ids(bundle)
    sub_filters = bundle.sub_filters or []
    text_of = dict(subs)
    fixed_of = {sid: (_filters_text(sub_filters[i])[0] if i < len(sub_filters) else "") for i, (sid, _) in enumerate(subs)}
    by_id = {r.id: r for r in records}
    hint = _hint(bundle)
    lines = _header_lines(bundle)
    for c in charts:
        lines += ["", f"[세트 {c.chart_id}]  (charts 의 chart_id = \"{c.chart_id}\")"]
        for sid in c.sub_question_ids or ["-"]:
            lines.append(f"질문 (answers 의 sub_question_id = \"{sid}\"): {text_of.get(sid, '(질문 문장 없음)')}"
                         + (f"  [고정 조건] {fixed_of[sid]}" if fixed_of.get(sid) else ""))
        lines.append(f"차트: {c.chart_type} (measure={c.measure})" if c.chart_type
                     else "차트: 없음 (질문용 계산만)" if c.view_ids else "차트: 없음")
        if c.chart_type:
            lines.append(_candidates_line(c))                 # [NEW 11-25 4단계] HCX 가 질문 의도로 고를 차트 후보
        if not c.view_ids:
            lines.append(f"자료: (없음 — {c.reason or '모듈 2 가 View 를 정하지 못함'}) → 이 세트는 계산하지 않는다")
            continue
        lines.append("자료:")
        for vid in c.view_ids:
            lines += _record_lines(by_id[vid], hint) if vid in by_id else [f"- (자료 없음: record_id={vid} 가 records 에 없음)"]
    return "\n".join(lines + _stage1_lines(charts, text_of))


def _stage1_lines(charts: list[ChartRequest], text_of: dict[str, str]) -> list[str]:
    """[NEW 11-27] 하위 질문이 둘 이상이면 '1차결과' 표를 알린다. HCX 가 하위 질문 결과로 다시 계산할 때(뺀 값 · 합 · 차이 · 몇 배)
    이 표를 쓰는 2차 계산을 적는다 (규칙 11). 결과 값은 1차 계산 뒤에 코드가 채운다 (stage2.py)"""
    sids = list(dict.fromkeys(s for c in charts if c.view_ids for s in c.sub_question_ids))
    if len(sids) < 2:
        return []
    return ["", f"[{STAGE1_ID}]  (record_id = \"{STAGE1_ID}\". 위 세트들의 질문용 계산 결과를 모은 표. 값은 1차 계산 뒤에 채워진다)",
            *(f"- item \"{s}\": {text_of.get(s, '(질문 문장 없음)')} 의 결과" for s in sids)]


# ── 응답 → Decision ──────────────────────────────────────────────
def _select(conditions: Any) -> dict[str, list]:
    out: dict[str, list] = {}
    for c in conditions if isinstance(conditions, list) else []:
        if isinstance(c, dict) and c.get("column") and c.get("values"):
            out[str(c["column"])] = list(c["values"])
    return out


def _pick(raw: dict) -> dict | None:
    if not isinstance(raw, dict) or not raw.get("record_id"):
        return None
    return {"role": raw.get("role") or None, "record_id": raw["record_id"], "item": raw.get("item") or None,
            "select": _select(raw.get("conditions")), "sign": raw.get("sign") if raw.get("sign") in ("+", "-") else None,
            "unit": str(raw.get("unit") or "").strip() or None}


def _args(raw: dict) -> dict:
    """빈 값("" · [] · 0)은 '쓰지 않음' 으로 본다"""
    out = {k: raw[k] for k in ("from", "to", "base", "join_on", "top_n") if raw.get(k)}
    if raw.get("agg") in _AGGS:
        out["agg"] = raw["agg"]
    if raw.get("kind") in _KINDS:          # [NEW 11-16] 최댓값/최솟값 (extreme)
        out["kind"] = raw["kind"]
    if raw.get("order") in _ORDERS:        # [NEW 11-16] 큰 값부터/작은 값부터 (rank)
        out["order"] = raw["order"]
    den = raw.get("denominator")
    if isinstance(den, dict) and den.get("scope") in ("question", "selected"):
        operand = _pick(den) if den["scope"] == "question" else None
        out["denominator"] = {"scope": den["scope"], "basis": den.get("basis") or None,
                              "label": den.get("label") or None, "operand": operand}
    return out


def _picks(raw: Any) -> list[dict]:
    return [p for p in map(_pick, raw if isinstance(raw, list) else []) if p]


def parse_decision(raw: Any) -> tuple[Decision, list[str]]:
    """HCX 응답(dict) → Decision. 항목 하나가 잘못되어도 나머지는 살린다"""
    if not isinstance(raw, dict) or "_raw" in raw:
        text = str(raw.get("_raw", "")) if isinstance(raw, dict) else str(raw)
        if text.lstrip().startswith("{"):     # JSON 으로 시작했는데 못 읽음 = 출력 한도에서 끊긴 경우가 대부분
            return Decision(), [f"HCX 응답이 중간에 끊김 (길이 {len(text):,}자, 출력 한도 {MAX_TOKENS} 토큰을 넘었을 수 있음)"]
        return Decision(), ["HCX 응답을 JSON 으로 읽지 못함"]
    notes, charts, answers = [], [], []
    for c in raw.get("charts") or []:
        try:
            ct = c.get("chart_type") or None              # [NEW 11-25 4단계] HCX 가 고른 차트 ("" = 1순위 그대로)
            if ct is not None and ct not in _CHART_TYPES:
                notes.append(f"HCX 가 고른 차트 '{ct}' 는 지원하지 않는 이름이라 버림 ({c.get('chart_id')})")
                ct = None
            charts.append(ChartDecision.model_validate({
                "chart_id": c.get("chart_id"), "chart_type": ct, "title": c.get("title") or None,
                "record_id": c.get("record_id") or None,
                "select": _select(c.get("conditions")), "operands": _picks(c.get("series")), **_args(c)}))
        except (ValidationError, AttributeError) as e:
            notes.append(f"HCX 차트 결정을 버림 ({_short(e)})")
    for a in raw.get("answers") or []:
        try:
            if a.get("op") not in get_args(Measure):
                notes.append(f"HCX 질문용 계산을 버림 (모르는 연산: {a.get('op')})")
                continue
            answers.append(AnswerDecision.model_validate({
                "sub_question_id": a.get("sub_question_id") or None, "op": a["op"],
                "operands": _picks(a.get("operands")), **_args(a)}))
        except (ValidationError, AttributeError) as e:
            notes.append(f"HCX 질문용 계산을 버림 ({_short(e)})")
    return Decision(charts=charts, answers=answers), notes


def _short(e: Exception) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:2])
    return str(e)[:80]


def decide_trace(bundle: QueryBundle, records: list[Record], charts: list[ChartRequest],
                 chat: Callable[..., Any] | None = None) -> dict[str, Any]:
    """decide 와 같은 일 + 중간 결과 {messages, raw, decision, notes} (테스트 화면 · 디버깅용)"""
    if not records:
        return {"messages": [], "raw": None, "decision": Decision(), "notes": ["View 가 없어 계획을 세우지 않음"]}
    if chat is None:
        from backend.core.llm import chat      # HCX 를 실제로 부를 때만 import (테스트는 HCX 설정 없이 돈다)
    messages = [{"role": "system", "content": CHART_PLAN_SYS},
                {"role": "user", "content": build_prompt(bundle, records, charts)}]
    try:
        raw = chat(messages, schema=CHART_PLAN_SCHEMA, max_tokens=MAX_TOKENS)
    except Exception as e:  # noqa: BLE001  (HcxError, 네트워크 오류 — 답변 전체를 멈추지 않는다)
        return {"messages": messages, "raw": None, "decision": Decision(), "notes": [f"HCX 호출 실패: {_short(e)}"]}
    decision, notes = parse_decision(raw)
    return {"messages": messages, "raw": raw, "decision": decision, "notes": notes}


def decide(bundle: QueryBundle, records: list[Record], charts: list[ChartRequest],
           chat: Callable[..., Any] | None = None) -> tuple[Decision, list[str]]:
    """chat = core.llm.chat 과 같은 모양의 함수. 테스트에서는 가짜를 넣는다"""
    t = decide_trace(bundle, records, charts, chat)
    return t["decision"], t["notes"]
