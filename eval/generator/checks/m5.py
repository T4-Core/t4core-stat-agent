"""모듈 5 draw_chart: 렌더링 상태 · Chart-Data Fidelity · Spec Lint"""
from eval.generator import trace
from eval.generator.chart_extract import compare
from eval.generator.findings import Finding

PERCENT_UNITS = {"%", "%p"}


def render_states(run: dict) -> dict[str, dict]:
    """render_status(KOS-41) 우선. 11-20 이전 trace 는 drawn[].status 에서 추정 (source=adapter)"""
    mods = trace.mods(run)
    if mods.get("render_status"):
        return {k: {**v, "source": "schema"} for k, v in mods["render_status"].items()}
    out = {}
    planned = {c.get("chart_id") for c in trace.m3(run).get("chart_contents") or []}
    drawn = {d.get("chart_id"): d for d in mods.get("drawn") or []}
    for cid in planned:
        d = drawn.get(cid)
        if d is None:
            out[cid] = {"state": "unresolved", "reason": "render_unresolved", "source": "adapter"}
        else:
            st = str(d.get("status") or "").lower()
            out[cid] = {"state": "drawn" if st in ("ok", "drawn", "success") else "failed", "reason": d.get("reason"),
                        "source": "adapter"}
    return out


def lint(content: dict, drawn: dict, displays: dict) -> list[str]:
    problems = []
    fig = drawn.get("figure") or {}
    layout = fig.get("layout") or {}
    t = content.get("chart_type")
    if t in ("line", "area", "bar", "stacked_bar", "combo", "scatter", "bubble", "dumbbell", "heatmap"):
        val_axis = "xaxis" if (content.get("options") or {}).get("orientation") == "horizontal" or t == "dumbbell" else "yaxis"
        title = ((layout.get(val_axis) or {}).get("title") or {})
        text = title.get("text") if isinstance(title, dict) else title
        if t not in ("heatmap",) and not text:
            problems.append(f"{val_axis} 제목 없음")
        ref = ((content.get("axis") or {}).get("y") or {}).get("display_ref") or (content.get("options") or {}).get("display_ref")
        d = displays.get(ref) or {}
        if d.get("display_unit") in PERCENT_UNITS and text and "%" not in str(text) and \
                "%" not in str((layout.get(val_axis) or {}).get("ticksuffix") or ""):
            problems.append("퍼센트 축에 % 표기 없음")
    if len([tr for tr in fig.get("data") or [] if tr.get("showlegend", True) is not False]) > 1 and \
            layout.get("showlegend") is False:
        problems.append("계열이 여럿인데 범례 없음")
    return problems


def check(run: dict) -> list[Finding]:
    out: list[Finding] = []
    m3 = trace.m3(run)
    displays = m3.get("displays") or {}
    states = render_states(run)
    drawn = {d.get("chart_id"): d for d in trace.mods(run).get("drawn") or []}
    for cid, st in states.items():
        s = st.get("state")
        if s == "skipped":
            out.append(Finding("render_skipped", "metric", "M5", None, st.get("reason") or "", detail=st, source=st["source"]))
        elif s == "unresolved":
            out.append(Finding("render", "metric", "M5", None, "render_unresolved", detail={"chart_id": cid}, source="adapter"))
        else:
            out.append(Finding("render", "stage1", "M5", s == "drawn", st.get("reason") or "", detail={"chart_id": cid},
                               source=st["source"]))
    for content in m3.get("chart_contents") or []:
        cid = content.get("chart_id")
        d = drawn.get(cid)
        if not d or not d.get("figure"):
            continue
        f = compare(content, displays, d)
        out.append(Finding("fidelity", "stage1" if f.ok is False else "metric", "M5", f.ok, f.status,
                           detail={"chart_id": cid, "type": f.chart_type, "missing": f.missing[:10], "extra": f.extra[:10],
                                   "diff": f.diff[:10]}))
        probs = lint(content, d, displays)
        out.append(Finding("spec_lint", "metric", "M5", not probs, "; ".join(probs), detail={"chart_id": cid}))
    for cid, v in (m3.get("validation") or {}).items():
        orig = (v.get("original") or {}).get("chart_type")
        final = v.get("final_chart_type")
        if final is not None:
            out.append(Finding("fallback", "metric", "M5", final == orig, f"{orig} → {final}", detail={"chart_id": cid}))
    return out
