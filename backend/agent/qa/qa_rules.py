"""스키마 검사 다음의 QA 규칙 — 허용값 · 비어 있으면 안 되는 값 · id 짝 (qa 설계.md 5장)

  rule_issues(point, raw, ctx) → [(loc, kind, message, value)]
    raw  스키마 검사를 통과한 값 (dict)
    ctx  id 짝을 볼 참조 목록 (qa_nodes 가 state 에서 만든다). 없는 키는 그 짝을 보지 않는다
      view_ids     모듈 2 입력 View 의 record id        (M2-out)
      record_ids   모듈 3 · 6 입력 records 의 id         (M3-in · M3-out · M6-in · M6-out)
      sub_ids      QueryBundle 의 하위 질문 id           (M3-in)
      chart_ids    모듈 3 이 받은 차트 id                (M3-out)
      drawn_ids    그릴 수 있는 차트 id (내용 + 겹침)     (M5-out)
      step_ids     calc_results 의 step_id              (M6-out)
      withheld_ids 모듈 6 에 넘긴 withheld 의 하위 질문 · 차트 ID (M6-out: 보류 사유 caveat 의 ref)
      role_unit_ids 질문에서 뺀 역할 단위(분모·조건)의 id    (M3-in · M6-in: role_links.unit_id)
    새 필드의 짝 (KOS-26 · KOS-38)
      role_links[]  unit_id → 뺀 역할 단위 · supports → 남은 하위 질문 · record_ids → records
      withheld[]    sub_question_id → 하위 질문 · chart_id → 차트
      질문용 계산    answer_steps[] · calc_results[] 의 sub_question_id → 하위 질문 (차트 단계는 None 이라 보지 않음)
  kind: enum (허용값) · empty (비어 있음) · ref (id 짝)

  허용값은 '스키마에 있는 값 목록' 만 쓴다. 필드가 그냥 str 이지만 같은 뜻의 Literal 이 다른 스키마에 있으면 그것을 적용한다.
  설명 글에만 적힌 목록(Note.type · Filters.의도 등)은 쓰지 않는다. 내부 구조(행 길이 · encoding 열)는 보지 않는다.
"""
import re
from typing import Any, get_args

from backend.schemas.chart import ChartType, Measure
from backend.schemas.query import Intent

INTENTS = set(get_args(Intent))
MEASURES = set(get_args(Measure)) | {"범위 밖"}          # 모듈 2 measure = 모듈 3 Measure + '범위 밖'
CHART_TYPES = set(get_args(ChartType))
PLAN_REF = "plan"                                       # 모듈 6 caveat(source=plan_warning) 의 ref


def _requirement_codes():
    """모듈 3 검사기(chart_calculate.validate)가 판정할 수 있는 조건 이름"""
    from backend.agent.chart_calculate import validate
    return set(validate._CHECKS), validate._COUNT


def _blank(v) -> bool:
    return v is None or (isinstance(v, (str, list, dict, tuple)) and len(v) == 0) or (isinstance(v, str) and not v.strip())


class _R:
    def __init__(self, ctx):
        self.ctx, self.out = ctx or {}, []

    def add(self, loc, kind, msg, value=None):
        self.out.append((tuple(loc), kind, msg, value))

    def enum(self, loc, v, allowed, what, none_ok=True):
        if v is None:
            if not none_ok:
                self.add(loc, "enum", f"{what}: None 은 허용되지 않음")
        elif v not in allowed:
            self.add(loc, "enum", f"{what} 허용값 밖", v)

    def nonempty(self, loc, v, what):
        if _blank(v):
            self.add(loc, "empty", f"{what} 이(가) 비어 있음", v)

    def ref(self, loc, v, key, what):
        have = self.ctx.get(key)
        if have is not None and v is not None and v not in have:
            self.add(loc, "ref", f"{what} 가 가리키는 것이 없음", v)

    def refs(self, loc, vs, key, what):
        for k, v in enumerate(vs or []):
            self.ref((*loc, k), v, key, what)

    def requirements(self, loc, codes):
        checks, count = _requirement_codes()
        for k, code in enumerate(codes or []):
            if code not in checks and not count.match(str(code)):
                self.add((*loc, k), "enum", "모듈 3 이 모르는 조건 이름", code)


# ── 지점별 ──────────────────────────────────────────────────────
def _a0(r: _R, raw):
    vb, vs = raw.get("view_bundle") or {}, raw.get("viewset") or {}
    r.enum(("view_bundle", "intent"), vb.get("intent"), INTENTS, "intent")
    if vs.get("status") == "ok":
        r.nonempty(("viewset", "units"), vs.get("units"), "units")
        r.nonempty(("viewset", "records"), vs.get("records"), "records")


def _m2in(r: _R, raw):
    r.enum(("query_bundle", "intent"), (raw.get("query_bundle") or {}).get("intent"), INTENTS, "intent")


def _m2out(r: _R, raw):
    plan = raw.get("chart_plan") or {}
    seen = set()
    for i, c in enumerate(plan.get("charts") or []):
        loc = ("chart_plan", "charts", i)
        r.nonempty((*loc, "chart_id"), c.get("chart_id"), "chart_id")
        if c.get("chart_id") in seen:
            r.add((*loc, "chart_id"), "ref", "chart_id 가 겹침", c.get("chart_id"))
        seen.add(c.get("chart_id"))
        r.enum((*loc, "measure"), c.get("measure"), MEASURES, "measure")
        for k, f in enumerate(c.get("fallback_charts") or []):
            r.enum((*loc, "fallback_charts", k), f, CHART_TYPES, "fallback_charts", none_ok=False)
        r.requirements((*loc, "requirements"), c.get("requirements"))
        if c.get("chart_type") is not None:
            r.nonempty((*loc, "view_ids"), c.get("view_ids"), "view_ids (차트가 있는데)")
        r.refs((*loc, "view_ids"), c.get("view_ids"), "view_ids", "view_ids")
    ids = {c.get("chart_id") for c in plan.get("charts") or []}
    for j, o in enumerate(plan.get("overlays") or []):
        loc = ("chart_plan", "overlays", j)
        r.nonempty((*loc, "overlay_id"), o.get("overlay_id"), "overlay_id")
        for k, cid in enumerate(o.get("charts") or []):
            if cid not in ids:
                r.add((*loc, "charts", k), "ref", "겹쳐 그릴 차트가 charts 에 없음", cid)


def _m3in(r: _R, raw):
    r.enum(("query_bundle", "intent"), (raw.get("query_bundle") or {}).get("intent"), INTENTS, "intent")
    if raw.get("charts"):
        r.nonempty(("records",), raw.get("records"), "records (차트가 있는데)")
    seen = set()
    for i, c in enumerate(raw.get("charts") or []):
        loc = ("charts", i)
        r.nonempty((*loc, "chart_id"), c.get("chart_id"), "chart_id")
        if c.get("chart_id") in seen:
            r.add((*loc, "chart_id"), "ref", "chart_id 가 겹침", c.get("chart_id"))
        seen.add(c.get("chart_id"))
        r.requirements((*loc, "requirements"), c.get("requirements"))
        r.refs((*loc, "view_ids"), c.get("view_ids"), "record_ids", "view_ids")
        r.refs((*loc, "sub_question_ids"), c.get("sub_question_ids"), "sub_ids", "sub_question_ids")
    _role_links(r, raw.get("role_links"))


def _role_links(r: _R, links):
    for i, l in enumerate(links or []):
        loc = ("role_links", i)
        r.ref((*loc, "unit_id"), l.get("unit_id"), "role_unit_ids", "role_links.unit_id")
        r.refs((*loc, "supports"), l.get("supports"), "sub_ids", "role_links.supports")
        r.refs((*loc, "record_ids"), l.get("record_ids"), "record_ids", "role_links.record_ids")


def _withheld(r: _R, items, prefix):
    for i, w in enumerate(items or []):
        loc = (*prefix, i)
        r.ref((*loc, "sub_question_id"), w.get("sub_question_id"), "sub_ids", "withheld.sub_question_id")
        r.ref((*loc, "chart_id"), w.get("chart_id"), "chart_ids", "withheld.chart_id")


def _display_refs(r: _R, loc, ref, displays):
    if ref is not None and ref not in displays:
        r.add(loc, "ref", "display_ref 가 displays 에 없음", ref)


def _calcs(r: _R, calcs, displays, prefix=("calc_results",)):
    for i, c in enumerate(calcs or []):
        loc = (*prefix, i)
        r.nonempty((*loc, "step_id"), c.get("step_id"), "step_id")
        r.ref((*loc, "sub_question_id"), c.get("sub_question_id"), "sub_ids", "calc_results.sub_question_id")
        _display_refs(r, (*loc, "display_ref"), c.get("display_ref"), displays)
        r.refs((*loc, "record_ids"), c.get("record_ids"), "record_ids", "record_ids")
        for k, inp in enumerate(c.get("inputs") or []):
            r.ref((*loc, "inputs", k, "record_id"), inp.get("record_id"), "record_ids", "inputs.record_id")


def _m3out(r: _R, raw):
    displays = raw.get("displays") or {}
    for i, c in enumerate(raw.get("chart_contents") or []):
        loc = ("chart_contents", i)
        for f in ("chart_id", "title", "columns", "rows", "encoding"):
            r.nonempty((*loc, f), c.get(f), f)
        r.ref((*loc, "chart_id"), c.get("chart_id"), "chart_ids", "chart_id")
        r.refs((*loc, "record_ids"), c.get("record_ids"), "record_ids", "record_ids")
        for ax, spec in (c.get("axis") or {}).items():
            _display_refs(r, (*loc, "axis", ax, "display_ref"), (spec or {}).get("display_ref"), displays)
    cp = raw.get("chart_plan") or {}
    for i, p in enumerate(cp.get("plans") or []):
        r.ref(("chart_plan", "plans", i, "chart_id"), p.get("chart_id"), "chart_ids", "plans.chart_id")
        for k, s in enumerate(p.get("steps") or []):
            _display_refs(r, ("chart_plan", "plans", i, "steps", k, "display_ref"), s.get("display_ref"), displays)
    for k, s in enumerate(cp.get("answer_steps") or []):
        r.nonempty(("chart_plan", "answer_steps", k, "step_id"), s.get("step_id"), "answer_steps.step_id")
        r.ref(("chart_plan", "answer_steps", k, "sub_question_id"), s.get("sub_question_id"), "sub_ids",
              "answer_steps.sub_question_id")
        _display_refs(r, ("chart_plan", "answer_steps", k, "display_ref"), s.get("display_ref"), displays)
    _withheld(r, cp.get("withheld"), ("chart_plan", "withheld"))
    for key in (raw.get("validation") or {}):
        r.ref(("validation", key), key, "chart_ids", "validation 의 chart_id")
    _calcs(r, raw.get("calc_results"), displays)


def _m5out(r: _R, raw):
    for i, x in enumerate(raw.get("results") or []):
        loc = ("results", i)
        r.nonempty((*loc, "chart_id"), x.get("chart_id"), "chart_id")
        r.ref((*loc, "chart_id"), x.get("chart_id"), "drawn_ids", "chart_id")
        if x.get("status") == "drawn" and x.get("figure") is None:
            r.add((*loc, "figure"), "empty", "status=drawn 인데 figure 가 없음")


def _m6in(r: _R, raw):
    _calcs(r, raw.get("calc_results"), raw.get("displays") or {})
    for k, s in enumerate(raw.get("answer_steps") or []):
        r.ref(("answer_steps", k, "sub_question_id"), s.get("sub_question_id"), "sub_ids", "answer_steps.sub_question_id")
    _withheld(r, raw.get("withheld"), ("withheld",))
    _role_links(r, raw.get("role_links"))


def _m6out(r: _R, raw):
    r.nonempty(("answer",), raw.get("answer"), "answer")
    r.refs(("used_step_ids",), raw.get("used_step_ids"), "step_ids", "used_step_ids")
    for i, t in enumerate(raw.get("tables") or []):
        loc = ("tables", i)
        r.nonempty((*loc, "table_id"), t.get("table_id"), "table_id")
        r.nonempty((*loc, "columns"), t.get("columns"), "columns")
        r.refs((*loc, "step_ids"), t.get("step_ids"), "step_ids", "step_ids")
        r.refs((*loc, "record_ids"), t.get("record_ids"), "record_ids", "record_ids")
    refs = (r.ctx.get("record_ids") or set()) | (r.ctx.get("step_ids") or set())
    if "record_ids" in r.ctx or "step_ids" in r.ctx:
        for i, c in enumerate(raw.get("caveats") or []):
            # 계산 보류 사유(source=plan_warning)의 ref (answer_compose/caveats.py):
            #   withheld 가 있으면 그 범위 = 하위 질문 ID · 차트 ID (KOS-38), 범위를 모르는 사유는 'plan'.
            #   스키마 설명(Record.id 또는 step_id)에는 빠져 있음 → 모듈 6 담당자에게 알릴 내용 (qa 설계.md 5장)
            if c.get("source") == "plan_warning" and (
                    c.get("ref") == PLAN_REF or c.get("ref") in (r.ctx.get("withheld_ids") or set())):
                continue
            if c.get("ref") not in refs:
                r.add(("caveats", i, "ref"), "ref", "caveat 가 가리키는 record · step 이 없음", c.get("ref"))


RULE_FUNCS = {"A0": _a0, "M2-in": _m2in, "M2-out": _m2out, "M3-in": _m3in, "M3-out": _m3out,
              "M5-out": _m5out, "M6-in": _m6in, "M6-out": _m6out}


def rule_issues(point: str, raw: Any, ctx: dict | None = None) -> list[tuple]:
    fn = RULE_FUNCS.get(point)
    if fn is None or not isinstance(raw, dict):
        return []
    r = _R(ctx)
    fn(r, raw)
    return r.out
