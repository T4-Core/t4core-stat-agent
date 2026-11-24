"""모듈 6 answer_compose + 사용자 응답 문장 (criteria.md 3장 1단계)

  - 금지 문구 (내부 오류 · None · nan)
  - 표시 반올림 (c)층: 계산 요약 표의 결과 문자열 == 평가기 기대 표시값 (display_ref.py, 팀 format_value 와 독립)
  - 결과 단위: 연산별 기대 결과 단위와 표시 단위 (F1 '1세이상' 같은 단위 오류)
  - FINAL binding: numeric_match · semantic_ok (binding.py)
  - 방향 단어, 필수 주의사항, 형식 지표(method · 자리표시자 검사 · Step Coverage)
  - [NEW] claim 단위 · 부호, 요구 자릿수, 근거 가시성(invisible_citation · table_complete), 인과 단정(unsupported_causal)
"""
import re

from eval.generator import binding, claim, trace
from eval.generator import resolve as R
from eval.generator.checks.m3 import AMBIGUOUS, COUNT_LIKE, MISSING, find_value
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
    q_text = run.get("question") or trace.bundle(run).get("original") or ""
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
        if p is MISSING:
            # [NEW] M3 가 이 점을 계산하지 않았다 → 답변에 같은 숫자가 있어도 다른 좌표의 값이다 (binding 위반으로 세지 않고 누락으로)
            out.append(Finding("final_in_answer", "stage2", "M6", False, "결과에 기대 점 없음 (M3 누락)", spec.key, {"value": vs.value}))
            continue
        d = displays.get((c or {}).get("display_ref")) or {}
        # [CHANGED] 이전: display_tolerance(d) if d else 0.5 — 표시 정보가 없으면 비율 · pp 기대값에도 0.5 를 허용오차로 써서
        # 20.0%(0.2) 를 pp 기대값 0.025 와 일치로 판정했다 (v2 S04). 개수형 단위만 0.5, 나머지는 표기 정밀도로만 비교한다
        tol_raw = display_tolerance(d) if d else (0.5 if vs.unit in COUNT_LIKE else 0.0)
        tol = abs(normalize(tol_raw, d.get("source_unit") or (c or {}).get("unit")).value or tol_raw)
        b = binding.check(text, vs.value, vs.unit, vs.binding.model_dump(exclude_none=True) if vs.binding else None,
                          tol=tol, calc=c, records=records, steps=steps, point_key=(p or {}).get("key"),
                          extra_regions=extra_regions(records))
        out.append(Finding("final_in_answer", "stage2", "M6", b.numeric_match, "", spec.key, {"value": vs.value}))
        if b.numeric_match:
            # [CHANGED] 이전: binding 기대가 없어도 semantic_ok=True 인 binding 행을 냈다 (검증하지 않은 100%). 기대가 없으면 행을 내지 않는다 (N/A)
            if vs.binding:
                out.append(Finding("binding", "stage1", "M6", b.semantic_ok, b.detail.get("why", ""), spec.key, b.detail,
                                   source="schema" if c else "text"))
            if b.unit_ok is not None:
                out.append(Finding("claim_unit", "stage1", "M6", b.unit_ok, f"표기 단위 '{b.detail.get('unit')}' / 기대 {vs.unit}",
                                   spec.key, b.detail))
            if b.sign_ok is not None:
                out.append(Finding("claim_sign", "stage1", "M6", b.sign_ok, f"기대 부호 {'음' if vs.value < 0 else '양'}, "
                                   f"표기 {b.detail.get('text')} · 방향어 {b.detail.get('direction')}", spec.key, b.detail))
            digits, scale = (vs.digits, vs.scale) if vs.digits is not None else \
                (asked_digits(q_text), 0.01 if vs.unit in ("ratio", "pp") else 1.0)
            if digits is not None:
                need = 0.5 * 10 ** -digits * scale
                out.append(Finding("required_digits", "stage1", "M6", b.detail.get("resolution", 0) <= need * (1 + 1e-9),
                                   f"요구 소수 {digits}자리, 표기 {b.detail.get('text')}", spec.key, {"digits": digits, **b.detail}))
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


# ── [NEW] claim 보조 ─────────────────────────────────────────────
_DIGIT_WORD = {"첫": 1, "둘": 2, "셋": 3, "넷": 4, "다섯": 5}
_ASK_DIGITS = re.compile(r"소수\s?(?:점\s?)?(?:이하\s?)?(첫|둘|셋|넷|다섯|\d)\s?(?:째|번째)?\s?자리")


def asked_digits(question: str) -> int | None:
    """질문이 정밀도를 요구할 때만 ('소수 셋째 자리까지') 요구 자릿수. 요구가 없으면 표시 규칙(display_round)만 본다"""
    m = _ASK_DIGITS.search(question or "")
    if not m:
        return None
    w = m.group(1)
    return int(w) if w.isdigit() else _DIGIT_WORD[w]


def extra_regions(records: list[dict]) -> tuple[str, ...]:
    """지역 열의 값 중 시도 목록에 없는 이름 (합성 '가상시' 등). claim 지역 레이블 추출에 더한다"""
    names = set()
    for rec in records:
        cols, rows = trace.table(rec)
        for i, c in enumerate(cols):
            if any(h in c for h in R.REGION_HINTS):
                names |= {str(r[i]).strip() for r in rows if i < len(r) and r[i] not in (None, "")}
    return tuple(sorted(n for n in names if not any(n.startswith(x) for x in claim.REGIONS)))


# ── [NEW] 근거 가시성 (provenance 단위) ───────────────────────────
_TOKEN = re.compile(r"\{([\w\-]+(?:\.[\w\-]+)*)\}")
_POINT_TOKEN = re.compile(r"^(?P<step>[\w\-]+?)(?:\.(?P<kind>r|in)(?P<n>\d+))?(?:\.abs)?$")
_SCALES = (1, 100, 0.01, 1e3, 1e-3, 1e4, 1e-4, 1e6, 1e-6, 1e8, 1e-8)     # 표시 배율 (천명 · 만 명 · % ↔ 비율)
_CITE = re.compile(r"\[([^\[\]]{1,80})\]")


def shown_tokens(run: dict) -> tuple[set[str] | None, str]:
    """M6 프롬프트에 실린 자리표시자. 실행 기록(m6_shown_tokens) → 기록된 M6 메시지에서 추출(adapter) → 없음(N/A)"""
    if run.get("m6_shown_tokens") is not None:
        return set(run["m6_shown_tokens"]), "schema"
    msgs = [str(m.get("content", "")) for c in run.get("hcx_calls") or [] for m in c.get("messages") or []
            if isinstance(m, dict) and m.get("role") == "user" and "[계산 결과]" in str(m.get("content", ""))]
    if msgs:
        body = "\n".join(t.split("[계산 결과]", 1)[1].split("[주의사항]", 1)[0] for t in msgs)
        toks = set(_TOKEN.findall(body))
        return toks | {t + ".abs" for t in toks}, "adapter"
    return None, "none"


def _token_value(tok: str, calcs: dict[str, dict]):
    if tok.endswith((".key", ".rank", ".dir")):
        return None
    m = _POINT_TOKEN.match(tok)
    if not m or m.group("step") not in calcs:
        return None
    c = calcs[m.group("step")]
    n = int(m.group("n") or 0)
    if m.group("kind") == "in":
        ins = c.get("inputs") or []
        return ins[n].get("value") if n < len(ins) else None
    v = c.get("value")
    pts = v if isinstance(v, list) else [{"value": v}]
    return pts[n].get("value") if n < len(pts) and isinstance(pts[n], dict) else None


def _key_numbers(tok: str, calcs: dict[str, dict]) -> list[float]:
    """[NEW] 프롬프트에 실린 결과 점 key 레이블 속 숫자 ('0~4세' → 0, 4). 연령 구간 같은 분류 레이블은 인용 수치가 아니다 (v2 C04)"""
    if not tok.endswith(".key"):
        return []
    m = _POINT_TOKEN.match(tok[:-4])
    if not m or m.group("step") not in calcs:
        return []
    c, n = calcs[m.group("step")], int(m.group("n") or 0)
    src = (c.get("inputs") or []) if m.group("kind") == "in" else (c.get("value") if isinstance(c.get("value"), list) else [])
    key = src[n].get("key") if n < len(src) and isinstance(src[n], dict) else None
    return [float(x.replace(",", "")) for v in (key or {}).values() for x in re.findall(r"\d[\d,]*(?:\.\d+)?", str(v))]


def _supported(c: claim.Claim, allowed: list[float]) -> bool:
    x, res = abs(float(c.value)), float(c.resolution)
    return any(abs(x - abs(v) * k) <= res * 1.000001 + 1e-9 * abs(v * k) for v in allowed for k in _SCALES)


def _list_counts(calcs: dict[str, dict]) -> list[float]:
    """목록 결과의 개수 표현('19개 중', '외 14개')에 쓰이는 값: 점 개수와 미리보기 뒤 남은 개수"""
    out = set()
    for c in calcs.values():
        if isinstance(c.get("value"), list):
            n = len(c["value"])
            out |= {float(n)} | {float(n - k) for k in range(1, n)}
    return sorted(out)


def calc_values(calcs: dict[str, dict]) -> list[float]:
    vals = []
    for c in calcs.values():
        v = c.get("value")
        vals += [p.get("value") for p in (v if isinstance(v, list) else [{"value": v}]) if isinstance(p, dict)]
        vals += [i.get("value") for i in c.get("inputs") or []]
    return [float(x) for x in vals if isinstance(x, (int, float)) and not isinstance(x, bool)]


def visibility_checks(q: Question, run: dict) -> list[Finding]:
    """답변 문장이 인용한 숫자는 M6 가 볼 수 있었던 자리표시자 값(또는 질문 속 숫자)이어야 한다 (invisible_citation).
    LLM 이 쓴 답변(method=hcx)만 본다. 템플릿 답변은 코드가 계산 결과 전체에서 쓰므로 가시 문맥 제약이 없다.
    사용자 표의 완전성(table_complete)은 문장 인용과 따로 센다: 프롬프트에 없던 목록 뒷부분이 표에 있으면 정상이다"""
    out = []
    text = trace.answer_text(run)
    calcs = {c.get("step_id"): c for c in trace.m3(run).get("calc_results") or []}
    shown, src = shown_tokens(run)
    if shown is not None and text and trace.m6(run).get("method", "hcx") == "hcx":
        allowed = [float(v) for t in shown if isinstance(v := _token_value(t, calcs), (int, float)) and not isinstance(v, bool)]
        allowed += [float(c.value) for c in claim.numeric_claims(run.get("question") or "")]
        allowed += [x for t in shown for x in _key_numbers(t, calcs)]
        counts = _list_counts(calcs)
        bad = [c.text for c in claim.numeric_claims(text) if c.unit and not _supported(c, allowed)
               and not (c.unit == "개" and float(c.value) in counts)]
        out.append(Finding("invisible_citation", "stage1", "M6", not bad, ", ".join(bad), detail={"unsupported": bad}, source=src))
    if q.citation_labels is not None and text:
        labels = {x.strip() for m in _CITE.finditer(text) for x in m.group(1).split(",") if x.strip()}
        # [CHANGED] 이전: labels - citation_labels — 질문에 있던 대괄호 표기('[합성 자료 검증]')를 답변이 되풀이해도 근거 라벨로 셌다 (v2 S06)
        asked = {m.group(1).strip() for m in _CITE.finditer(run.get("question") or q.question or "")}
        bad = sorted(labels - set(q.citation_labels) - asked)
        out.append(Finding("invisible_citation", "stage1", "M6", not bad, f"보이지 않는 근거 라벨 {bad}" if bad else "",
                           detail={"labels": sorted(labels), "visible": q.citation_labels}, source="label"))
    tables = trace.m6(run).get("tables") or []
    listed = {sid: len([p for p in c["value"] if isinstance(p, dict) and p.get("value") is not None])
              for sid, c in calcs.items() if isinstance(c.get("value"), list)}
    if tables and listed:
        rows = sum(len(t.get("rows") or []) for t in tables)
        need = max(listed.values())
        out.append(Finding("table_complete", "metric", "M6", rows >= need, f"표 행 {rows} / 최대 결과 점 {need}"))
    return out


# ── [NEW] 인과 단정 ──────────────────────────────────────────────
CAUSAL = re.compile(r"때문(?:이다|입니다|이며|에|일|이라)|(?:으)?로 인해|덕분|원인(?:은|이)|효과가?\s?(?:입증|확인)|"
                    r"낳았|초래했|초래하였|이끌었|야기했")
HEDGE = re.compile(r"수 있|보인다|보입니다|가능성|추정|짐작|단정할 수 없|알 수 없")
ARITH = re.compile(r"(?:더했|뺐|나눴|곱했|합산|합계|계산)\S*\s?(?:했\s?)?(?:기\s?)?때문")
# [CHANGED] 이전: r"없어|없기 때문|못했|못합니다|제공되지 않" — '계산이 불가능하기 때문' 같은 계산 불가 설명을 인과 단정으로 셌다 (v2 S04).
# 설명한 사유가 실제 보류 사유와 맞는지는 이 검사의 범위가 아니다 (후속: 보류 사유 대조 검사)
NOTICE = re.compile(r"없어|없기 때문|못했|못합니다|제공되지 않|계산.{0,20}(?:불가능|할 수 없|수 없)")


def _arith_restatement(sent: str, values: list[float]) -> bool:
    """'이는 출생아수가 238,317명이고 사망자수가 358,569명이기 때문입니다' — 계산 입력값을 다시 말하는 산술 설명.
    문장의 숫자가 모두 계산 결과 · 입력 값이면 인과 주장이 아니라 계산 근거 설명으로 본다"""
    cs = [c for c in claim.numeric_claims(sent) if c.unit]
    return bool(cs) and all(_supported(c, values) for c in cs)


def causal_checks(q: Question, run: dict) -> list[Finding]:
    """통계표는 인과를 담지 않는다. 답변이 인과를 단정하면 근거 없는 주장(1단계 실패).
    가능성 표현은 수동 판정(None), 산술 설명 · 보류 고지는 대상이 아니다"""
    out = []
    text = trace.answer_text(run)
    supported = any("causal" in f or "인과" in f for f in q.required_facts)
    values = calc_values({c.get("step_id"): c for c in trace.m3(run).get("calc_results") or []})
    for a, b in claim.sentences(text):
        sent = text[a:b]
        if not CAUSAL.search(sent) or ARITH.search(sent) or NOTICE.search(sent) or _arith_restatement(sent, values):
            continue
        ok = None if HEDGE.search(sent) or supported else False
        out.append(Finding("unsupported_causal", "stage1", "M6", ok, sent.strip()[:120]))
    return out
