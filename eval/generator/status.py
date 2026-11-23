"""기대 상태 결정 (criteria.md 2장)

조건 술어는 입력 스냅샷만 본다: 하위 질문 답변 가능성은 ViewSet 의 Record, A0 기대 라벨은 ViewSet + analysis 메모.
Generator 출력과 analysis.status 는 기대를 정하는 데 쓰지 않는다.
"""
import re
from dataclasses import dataclass, field

from eval.generator import resolve as R
from eval.generator import trace
from eval.generator.schema import Question, SubQuestion

UNKNOWN_INDICATOR = re.compile(r"\[지표\]\s*'(.+?)'\s*를 CSV·사전에서 찾지 못함")   # qa_semantic._UNKNOWN_INDICATOR 와 같은 메모 형식
A0_REASON = {"stop_no_data": "no_data", "stop_indicator_not_found": "item_mismatch", "stop_status": "no_data"}


@dataclass
class SubExpect:
    key: str
    expect: str                    # answer · hold
    hold_reason: str | None
    tags: list[str] = field(default_factory=list)
    source: str = "predicate"      # predicate · a0 · unresolved


# ── 조건 술어 ────────────────────────────────────────────────────
def _view_has_row(records, item=None, period=None, region=None) -> R.Pred:
    rows = R.find(records, {"item": item, "period": period, "region": region})
    if not rows:
        return R.Pred(False, "missing_operand" if (region or period) else "item_mismatch")
    if not any(R.is_number(r.value) for r in rows):
        return R.Pred(False, "missing_value")
    return R.Pred(True)


def _view_has_rows(records, item, min_periods=1) -> R.Pred:
    best = 0
    for rec in records:
        ps = {R.norm(r.cols.get(R.PERIOD_COL)) for r in R.rows_of(rec)
              if R.is_number(r.value) and (not item or any(R.item_match(item, v) for v in r.cols.values()))}
        best = max(best, len(ps))
    if best == 0:
        return R.Pred(False, "item_mismatch")
    reason = None if best >= min_periods else ("single_period" if best == 1 else "missing_period")
    return R.Pred(best >= min_periods, reason, detail={"periods": best})


TOTALS = {"계", "전체", "합계", "총계", "소계"}


def _view_has_categories(records, dim, min=2, item=None) -> R.Pred:  # noqa: A002
    """열 이름에 dim 이 들어간 분류에서 합계가 아닌 서로 다른 값이 min 개 이상 (순위 · 비교 질문)"""
    best = 0
    for rec in records:
        cols, _ = trace.table(rec)
        dcols = [c for c in cols if dim in c]
        for c in dcols:
            vals = {R.norm(r.cols.get(c)) for r in R.rows_of(rec) if R.is_number(r.value)
                    and (not item or any(R.item_match(item, v) for k, v in r.cols.items() if k != c))}
            vals = {v for v in vals if v and v not in TOTALS and not v.endswith("_계") and v != "전국"}
            best = max(best, len(vals))
    return R.Pred(best >= min, None if best >= min else ("item_mismatch" if best == 0 else "missing_operand"),
                  detail={"categories": best})


def _view_note_has(records, text) -> R.Pred:
    for rec in records:
        cols, _ = trace.table(rec)
        notes = [n.get("text", "") if isinstance(n, dict) else str(n) for n in rec.get("notes") or []]
        if any(text in c for c in cols) or any(text in n for n in notes):
            return R.Pred(True)
    return R.Pred(False, "item_mismatch")


def evaluate(when: dict, records: list[dict], spec: SubQuestion) -> R.Pred:
    (name, arg), = when.items()
    if name == "operands_valid":
        return R.operands_valid(records, arg.get("operands") or [], arg.get("denominator"),
                                op=arg.get("op") or spec.m3.op, result_unit=arg.get("result_unit") or spec.m3.result_unit)
    if name == "view_has_row":
        return _view_has_row(records, **arg)
    if name == "view_has_rows":
        return _view_has_rows(records, **arg)
    if name == "view_note_has":
        return _view_note_has(records, arg)
    if name == "view_has_categories":
        return _view_has_categories(records, **arg)
    raise ValueError(f"모르는 조건 술어: {name}")


def legacy_unresolved(records: list[dict]) -> bool:
    return any(trace.truncated(r) for r in records)


def sub_expect(spec: SubQuestion, records: list[dict]) -> SubExpect:
    for rule in spec.answerable_when:
        if rule.when is None:
            return SubExpect(spec.key, rule.expect, rule.hold_reason if rule.hold_reason != "from_predicate" else None)
        p = evaluate(rule.when, records, spec)
        if p.ok:
            return SubExpect(spec.key, rule.expect, None if rule.expect == "answer" else rule.hold_reason, p.tags)
        if "manual" in p.tags:
            return SubExpect(spec.key, "hold", p.reason, ["manual"], "unresolved")
        nxt = spec.answerable_when[spec.answerable_when.index(rule) + 1:]
        if nxt and nxt[0].when is None:
            r = nxt[0]
            reason = p.reason if r.hold_reason in (None, "from_predicate") else r.hold_reason
            tags = list(p.tags)
            if not p.ok and legacy_unresolved(records):
                tags.append("status_unresolved")
            return SubExpect(spec.key, r.expect, reason if r.expect == "hold" else None, tags)
    return SubExpect(spec.key, "answer", None, ["no_rule_matched"])


# ── A0 기대 라벨 (2.2.2) ─────────────────────────────────────────
def a0_label(run: dict) -> str:
    vs = run.get("viewset")
    records = trace.records_of(run)
    if vs is not None and vs.get("status") not in (None, "ok"):
        return "stop_status"
    if not records:
        return "stop_no_data"
    notes = (run.get("analysis") or {}).get("notes") or []
    unknown = {m.group(1) for n in notes if (m := UNKNOWN_INDICATOR.search(str(n)))}
    if not unknown:
        return "continue"
    units = [u for u in (vs or {}).get("units") or [] if not (u.get("filters") or {}).get("역할")]
    wants = [((u.get("filters") or {}).get("지표") or []) for u in units] or [list(unknown)]
    if not all(w and set(w) <= unknown for w in wants):
        return "continue"
    names = {n for w in wants for n in w}
    for rec in records:                     # QA 의 used.지표 플래그가 아니라 Record 항목 열을 직접 본다 (자기 참조 방지)
        for r in R.rows_of(rec):
            if any(R.item_match(n, v) for n in names for v in r.cols.values()):
                return "continue"
    return "stop_indicator_not_found"


def expectations(q: Question, run: dict) -> tuple[str, list[SubExpect]]:
    """(A0 기대 라벨, 하위 질문 기대). A0 가 stop_* 이면 하위 질문 기대 사유를 A0 사유로 덮는다"""
    if q.scope == "out":
        return "out_of_scope", []
    # slim trace 에는 ViewSet 전체가 없어(Record 는 모듈에 넘긴 것만) A0 기대를 정할 수 없다 → n/a
    label = a0_label(run) if run.get("viewset") is not None else "n/a"
    records = trace.records_of(run)
    if label.startswith("stop_"):
        return label, [SubExpect(s.key, "hold", A0_REASON[label], [], "a0") for s in q.sub_questions]
    return label, [sub_expect(s, records) for s in q.sub_questions]


def question_expect(q: Question, subs: list[SubExpect]) -> str:
    if q.scope == "out":
        return "out_of_scope"
    kinds = {s.expect for s in subs}
    if kinds == {"answer"}:
        return "answer"
    if kinds == {"hold"}:
        return "hold"
    return "partial" if kinds else "answer"
