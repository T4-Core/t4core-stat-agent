"""차트 — 모듈 5 의 plotly JSON 은 시안 색으로 다시 칠하고, default 모드의 차트 스펙(line/bar/table)은 여기서 그림

시안 규칙: 질문한 시점(처음·끝) 막대·점은 진한 청록, 사이 연도는 연한 청록. 배경·격자는 옅게
"""
from __future__ import annotations

import copy

import plotly.graph_objects as go

TEAL, TEAL_L, INK2, INK3, GRID = "#7BA39D", "#DCE9E6", "#55625F", "#8A9794", "#EDF1F0"
SERIES = [TEAL, "#E9A57B", "#3F6661", "#B9CCC8", "#9BBBB5", "#C7926E"]
FONT = "Pretendard, 'Noto Sans KR', 'Malgun Gothic', sans-serif"


def _layout(fig, height):
    fig.update_layout(template="plotly_white", height=height, margin=dict(l=8, r=8, t=24, b=8),
                      font=dict(family=FONT, size=12, color=INK2), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", showlegend=len(fig.data) > 1, colorway=SERIES,
                      legend=dict(orientation="h", y=-0.15, x=0), hoverlabel=dict(font_family=FONT))
    fig.update_xaxes(showgrid=False, linecolor=GRID, tickfont=dict(color=INK2), title=None, type="category")
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickfont=dict(color=INK3), title=None)
    return fig


def _shade(xs, highlight):
    hi = {str(h) for h in highlight or []}
    return [TEAL if (not hi or str(x) in hi) else TEAL_L for x in xs]


def from_module(figure: dict, highlight=(), height=330):
    """모듈 5 plotly JSON → 시안 색. 막대 하나짜리면 질문 시점 강조, 선은 계열 색"""
    figure = copy.deepcopy(figure)  # go.Figure 는 실패할 때 입력 dict 를 고침 (type 을 뺌) — 세션의 응답을 지킴
    try:
        fig = go.Figure(copy.deepcopy(figure))
    except ValueError:  # 이 plotly 버전이 모르는 속성은 버리고 그림 (모듈 5 와 버전이 다를 때). 트레이스 종류는 지킴
        fig = go.Figure(layout=go.Layout(figure.get("layout") or {}, skip_invalid=True))
        for t in figure.get("data") or []:
            cls = getattr(go, str(t.get("type") or "scatter").capitalize(), go.Scatter)
            fig.add_trace(cls({k: v for k, v in t.items() if k != "type"}, skip_invalid=True))
    for i, tr in enumerate(fig.data):
        c = SERIES[i % len(SERIES)]
        if tr.type == "bar":
            tr.marker.color = _shade(list(tr.x or []), highlight) if len(fig.data) == 1 else c
            tr.marker.line.width = 0
        elif tr.type == "scatter":
            tr.line.color, tr.marker.color = c, c
    fig.update_layout(title=None, bargap=0.35)
    return _layout(fig, height)


def from_spec(spec: dict, highlight=(), height=330):
    """result.chart (default 모드) → plotly. type: line | bar | table(None 반환 → 표로)"""
    if (spec or {}).get("type") not in ("line", "bar"):
        return None
    cols = spec.get("columns") or []
    rows = spec.get("rows") or []
    x, y, s = spec.get("x") or (cols[0] if cols else None), spec.get("y") or "값", spec.get("series")
    if x not in cols or y not in cols:
        return None
    xi, yi = cols.index(x), cols.index(y)
    si = cols.index(s) if s in cols else None
    groups = {}
    for r in rows:
        groups.setdefault(r[si] if si is not None else "", []).append((str(r[xi]), r[yi]))
    fig = go.Figure()
    for i, (name, pts) in enumerate(groups.items()):
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        text = [f"{v:,.0f}" if isinstance(v, (int, float)) and abs(v) >= 100 else f"{v}" for v in ys]
        if spec["type"] == "bar":
            fig.add_bar(x=xs, y=ys, name=name or y, text=text, textposition="outside",
                        marker_color=_shade(xs, highlight) if len(groups) == 1 else SERIES[i % len(SERIES)])
        else:
            hi = {str(h) for h in highlight or []}
            fig.add_scatter(x=xs, y=ys, name=name or y, mode="lines+markers+text", text=text, textposition="top center",
                            line=dict(color=SERIES[i % len(SERIES)], width=2.5),
                            marker=dict(size=[11 if xx in hi else 7 for xx in xs], color=SERIES[i % len(SERIES)]))
    fig.update_layout(bargap=0.35)
    return _layout(fig, height)


def figure_of(chart, height=330):
    """view_model.Chart → plotly Figure (그릴 수 없으면 None → 표만)"""
    if chart.figure:
        return from_module(chart.figure, chart.highlight, height)
    return from_spec(chart.spec or {}, chart.highlight, height)
