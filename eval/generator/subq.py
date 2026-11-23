"""기대 하위 질문 ↔ 출력 하위 질문 대응 (계획 2.2, 2.4.1, D-11)

하위 질문 ID('{query_id}-{n}')는 질의 분석이 실행 중에 정하므로 기대 결과에 쓸 수 없다. 내용(문장 · 계산 입력 항목 · 연산)으로 대응시킨다.
지표는 기대 하위 질문 단위로 센다: 대응되지 않은 기대 = missing, 기대에 없는 출력 = extra.
"""
from dataclasses import dataclass, field

from eval.generator import reason_codes, trace
from eval.generator.resolve import item_match, label_eq, norm
from eval.generator.schema import Question, SubQuestion


@dataclass
class OutSub:
    sid: str
    text: str
    charts: list[dict] = field(default_factory=list)
    calcs: list[dict] = field(default_factory=list)
    withheld: list[dict] = field(default_factory=list)
    source: str = "schema"          # adapter = sub_question_id 없이 내용으로 묶음 (11-20 이전 trace)


@dataclass
class SubResult:
    key: str
    sid: str | None
    status: str                     # matched · missing · ambiguous_match
    observed: str                   # value · hold · missing
    notified: bool
    hold_codes: list[str]
    out: OutSub | None = None
    source: str = "schema"


def has_value(c: dict) -> bool:
    v = c.get("value")
    pts = v if isinstance(v, list) else [{"value": v}]
    return any(isinstance(p, dict) and isinstance(p.get("value"), (int, float)) and not isinstance(p.get("value"), bool)
               for p in pts)


def outputs(run: dict) -> list[OutSub]:
    m3 = trace.m3(run)
    plan = m3.get("chart_plan") or {}
    calcs = [c for c in m3.get("calc_results") or [] if str(c.get("step_id", "")).startswith("a") or c.get("sub_question_id")]
    charts = trace.mods(run).get("charts") or []
    withheld = plan.get("withheld") or []
    subs = [OutSub(sid, text) for sid, text in trace.sub_question_list(run)]
    by = {s.sid: s for s in subs}
    for c in charts:
        for sid in c.get("sub_question_ids") or []:
            if sid in by:
                by[sid].charts.append(c)
    schema_ids = any(c.get("sub_question_id") for c in calcs)
    for c in calcs:
        sid = c.get("sub_question_id")
        if sid in by:
            by[sid].calcs.append(c)
        elif not schema_ids:
            tgt = _adapter_target(c, subs)
            if tgt:
                tgt.calcs.append(c)
                tgt.source = "adapter"
    chart_sid = {c.get("chart_id"): (c.get("sub_question_ids") or [None])[0] for c in charts}
    for w in withheld:
        sid = w.get("sub_question_id") or chart_sid.get(w.get("chart_id"))
        if sid in by:
            by[sid].withheld.append(w)
        elif len(subs) == 1:
            subs[0].withheld.append(w)
    return subs


def _adapter_target(calc: dict, subs: list[OutSub]) -> OutSub | None:
    """sub_question_id 없는 계산: 하위 질문이 하나면 그것, 여럿이면 차트의 View 와 계산의 record_ids 가 겹치는 것"""
    if len(subs) == 1:
        return subs[0]
    rids = set(calc.get("record_ids") or [])
    hits = [s for s in subs if any(rids & set(c.get("view_ids") or []) for c in s.charts)]
    return hits[0] if len(hits) == 1 else None


def _items(o: OutSub) -> list[str]:
    return [i.get("item") or "" for c in o.calcs for i in c.get("inputs") or []] + \
           [str(v) for c in o.calcs for i in c.get("inputs") or [] for v in (i.get("key") or {}).values()]


def _fits(spec: SubQuestion, o: OutSub) -> bool:
    m = spec.match
    hay = [o.text] + _items(o)
    if m.item_any and not any(item_match(w, h) or norm(w) in norm(h) for w in m.item_any for h in hay):
        return False
    if m.region_any and not any(norm(w) in norm(h) or label_eq(w, h) for w in m.region_any for h in hay):
        return False
    if m.op_any and o.calcs and not any(c.get("op") in m.op_any for c in o.calcs):
        return False
    return True


def match(q: Question, run: dict) -> tuple[list[SubResult], list[OutSub]]:
    outs = outputs(run)
    exps = q.sub_questions
    cand = {s.key: [o for o in outs if _fits(s, o)] for s in exps}
    if len(exps) == 1 and len(outs) == 1 and not cand[exps[0].key]:
        cand[exps[0].key] = outs                  # 하나 대 하나면 내용이 덜 맞아도 같은 질문으로 본다 (예: 항목 표기 차이)
    taken: set[str] = set()
    chosen: dict[str, tuple[str, OutSub | None]] = {}
    for s in sorted(exps, key=lambda s: len(cand[s.key])):     # 후보가 적은 기대부터 확정
        free = [o for o in cand[s.key] if o.sid not in taken]
        if len(free) == 1:
            chosen[s.key] = ("matched", free[0])
            taken.add(free[0].sid)
        elif not free:
            chosen[s.key] = ("missing", None)
        else:
            chosen[s.key] = ("ambiguous_match", None)
    for s in exps:                                # 하위 질문에 걸친 계산 (Q12: 출생아수 − 사망자수 를 질의 분석이 둘로 나눔)
        if chosen[s.key][0] == "missing" and s.match.op_any:
            cross = [c for c in trace.m3(run).get("calc_results") or [] if c.get("op") in s.match.op_any
                     and _fits(s, OutSub("", " ".join(i.get("item") or "" for i in c.get("inputs") or []), calcs=[c]))]
            if len(cross) == 1:
                chosen[s.key] = ("matched", OutSub(f"cross:{cross[0].get('step_id')}", "", calcs=cross, source="adapter"))
    results = []
    for s in exps:
        status, o = chosen[s.key]
        results.append(_observe(s, status, o, run))
    contested = {o.sid for s in exps if chosen[s.key][0] == "ambiguous_match" for o in cand[s.key]}
    extra = [o for o in outs if o.sid not in taken | contested and (o.calcs or o.charts)]
    return results, extra


def _notified(run: dict, texts: list[str]) -> bool:
    shown = " ".join([trace.answer_text(run)] + trace.user_caveats(run) +
                     [c.get("text", "") for c in trace.m6(run).get("caveats") or []])
    if any(t and t[:12] in shown for t in texts):
        return True
    return any(k in shown for k in ("못했", "없습니다", "없어", "찾지 못", "제공되지 않", "자료가 없", "대신"))


def _observe(spec: SubQuestion, status: str, o: OutSub | None, run: dict) -> SubResult:
    if o is None:
        return SubResult(spec.key, None, status, "missing", _notified(run, []), [], None)
    reasons = [w.get("text") for w in o.withheld] + [c.get("note") for c in o.calcs if c.get("note")] + \
              (trace.m3(run).get("chart_plan") or {}).get("warnings", []) * (not o.withheld and not any(has_value(c) for c in o.calcs))
    if any(has_value(c) for c in o.calcs):
        observed = "value"
    elif o.withheld or o.calcs:
        observed = "hold"
    else:
        observed = "missing"
    return SubResult(spec.key, o.sid, status, observed, _notified(run, reasons), reason_codes.codes_of(reasons), o, o.source)
