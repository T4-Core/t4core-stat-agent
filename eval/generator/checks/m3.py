"""모듈 3 chart_calculate: 연산 · 피연산자 · 계산 정확도 · 보류 (criteria.md 3장 1단계)

계산 값 비교는 (a)층: 정규형 원값, 원자료 정밀도 기준 허용오차.
"""
from eval.generator import resolve as R
from eval.generator import trace
from eval.generator.binding import region_key
from eval.generator.checks.normalize import close, normalize
from eval.generator.findings import Finding
from eval.generator.schema import SubQuestion, ValueSpec
from eval.generator.status import SubExpect
from eval.generator.subq import SubResult, has_value

COUNT_LIKE = {"명", "건", "가구", "개", "호", "원"}


def tol(vs: ValueSpec) -> tuple[float, float]:
    if vs.atol is not None or vs.rtol is not None:
        return vs.atol or 0.0, vs.rtol or 0.0
    if vs.unit in COUNT_LIKE:
        return 0.5, 0.0
    return 0.0, 1e-6                                 # 비율 · 증감률 같은 파생값: 부동소수 오차만


def points(c: dict) -> list[dict]:
    v = c.get("value")
    if v is None:
        return []
    return [p for p in v if isinstance(p, dict)] if isinstance(v, list) else [{"key": {}, "value": v}]


def _key_eq(want: dict, got: dict) -> bool:
    for k, v in want.items():
        if k not in got or R.norm(got[k]) != R.norm(v):
            if not (k != "시점" and region_key(got.get(k)) == region_key(v)):
                return False
    return True


AMBIGUOUS = {"ambiguous": True}
MISSING = {"missing": True}          # [NEW] 기대 지역의 결과 점이 없음 (다른 지역 점만 있음)


def _region_col(k: str) -> bool:
    """결과 점 key 중 지역 차원 (성별 · 연령 같은 다른 나눔은 아니다 — C03 {시점, 성별} 점을 지역 누락으로 오판)"""
    return any(w in str(k) for w in ("지역", "시도", "시군구", "행정구역"))
DEGENERATE_AGG = {"mean", "sum", "max", "min"}


def degenerate_aggregate(c: dict) -> bool:
    """[NEW] 입력 행이 하나인 aggregate(mean · sum · max · min)는 값이 그 행 원값과 같다 (v2 R18: '평균 매출액' 1행에 mean)"""
    agg = c.get("agg") or (c.get("params") or {}).get("agg")
    return c.get("op") == "aggregate" and agg in DEGENERATE_AGG and len(c.get("inputs") or []) == 1


def _unit_fits(c: dict, vs: ValueSpec) -> bool:
    u = normalize(1.0, c.get("unit")).unit
    if vs.unit in ("ratio", "pp") or u in ("ratio", "pp"):
        return u == vs.unit
    return True


def find_value(calcs: list[dict], vs: ValueSpec, op: str | None, regions: list[str] | None = None) -> tuple[dict | None, dict | None]:
    """기대값에 대응하는 결과 점. key 가 부분 일치하는 점이 여럿이면(share 를 전국 포함 모든 지역에 계산 — 11-23 live 실행 Q28)
    기대 지역으로 좁힌다. 그래도 여럿이고 값이 다르면 (None, AMBIGUOUS) → 수동"""
    pool = [c for c in calcs if has_value(c) and (op is None or c.get("op") == op)] or [c for c in calcs if has_value(c)]
    if op is None:
        # [NEW] 연산을 하나로 정하지 않은 하위 질문(v2 C06: raw + share): 정규형 단위가 같은 결과에서만 찾는다 (20명 ↔ 16.7% 비교 방지)
        pool = [c for c in pool if _unit_fits(c, vs)]
    hits = []
    for c in pool:
        pts = points(c)
        scalar = not isinstance(c.get("value"), list)
        for p in pts:
            if vs.key is None and len(pts) > 1:
                continue
            # [CHANGED] 이전: 단일 값(scalar) 결과도 key 를 요구해 '결과 key {}' 로 실패했다 (v2 R06 share). scalar 는 key 가 없다
            if vs.key is None or scalar or _key_eq(vs.key, p.get("key") or {}):
                hits.append((c, p))
    if len(hits) <= 1:
        return hits[0] if hits else (None, None)
    # [CHANGED] 이전: [vs.binding.region] — v2 binding 은 지역 목록이다
    want = {region_key(r) for r in ((vs.binding.regions() if vs.binding else []) or regions or [])}
    if want:
        narrowed = [(c, p) for c, p in hits if any(region_key(v) in want for k, v in (p.get("key") or {}).items() if k != "시점")]
        if not narrowed and all(any(_region_col(k) for k in (p.get("key") or {})) for _, p in hits):
            # [CHANGED] 이전: narrowed or hits — 기대 지역 점이 없으면 다른 지역 점들로 되돌아가 '모호(수동)' 가 되고 누락이 통과했다
            # (v2 slots C15: M3 가 '나시' 를 빼고 계산). 결과 점에 지역 차원이 있는데 기대 지역이 없으면 누락이다
            return None, MISSING
        hits = narrowed or hits
    if len(hits) == 1 or len({p.get("value") for _, p in hits}) == 1:
        return hits[0]
    return None, AMBIGUOUS


def operand_coords(calc: dict, records: list[dict], steps: list[dict]) -> tuple[list[tuple[str, dict]], bool]:
    out, ok = [], True
    for inp in calc.get("inputs") or []:
        row, _ = R.resolve_input(records, inp, R.select_of(steps, calc.get("step_id"), inp.get("record_id")))
        if row is None:
            ok = False
            continue
        out.append((inp.get("role") or "", row.coord()))
    return out, ok


def _coord_in(want: dict, coords: list[dict]) -> bool:
    for c in coords:
        if want.get("period") and str(c.get("period")) != str(want["period"]):
            continue
        if want.get("item") and not any(R.item_match(want["item"], v) for k, v in c.items() if k != "period"):
            continue                                 # 지표 이름이 분류 열에 있는 View 도 있다
        if want.get("region") and region_key(c.get("region")) != region_key(want["region"]):
            continue
        return True
    return False


def check(spec: SubQuestion, exp: SubExpect, res: SubResult, run: dict) -> list[Finding]:
    out: list[Finding] = []
    if exp.source == "a0" or res.out is None:
        return out
    calcs = res.out.calcs
    records = trace.records_of(run)
    steps = (trace.m3(run).get("chart_plan") or {}).get("answer_steps") or []
    valued = [c for c in calcs if has_value(c)]
    internal = [c for c in calcs if "내부 오류" in (c.get("note") or "")]
    out.append(Finding("plan_valid", "metric", "M3", not internal, "", spec.key))
    if exp.expect != "answer" or not valued:
        return out
    op = spec.m3.op
    if op:
        ops = [c.get("op") for c in valued]
        ok = op in ops or bool(spec.match.op_any and set(ops) & set(spec.match.op_any))
        degenerate = [c for c in valued if degenerate_aggregate(c)]
        if not ok and op == "raw" and degenerate and all(c.get("op") == "raw" or degenerate_aggregate(c) for c in valued):
            # [CHANGED] 이전: 단일 입력 aggregate 도 기대 raw 와 다르면 1단계 실패. 결과는 원값과 같으므로 판정은 통과,
            # 계획 품질(이미 집계된 행에 다시 집계)은 지표로만 남긴다
            ok = True
        out.append(Finding("operation", "stage1", "M3", ok, f"연산 {ops} / 기대 {op}", spec.key))
        if degenerate:
            out.append(Finding("degenerate_aggregate", "metric", "M3", False,
                               f"입력 1행 집계 {[(c.get('step_id'), c.get('agg')) for c in degenerate]}", spec.key))
    if spec.m3.operands or spec.m3.denominator:
        target = next((c for c in valued if c.get("op") == op), valued[0])
        coords, resolved = operand_coords(target, records, steps)
        allc = [c for _, c in coords]
        wants = [o.model_dump(exclude_none=True) for o in spec.m3.operands]
        if spec.m3.denominator:
            wants.append(spec.m3.denominator.model_dump(exclude_none=True))
        if not resolved:
            out.append(Finding("operand", "stage1", "M3", None, "원본 행 복원 실패 (operand_unresolved)", spec.key, source="adapter"))
        else:
            missing = [w for w in wants if not _coord_in(w, allc)]
            out.append(Finding("operand", "stage1", "M3", not missing, f"없는 피연산자 {missing}", spec.key,
                               {"inputs": allc}))
    for vs in spec.values:
        c, p = find_value(valued, vs, op, spec.match.region_any)
        if p is AMBIGUOUS:
            out.append(Finding("execution", "stage1", "M3", None, f"기대값 {vs.key} 에 맞는 결과 점이 여럿 (지역으로 좁힐 수 없음)", spec.key))
            continue
        if p is None or p is MISSING:
            same_op = [x for x in valued if x.get("op") == op] or ([x for x in valued if _unit_fits(x, vs)] if op is None else valued)
            pts = [pt for x in same_op for pt in points(x)]
            if op is None and not pts:
                # v2 다중 연산 하위 질문: 이 claim 의 단위로 낸 결과가 없다 (C06 원값 20명을 계산하지 않고 구성비만 냄) → 완전성 문제
                out.append(Finding("execution_point", "stage2", "M3", False, f"기대 단위 {vs.unit} 의 결과 없음", spec.key))
            elif vs.key and len(pts) == 1:
                # 값이 하나인 결과(extreme 등)의 key 가 기대와 다르다 = 다른 대상을 답으로 냄 (기준선 3회차 Q33: 1980년)
                out.append(Finding("execution", "stage1", "M3", False, f"결과 key {pts[0].get('key')} / 기대 {vs.key}", spec.key))
            elif vs.key and pts:
                out.append(Finding("execution_point", "stage2", "M3", False, f"기대 점 {vs.key} 이 결과에 없음", spec.key))
            else:
                out.append(Finding("execution", "stage1", "M3", None, f"기대값 {vs.key or ''} 에 대응하는 결과 없음", spec.key))
            continue
        n = normalize(p.get("value"), c.get("unit"))
        atol, rtol = tol(vs)
        ok = n.unit == vs.unit and close(n.value, vs.value, atol, rtol) if vs.unit in ("ratio", "pp") or n.unit in ("ratio", "pp") \
            else close(n.value, vs.value, atol, rtol)
        out.append(Finding("execution", "stage1", "M3", ok, f"{n.value} {n.unit} / 기대 {vs.value} {vs.unit}", spec.key,
                           {"observed": n.value, "observed_unit": n.unit, "expected": vs.value, "key": vs.key}))
    return out


def hold_grounded(res: SubResult, run: dict, spec: SubQuestion | None = None) -> bool:
    """기대 hold 인데 값을 냈을 때 근거가 있는가
      - 입력이 모두 원본 행으로 복원된다
      - share 의 분자 · 분모가 다른 행이다 (Q05 1회차 100.0%)
      - 입력 행의 지표가 질문한 지표다 (Q08 1회차: 출생성비 표로 인구 순위)"""
    records = trace.records_of(run)
    steps = (trace.m3(run).get("chart_plan") or {}).get("answer_steps") or []
    asked = spec.match.item_any if spec else []
    for c in res.out.calcs if res.out else []:
        if not has_value(c):
            continue
        rows = []
        for inp in c.get("inputs") or []:
            row, _ = R.resolve_input(records, inp, R.select_of(steps, c.get("step_id"), inp.get("record_id")))
            if row is None:
                return False
            rows.append(row)
        if c.get("op") == "share" and len(rows) >= 2 and rows[0].cols == rows[1].cols:
            return False
        if asked and not all(any(R.item_match(a, v) for a in asked for k, v in r.cols.items() if k != R.PERIOD_COL)
                             for r in rows):
            return False
    return True


def asked_indicator(q, run: dict) -> list[Finding]:
    """값을 낸 질문용 계산이 질문한 지표의 행으로 계산됐는가 (1단계, 출력한 모든 내용. 기대 하위 질문과 대응되지 않은 출력 포함)
    11-23 live 실행 Q32: 질의 분석이 지역을 지표로 나눠 '항목=서울' 인 다른 표의 값을 '결혼 건수' 로 답함"""
    asked = [w for s in q.sub_questions for w in s.match.item_any]
    if not asked:
        return []
    records = trace.records_of(run)
    steps = (trace.m3(run).get("chart_plan") or {}).get("answer_steps") or []
    out = []
    for c in trace.m3(run).get("calc_results") or []:
        if not has_value(c) or not (str(c.get("step_id", "")).startswith("a") or c.get("sub_question_id")):
            continue
        rows, unresolved = [], False
        for inp in c.get("inputs") or []:
            row, _ = R.resolve_input(records, inp, R.select_of(steps, c.get("step_id"), inp.get("record_id")))
            if row is None:
                unresolved = True
                continue
            rows.append(row)
        if not rows:
            continue
        bad = [r for r in rows if not any(R.item_match(a, v) for a in asked for k, v in r.cols.items() if k != R.PERIOD_COL)]
        if bad:
            out.append(Finding("asked_indicator", "stage1", "M3", False,
                               f"{c.get('step_id')}: 질문한 지표({', '.join(asked)})가 아닌 행으로 계산 {list(bad[0].cols.values())[:4]}",
                               detail={"step_id": c.get("step_id")}))
        elif unresolved:
            out.append(Finding("asked_indicator", "stage1", "M3", None, f"{c.get('step_id')}: 일부 입력 행 복원 실패",
                               detail={"step_id": c.get("step_id")}, source="adapter"))
    return out


def unit_semantic(run: dict) -> list[Finding]:
    """표 메타데이터 단위와 지표 이름이 어긋나는 경우 (Q30: 혼인건수인데 '명'). 메타데이터 기준이라 자동 판정하지 않는다 → 수동"""
    out = []
    for c in trace.m3(run).get("calc_results") or []:
        if not has_value(c):
            continue
        items = " ".join(i.get("item") or "" for i in c.get("inputs") or [])
        unit = c.get("unit")
        if "건수" in items and unit == "명" or "인구" in items and unit == "건":
            out.append(Finding("unit_semantic", "stage1", "data", None, f"지표 '{items[:20]}' 의 단위가 '{unit}'",
                               detail={"step_id": c.get("step_id")}, source="text"))
    return out
