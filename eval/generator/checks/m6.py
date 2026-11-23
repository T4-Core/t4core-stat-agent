"""모듈 6 answer_compose + 사용자 응답 문장 (criteria.md 3장 1단계)

  - 금지 문구 (내부 오류 · None · nan)
  - 표시 반올림 (c)층: 계산 요약 표의 결과 문자열 == 평가기 기대 표시값 (display_ref.py, 팀 format_value 와 독립)
  - 결과 단위: 연산별 기대 결과 단위와 표시 단위 (F1 '1세이상' 같은 단위 오류)
  - FINAL binding: numeric_match · semantic_ok (binding.py)
  - 방향 단어, 필수 주의사항, 형식 지표(method · 자리표시자 검사 · Step Coverage)
"""
import re

from eval.generator import binding, trace
from eval.generator import resolve as R
from eval.generator.checks.m3 import AMBIGUOUS, find_value
from eval.generator.checks.normalize import CONVERTIBLE, normalize
from eval.generator.display_ref import display_tolerance, from_display
from eval.generator.findings import Finding
from eval.generator.schema import Question, SubQuestion
from eval.generator.subq import SubResult, has_value
from synthetic_gold_pipeline.tools.evaluation_tool import DECREASE, INCREASE

BAD_TOKENS = ("None", "nan", "null", "내부 오류", "Traceback", "{a", "undefined")
UNIT_CHANGING = {"share": "%", "growth_rate": "%", "cagr": "%", "index": "index"}
PROJECTION = ("추계", "전망", "예측")


def bad_tokens(text: str) -> list[str]:
    return [t for t in BAD_TOKENS if re.search(rf"(?<![A-Za-z]){re.escape(t)}(?![A-Za-z])", text)]


def expected_result_unit(op: str, in_unit: str | None) -> set[str | None]:
    if op in UNIT_CHANGING:
        return {UNIT_CHANGING[op]}
    if op in ("change", "diff") and in_unit == "%":
        return {"%p"}
    if op == "ratio":
        return {"배"} | ({None} if in_unit is None else set())
    return {in_unit, CONVERTIBLE.get(in_unit)} if in_unit else {None}


def _shown(run: dict) -> str:
    return " ".join([trace.answer_text(run)] + trace.user_caveats(run) +
                    [c.get("text", "") for c in trace.m6(run).get("caveats") or []])


def text_checks(run: dict) -> list[Finding]:
    text = trace.answer_text(run)
    out = []
    bad = bad_tokens(text)
    out.append(Finding("bad_token", "stage1", "M6", not bad, ", ".join(bad)))
    return out


def display_checks(run: dict) -> list[Finding]:
    """계산 요약 표(calc_summary)의 결과 열 == 기대 표시값"""
    out = []
    m3 = trace.m3(run)
    displays = m3.get("displays") or {}
    by_step = {c.get("step_id"): c for c in m3.get("calc_results") or []}
    for t in trace.m6(run).get("tables") or []:
        if t.get("kind") != "calc_summary":
            continue
        cols = t.get("columns") or []
        if "결과" not in cols:
            continue
        ri = cols.index("결과")
        for sid, row, raw in zip(t.get("step_ids") or [], t.get("rows") or [], t.get("raw_rows") or []):
            c = by_step.get(sid)
            if not c or isinstance(raw[ri], list) or raw[ri] is None:
                continue
            want = from_display(raw[ri], displays.get(c.get("display_ref")))
            got = row[ri]
            out.append(Finding("display_round", "stage1", "M3", want == got, f"표시 {got!r} / 기대 {want!r}",
                               detail={"step_id": sid}))
    return out


def unit_checks(run: dict) -> list[Finding]:
    """계산 결과의 표시 단위가 연산과 입력 단위로 정해지는 결과 단위와 맞는가 (F1 유형)"""
    out = []
    m3 = trace.m3(run)
    displays = m3.get("displays") or {}
    records = trace.records_of(run)
    steps = (m3.get("chart_plan") or {}).get("answer_steps") or []
    for c in m3.get("calc_results") or []:
        if not has_value(c) or not c.get("inputs"):
            continue
        row, _ = R.resolve_input(records, c["inputs"][0], R.select_of(steps, c.get("step_id"), c["inputs"][0].get("record_id")))
        in_unit = R.row_unit(row) if row else None
        d = displays.get(c.get("display_ref")) or {}
        src = d.get("source_unit") or c.get("unit")
        if in_unit is None:
            if src and src not in R.KNOWN_UNITS and src not in ("index",):
                out.append(Finding("result_unit", "stage1", "M3", None, f"단위 '{src}' 를 입력 단위로 확인하지 못함 (수동)",
                                   detail={"step_id": c.get("step_id")}, source="adapter"))
            continue
        want = expected_result_unit(c.get("op"), in_unit)
        if c.get("op") == "ratio" and in_unit:
            row_b, _ = R.resolve_input(records, c["inputs"][-1], None) if len(c["inputs"]) > 1 else (None, None)
            ub = R.row_unit(row_b) if row_b else None
            want = {"배"} if ub == in_unit else ({f"{in_unit}/{ub}"} if ub else {None})
        out.append(Finding("result_unit", "stage1", "M3", src in want, f"표시 단위 '{src}' / 기대 {sorted(map(str, want))}",
                           detail={"step_id": c.get("step_id"), "input_unit": in_unit}))
    return out


def value_checks(spec: SubQuestion, res: SubResult, run: dict) -> list[Finding]:
    """FINAL 값이 답변 문장에 있고 기대한 대상에 연결되는가"""
    out = []
    if res.out is None:
        return out
    text = trace.answer_text(run)
    m3 = trace.m3(run)
    displays = m3.get("displays") or {}
    records = trace.records_of(run)
    steps = (m3.get("chart_plan") or {}).get("answer_steps") or []
    for vs in spec.values:
        if vs.role != "FINAL":
            continue
        c, p = find_value([x for x in res.out.calcs if has_value(x)], vs, spec.m3.op, spec.match.region_any)
        if p is AMBIGUOUS:
            out.append(Finding("binding", "stage1", "M6", None, "기대값에 맞는 결과 점이 여럿 (binding_unresolved)", spec.key))
            continue
        d = displays.get((c or {}).get("display_ref")) or {}
        tol_raw = display_tolerance(d) if d else 0.5
        tol = abs(normalize(tol_raw, d.get("source_unit") or (c or {}).get("unit")).value or tol_raw)
        b = binding.check(text, vs.value, vs.unit, vs.binding.model_dump(exclude_none=True) if vs.binding else None,
                          tol=tol, calc=c, records=records, steps=steps, point_key=(p or {}).get("key"))
        out.append(Finding("final_in_answer", "stage2", "M6", b.numeric_match, "", spec.key, {"value": vs.value}))
        if b.numeric_match:
            out.append(Finding("binding", "stage1", "M6", b.semantic_ok, b.detail.get("why", ""), spec.key, b.detail,
                               source="schema" if c else "text"))
    if spec.direction:
        sents = [s for s in re.split(r"(?<=[.!?])\s+|\n", text) if s]
        up = any(INCREASE.search(s) for s in sents)
        down = any(DECREASE.search(s) for s in sents)
        if up or down:
            ok = (spec.direction == "up" and up and not (down and not up)) or (spec.direction == "down" and down)
            out.append(Finding("direction", "stage1", "M6", ok, f"기대 {spec.direction}, 증가어 {up} 감소어 {down}", spec.key))
    return out


def caveat_checks(q: Question, run: dict) -> list[Finding]:
    """필수 주의사항 (questions/README.md 코드표). 필요 조건이 입력에서 성립할 때만 검사한다"""
    out = []
    shown = _shown(run)
    records = trace.records_of(run)
    used = {rid for c in trace.m3(run).get("calc_results") or [] if has_value(c) for rid in c.get("record_ids") or []}
    used_recs = [r for r in records if r.get("id") in used] or records
    periods = {R.norm(r.cols.get(R.PERIOD_COL)) for rec in records for r in R.rows_of(rec)}
    for code in q.required_caveats:
        if code == "projection":
            meta = " ".join(str((r.get("metadata") or {}).get(k, "")) for r in used_recs for k in ("survey_nm", "tbl_nm")) + \
                   " ".join(r.get("id", "") for r in used_recs) + " ".join(str(r.get("unit", "")) for r in used_recs)
            cols = " ".join(" ".join(map(str, trace.table(r)[0])) + " " +
                            " ".join(str(v) for row in trace.table(r)[1][:3] for v in row) for r in used_recs)
            needed = any(k in meta + cols for k in PROJECTION + ("시나리오", "중위"))
            if needed:
                out.append(Finding("caveat_projection", "stage1", "M6", any(k in shown for k in PROJECTION),
                                   "추계 표를 썼는데 추계 · 전망 · 예측 고지", detail={"code": code}))
        elif code.startswith("missing_period:"):
            y = code.split(":", 1)[1]
            if y not in periods and has_any_value(run):
                out.append(Finding("caveat_missing_period", "stage1", "M6", y in shown and "없" in shown,
                                   f"{y} 자료 없음 고지", detail={"code": code}))
        elif code == "missing_period":
            caveats = [c for c in trace.m6(run).get("caveats") or [] if c.get("source") in ("view_missing", "plan_warning", "view_note")]
            out.append(Finding("caveat_missing_period", "stage2", "M6", bool(caveats) or "없" in shown, "기간 일부 없음 고지",
                               detail={"code": code}))
    return out


def has_any_value(run: dict) -> bool:
    return any(has_value(c) for c in trace.m3(run).get("calc_results") or [])


def format_metrics(run: dict) -> list[Finding]:
    m6 = trace.m6(run)
    out = []
    if not m6:
        return out
    out.append(Finding("method", "metric", "M6", m6.get("method") == "hcx", m6.get("method") or "", detail={"method": m6.get("method")}))
    notes = " ".join(m6.get("notes") or [])
    out.append(Finding("unresolved_placeholder", "metric", "M6", "풀 수 없는" not in notes and "없는 계산 ID" not in notes, ""))
    out.append(Finding("unsupported_number", "metric", "M6", "자리표시자 밖" not in notes, ""))
    out.append(Finding("direction_check", "metric", "M6", "반대" not in notes, ""))
    valued = [c.get("step_id") for c in trace.m3(run).get("calc_results") or [] if has_value(c)
              and str(c.get("step_id", "")).startswith("a")]
    if valued:
        used = set(m6.get("used_step_ids") or [])
        out.append(Finding("step_coverage", "metric", "M6", None, "", detail={"covered": len(used & set(valued)), "total": len(valued)}))
    chart_words = re.findall(r"(그래프|차트|막대|원그래프|꺾은선)", m6.get("answer") or "")
    out.append(Finding("m6_chart_claim", "metric", "M6", not chart_words, ", ".join(chart_words)))
    return out
