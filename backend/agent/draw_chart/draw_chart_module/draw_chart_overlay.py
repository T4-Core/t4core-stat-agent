"""
모듈 5 겹쳐 그리기 — 2번 chart_plan.overlays 의 두 차트를 그림 하나로 합쳐 3번째 차트를 더한다

  apply_overlays(results, jobs, overlays) → results (원래 차트 그대로 + 합친 차트를 두 차트 뒤에)

  - 원래 두 차트(c1, c2)는 그대로 두고, 합친 차트(chart_id "c1+c2", merged_from ["c1", "c2"])를 더한다
  - 두 차트가 모두 drawn 이고 x 값이 정확히 같을 때만 합친다. 아니면 합치지 않고 첫 차트 경고에 이유를 남긴다
  - 합친 ChartContent 를 만들어 기존 렌더러(draw_chart)로 그린다
      combo : 큰 값 막대(y, 왼쪽 축) + 작은 값 선(y2, 오른쪽 축)  ← overlays[].axes
      lines : line 하나에 선 2개   /   bars : 묶음 막대 하나
  3번 모듈은 이 표시를 모른다 (2번이 chart_plan.overlays 에 남기고 5번만 읽는다).
"""
from backend.schemas.chart import AxisSpec, ChartContent

from .draw_chart_prepare import display_refs_of
from .draw_chart_schema import DRAWN, DrawJob
from .draw_chart_tool import draw_chart

ITEM, VALUE = "항목", "값"


def _label(c):
    """차트의 지표 이름: 계열 값이 하나면 그 값 ('혼인건수'), 아니면 y 축 이름, 없으면 제목"""
    s = c.encoding.get("series")
    if s and s in c.columns:
        vals = list(dict.fromkeys(str(r[c.columns.index(s)]) for r in c.rows))
        if len(vals) == 1:
            return vals[0]
    y = c.axis.get("y")
    return (y.label if y and y.label else None) or c.title


def _points(c):
    """(x 열 이름, [(x 값, y 값), …])"""
    x, y = c.encoding.get("x"), c.encoding.get("y")
    if not x or not y or x not in c.columns or y not in c.columns:
        raise ValueError(f"{c.chart_id}: x·y 역할이 없는 차트")
    xi, yi = c.columns.index(x), c.columns.index(y)
    return x, [(str(r[xi]), r[yi]) for r in c.rows]


def merge_content(ov, ca, cb):
    """overlay 하나 + 두 ChartContent → 합친 ChartContent (x 값이 다르면 ValueError)"""
    xa, pa = _points(ca)
    _, pb = _points(cb)
    xs_a, xs_b = list(dict.fromkeys(x for x, _ in pa)), list(dict.fromkeys(x for x, _ in pb))
    if xs_a != xs_b:
        raise ValueError(f"두 차트의 x 값이 다름 ({len(xs_a)}개 · {len(xs_b)}개)")
    la, lb = _label(ca), _label(cb)
    if la == lb:
        la, lb = ca.title, cb.title
    rows = [[x, la, v] for x, v in pa] + [[x, lb, v] for x, v in pb]
    xspec = ca.axis.get("x") or AxisSpec(label=xa)
    title = ca.title.replace(la, f"{la}·{lb}") if la in ca.title else f"{la} · {lb}"

    if ov["mode"] == "combo":
        y_id = next((k for k, v in (ov.get("axes") or {}).items() if v == "y"), ca.chart_id)
        (cy, ly), (cy2, ly2) = ((ca, la), (cb, lb)) if y_id == ca.chart_id else ((cb, lb), (ca, la))
        # 원래 차트의 축 범위(min · max)는 그 차트 값 기준이라 지운다 → 합친 차트의 기준선 규칙(막대는 0 포함)이 적용됨
        ya = (cy.axis.get("y") or AxisSpec()).model_copy(update={"label": ly, "min": None, "max": None})
        yb = (cy2.axis.get("y") or AxisSpec()).model_copy(update={"label": ly2, "min": None, "max": None})
        return ChartContent(chart_id=ov["overlay_id"], chart_type="combo", measure=ca.measure, title=title,
                            encoding={"x": xa, "y": VALUE, "y2": VALUE, "series": ITEM},
                            axis={"x": xspec, "y": ya, "y2": yb},
                            options={"marks": {"y": "bar", "y2": "line"}, "series_axis": {ly: "y", ly2: "y2"}},
                            columns=[xa, ITEM, VALUE], rows=rows,
                            record_ids=list(dict.fromkeys(ca.record_ids + cb.record_ids)), warnings=[])

    # 한쪽 차트의 축 범위로 고정하면 다른 쪽 값이 화면 밖으로 나갈 수 있어 min · max 를 지운다
    yspec = (ca.axis.get("y") or AxisSpec()).model_copy(update={"label": f"{la} · {lb}", "min": None, "max": None})
    return ChartContent(chart_id=ov["overlay_id"], chart_type="line" if ov["mode"] == "lines" else "bar",
                        measure=ca.measure, title=title, encoding={"x": xa, "y": VALUE, "series": ITEM},
                        axis={"x": xspec, "y": yspec}, options={} if ov["mode"] == "lines" else {"orientation": "vertical"},
                        columns=[xa, ITEM, VALUE], rows=rows,
                        record_ids=list(dict.fromkeys(ca.record_ids + cb.record_ids)), warnings=[])


def _color(res):
    """그린 차트의 첫 trace 색 (선이면 선 색, 막대면 막대 색)"""
    if res.figure is None or not res.figure.data:
        return None
    t = res.figure.data[0]
    c = t.marker.color if t.type == "bar" else (t.line.color or t.marker.color)
    return c if isinstance(c, str) else None


def apply_overlays(results, jobs, overlays):
    """results(ChartPlan 순서) 에 합친 차트를 더한다. 원래 차트는 그대로 둔다"""
    out = list(results)
    by_id = {r.chart_id: r for r in results}
    jobs_by = {j.chart_id: j for j in jobs or []}
    for ov in overlays or []:
        a, b = (ov.get("charts") or [None, None])[:2]
        ra, rb = by_id.get(a), by_id.get(b)

        def skip(why):
            target = ra or rb
            if target is not None:
                target.warnings.append(f"{ov.get('overlay_id')} 겹쳐 그리기 생략: {why}")

        if ra is None or rb is None:
            skip("겹칠 차트가 결과에 없음")
            continue
        if ra.status != DRAWN or rb.status != DRAWN:
            skip(f"한쪽 차트를 그리지 못함 ({a} {ra.status} · {b} {rb.status})")
            continue
        ja, jb = jobs_by.get(a), jobs_by.get(b)
        try:
            content = merge_content(ov, ja.content, jb.content)
        except (ValueError, AttributeError) as e:
            skip(str(e))
            continue
        # 합친 차트의 두 계열 = 원래 두 차트의 색 그대로 (rows 는 a 계열 → b 계열 순서)
        names = list(dict.fromkeys(str(r[1]) for r in content.rows))
        colors = {n: col for n, col in zip(names, (_color(ra), _color(rb))) if col}
        job = DrawJob(chart_id=ov["overlay_id"], sub_question_ids=list(dict.fromkeys(ja.sub_question_ids + jb.sub_question_ids)),
                      planned_type="overlay", chart_type=content.chart_type, content=content,
                      displays={**ja.displays, **jb.displays}, display_refs=display_refs_of(content),
                      source_links=list({l["url"]: l for l in ja.source_links + jb.source_links}.values()),
                      # 원래 차트 경고를 물려받되, 자릿수 보정 경고는 합친 차트에서 축마다 다시 계산하므로 뺀다
                      warnings=[w for w in dict.fromkeys(ra.warnings + rb.warnings) if not w.startswith("표시 자릿수")],
                      colors=colors)
        res = draw_chart(job)
        res.merged_from = [a, b]
        if res.status != DRAWN:
            skip(res.reason or res.status)
            continue
        pos = max(out.index(ra), out.index(rb)) + 1        # 두 차트 뒤에
        out.insert(pos, res)
    return out
