"""
모듈 5 렌더러 15종 — (df, content, displays) → (traces, layout, warnings)

  입력은 모든 유형이 같은 ChartContent 하나. 유형별 약속(역할 · 행 모양 · 숫자 · 음수 · y 기준선)은
  draw_chart_tool.precheck가 먼저 확인하므로, 렌더러는 약속이 지켜진 입력만 받는다.
  새 유형을 추가할 때는 렌더러 함수를 만들어 아래 RENDERERS에 등록한다.
"""
import math

import plotly.graph_objects as go

from .draw_chart_format import (COLOR_SCALE, LABEL_MAX_POINTS, aligned, axis_title, categories, digits_of, display_for,
                                fallback_digits, fmt, is_missing, missing_warning, nice_step, scaled, series_groups,
                                tick_format, unit_text, value_range, y_floor)
from .draw_chart_schema import CHART_TYPES

# =============================================
# 렌더러: (df, content, displays) → (traces, layout, warnings)
#   trace와 그 차트에만 필요한 레이아웃만 만든다. 제목·폰트·범례·출처는 decorate가 공통으로 한다
#   입력은 모든 유형이 같은 ChartContent 하나. 유형마다 다른 '약속'(역할·행 모양·숫자·음수·y 기준선)은
#   precheck가 먼저 확인하므로, 렌더러는 약속이 지켜졌다고 보고 그린다. 각 렌더러 docstring의 '약속' 줄 참고
# =============================================
HOVER = "%{customdata}<extra>%{fullData.name}</extra>"


# ── line · area: x(time), y, series ──────────────
def _time_series(df, content, displays, area=False):
    enc, warns = content.encoding, []
    x_col, y_col, s_col = enc["x"], enc["y"], enc.get("series")
    y_spec = content.axis.get("y")
    d = display_for(content, displays, "y")
    xs = categories(df, x_col)          # 연도를 숫자로 두면 2021.5 같은 눈금이 생긴다 → 문자열 + category 축
    show = len(xs) <= LABEL_MAX_POINTS
    traces = []
    for name, g in series_groups(df, s_col):
        raw = aligned(g, x_col, xs, y_col)                    # 빠진 시점 → None (끊긴 선)
        warns += missing_warning(raw, name)
        traces.append(go.Scatter(
            x=xs, y=[scaled(v, d) for v in raw], name=name or (y_spec.label if y_spec else y_col),
            mode="lines+markers+text" if show else "lines+markers",
            text=[fmt(v, d, with_unit=False) for v in raw] if show else None,
            textposition="top center", cliponaxis=False,
            customdata=[fmt(v, d) for v in raw], hovertemplate="%{x}<br>" + HOVER,
            connectgaps=False, fill="tozeroy" if area else None,
        ))
    layout = {
        "xaxis": {"title": axis_title(content.axis.get("x"), None), "type": "category",
                  "categoryorder": "array", "categoryarray": xs},
        "yaxis": {"title": axis_title(y_spec, d), "tickformat": tick_format(d),
                  **value_range(y_spec, d, y_floor(content))},
    }
    return traces, layout, warns


def draw_line(df, content, displays):
    """꺾은선
    약속: 필수 x(시점)·y / 선택 series / long 행 / 숫자 y / y 기준선 없음 (0부터 시작하지 않아도 됨)"""
    return _time_series(df, content, displays)


def draw_area(df, content, displays):
    """면적: 선 아래를 0까지 채운다. 계열이 여럿이면 겹쳐 그린다 (쌓지 않음)
    약속: 필수 x(시점)·y / 선택 series / long 행 / 숫자 y / y 음수 불가 / y 기준선 zero (0부터)"""
    return _time_series(df, content, displays, area=True)


# ── bar · stacked_bar: x(category), y, series ────
def _bars(df, content, displays, stacked=False):
    enc, warns = content.encoding, []
    x_col, y_col, s_col = enc["x"], enc["y"], enc.get("series")
    y_spec = content.axis.get("y")
    d = display_for(content, displays, "y")
    horizontal = content.options.get("orientation") == "horizontal"     # 순위(rank)면 가로 막대
    cats = categories(df, x_col)
    show = len(cats) <= LABEL_MAX_POINTS
    traces = []
    for name, g in series_groups(df, s_col):
        raw = aligned(g, x_col, cats, y_col)
        warns += missing_warning(raw, name)
        vals = [scaled(v, d) for v in raw]
        xy = {"x": vals, "y": cats, "orientation": "h"} if horizontal else {"x": cats, "y": vals}
        traces.append(go.Bar(
            **xy, name=name or (y_spec.label if y_spec else y_col),
            text=[fmt(v, d, with_unit=False) for v in raw] if show else None,
            textposition="inside" if stacked else "outside", cliponaxis=False,
            customdata=[fmt(v, d) for v in raw],
            hovertemplate=("%{y}" if horizontal else "%{x}") + "<br>" + HOVER,
        ))
    cat_axis = {"title": axis_title(content.axis.get("x"), None), "type": "category",
                "categoryorder": "array", "categoryarray": cats}
    val_axis = {"title": axis_title(y_spec, d), "tickformat": tick_format(d), **value_range(y_spec, d, y_floor(content))}
    if horizontal:
        cat_axis["autorange"] = "reversed"                     # 1위가 위에 오도록
        layout = {"xaxis": val_axis, "yaxis": cat_axis}
    else:
        layout = {"xaxis": cat_axis, "yaxis": val_axis}
    layout["barmode"] = "stack" if stacked else "group"
    return traces, layout, warns


def draw_bar(df, content, displays):
    """막대: options.orientation = horizontal이면 가로 막대 (순위)
    약속: 필수 x(범주)·y / 선택 series / long 행 / 숫자 y / y 기준선 include_zero (범위에 0 포함)"""
    return _bars(df, content, displays)


def draw_stacked_bar(df, content, displays):
    """누적 막대: 같은 x에서 series를 쌓는다
    약속: 필수 x·y·series / long 행 / 숫자 y / y 음수 불가 / y 기준선 zero"""
    return _bars(df, content, displays, stacked=True)


# ── pyramid: y(category), group(2개), value ──────
def draw_pyramid(df, content, displays):
    """피라미드: 첫 번째 group을 왼쪽(음수로 그림), 두 번째를 오른쪽. 눈금은 절댓값으로 표시
    약속: 필수 y(범주, 예: 연령)·group(값 2개)·value / long 행 / 숫자 value / value 음수 불가"""
    enc, warns = content.encoding, []
    y_col, g_col, v_col = enc["y"], enc["group"], enc["value"]
    d = display_for(content, displays, "x")
    cats = categories(df, y_col)
    groups = categories(df, g_col)
    if len(groups) != 2:
        raise ValueError(f"group 값이 2개가 아님: {groups}")
    traces, vmax = [], 0
    for i, gname in enumerate(groups):
        raw = aligned(df[df[g_col].astype(str) == gname], y_col, cats, v_col)
        warns += missing_warning(raw, gname)
        vals = [scaled(v, d) for v in raw]
        vmax = max(vmax, *(abs(v) for v in vals if v is not None))
        sign = -1 if i == 0 else 1
        traces.append(go.Bar(y=cats, x=[None if v is None else sign * v for v in vals], orientation="h", name=gname,
                             customdata=[fmt(v, d) for v in raw], hovertemplate="%{y}<br>" + HOVER))
    step = nice_step(vmax)
    n = math.ceil(vmax / step)
    ticks = [k * step for k in range(-n, n + 1)]
    dg = digits_of(d) if float(step).is_integer() else max(1, digits_of(d))
    layout = {
        "barmode": "relative", "bargap": 0.1,
        "xaxis": {"title": unit_text(d), "tickvals": ticks, "ticktext": [f"{abs(t):,.{dg}f}" for t in ticks],
                  "range": [-n * step, n * step]},
        "yaxis": {"title": axis_title(content.axis.get("y"), None), "type": "category",
                  "categoryorder": "array", "categoryarray": cats},
        "legend": {"orientation": "h", "x": 0.5, "xanchor": "center", "y": 1.08},
    }
    return traces, layout, warns


# ── pie · donut: label, value ────────────────────
def _pie(df, content, displays, hole=0.0):
    enc = content.encoding
    l_col, v_col = enc["label"], enc["value"]
    d = display_for(content, displays)
    labels = df[l_col].astype(str).tolist()
    raw = [None if is_missing(v) else v for v in df[v_col]]
    trace = go.Pie(labels=labels, values=[scaled(v, d) for v in raw], hole=hole, sort=False, direction="clockwise",
                   textinfo="label+percent", customdata=[fmt(v, d) for v in raw],
                   hovertemplate="%{label}<br>%{customdata} (%{percent})<extra></extra>")
    layout = {}
    if hole and (center := content.options.get("center_text")):
        layout["annotations"] = [{"text": center, "x": 0.5, "y": 0.5, "xref": "paper", "yref": "paper",
                                  "showarrow": False, "font": {"size": 14}}]
    return [trace], layout, missing_warning(raw, None)


def draw_pie(df, content, displays):
    """원형: 축 없음. 표시 설정은 options.display_ref
    약속: 필수 label·value / long 행 / 숫자 value / value 음수 불가"""
    return _pie(df, content, displays)


def draw_donut(df, content, displays):
    """도넛: 가운데에 options.center_text
    약속: pie와 같음 (필수 label·value / long 행 / 숫자 value / value 음수 불가)"""
    return _pie(df, content, displays, hole=0.5)


# ── treemap: parent, label, value ────────────────
def draw_treemap(df, content, displays):
    """트리맵: 면적이 값. parent 노드는 자식 합계로 크기가 정해진다 (branchvalues=remainder, 부모 값 0)
    약속: 필수 parent·label·value / long 행 / 숫자 value / value 음수 불가"""
    enc = content.encoding
    p_col, l_col, v_col = enc.get("parent"), enc["label"], enc["value"]
    d = display_for(content, displays)
    ids, labels, parents, values, custom = [], [], [], [], []
    if p_col:
        for p in categories(df, p_col):
            total = sum(v for v in df[df[p_col].astype(str) == p][v_col] if not is_missing(v))
            ids.append(f"p::{p}"); labels.append(p); parents.append(""); values.append(0); custom.append(fmt(total, d))
    for _, r in df.iterrows():
        pid = f"p::{r[p_col]}" if p_col else ""
        ids.append(f"{pid}/{r[l_col]}"); labels.append(str(r[l_col])); parents.append(pid)
        values.append(scaled(r[v_col], d) or 0); custom.append(fmt(r[v_col], d))
    trace = go.Treemap(ids=ids, labels=labels, parents=parents, values=values, branchvalues="remainder",
                       customdata=custom, texttemplate="%{label}<br>%{customdata}",
                       hovertemplate="%{label}<br>%{customdata}<extra></extra>")
    return [trace], {"margin": {"t": 70, "b": 60, "l": 10, "r": 10}}, []


# ── radar: label(지표 축), series, value ─────────
def draw_radar(df, content, displays):
    """레이더: 계열별로 닫힌 다각형. 단위가 다른 지표의 정규화는 모듈 3 몫 (아직 없음)
    약속: 필수 label(지표 축)·series·value / long 행 / 숫자 value"""
    enc, warns = content.encoding, []
    l_col, s_col, v_col = enc["label"], enc.get("series"), enc["value"]
    d = display_for(content, displays)
    axes = categories(df, l_col)
    traces = []
    for name, g in series_groups(df, s_col):
        raw = aligned(g, l_col, axes, v_col)
        warns += missing_warning(raw, name)
        vals = [scaled(v, d) for v in raw]
        traces.append(go.Scatterpolar(r=vals + vals[:1], theta=axes + axes[:1], name=name or v_col, fill="toself",
                                      opacity=0.6, customdata=[fmt(v, d) for v in raw + raw[:1]],
                                      hovertemplate="%{theta}<br>" + HOVER))
    # 반지름 눈금은 위쪽 세로축에 가로 글씨로 (기본 위치는 지표 이름·축 제목과 겹친다), 단위는 눈금 뒤에 붙인다
    layout = {"polar": {"radialaxis": {"angle": 90, "tickangle": 90, "nticks": 5, "tickformat": tick_format(d),
                                       "ticksuffix": unit_text(d), "tickfont": {"size": 10}},
                        "angularaxis": {"direction": "clockwise", "rotation": 90}}}
    return traces, layout, warns


# ── map: region, value (시도 타일 지도) ──────────
# 저장소에 지역 경계(GeoJSON)가 없어 시도 17곳을 격자 칸에 놓는다 (대략적인 위치). 시군구 지도는 경계 파일이 생기면 추가
SIDO_TILES = {  # 이름: (열, 행)
    "인천": (0, 0), "서울": (1, 0), "경기": (2, 0), "강원": (3, 0),
    "충남": (0, 1), "세종": (1, 1), "충북": (2, 1), "경북": (3, 1),
    "전북": (0, 2), "대전": (1, 2), "대구": (2, 2), "울산": (3, 2),
    "광주": (0, 3), "전남": (1, 3), "경남": (2, 3), "부산": (3, 3),
    "제주": (0, 4),
}


def sido_short(name):
    """'충청북도' → '충북', '서울특별시' → '서울', '전북특별자치도' → '전북'"""
    n = str(name).replace(" ", "")
    for full, short in (("충청북", "충북"), ("충청남", "충남"), ("전라북", "전북"), ("전라남", "전남"),
                        ("경상북", "경북"), ("경상남", "경남")):
        if n.startswith(full):
            return short
    return n[:2]


def draw_map(df, content, displays):
    """맵: 칸 색이 값. 타일에 없는 지역(전국, 시군구 등)은 빼고 경고
    약속: 필수 region·value / long 행 / 숫자 value / options.geo_level(시도)"""
    enc, warns = content.encoding, []
    r_col, v_col = enc["region"], enc["value"]
    d = display_for(content, displays)
    if (lvl := content.options.get("geo_level")) not in (None, "시도"):
        warns.append(f"geo_level={lvl}: 시도 타일 지도로 그림")
    ncol = max(c for c, _ in SIDO_TILES.values()) + 1
    nrow = max(r for _, r in SIDO_TILES.values()) + 1
    z = [[None] * ncol for _ in range(nrow)]
    text = [[""] * ncol for _ in range(nrow)]
    hover = [[""] * ncol for _ in range(nrow)]
    skipped = []
    for _, row in df.iterrows():
        key = sido_short(row[r_col])
        if key not in SIDO_TILES or is_missing(row[v_col]):
            skipped.append(str(row[r_col]))
            continue
        c, r = SIDO_TILES[key]
        z[r][c] = scaled(row[v_col], d)
        text[r][c] = f"{key}<br>{fmt(row[v_col], d, with_unit=False)}"
        hover[r][c] = f"{row[r_col]}<br>{fmt(row[v_col], d)}"
    if all(v is None for line in z for v in line):
        raise ValueError("타일 지도에 놓을 수 있는 시도가 없음 (시군구 지도는 아직 없음)")
    if skipped:
        warns.append(f"지도에 없는 지역 {len(skipped)}개 제외: {', '.join(skipped)}")
    trace = go.Heatmap(z=z, text=text, texttemplate="%{text}", customdata=hover,
                       hovertemplate="%{customdata}<extra></extra>", colorscale=COLOR_SCALE, xgap=4, ygap=4,
                       colorbar={"title": {"text": unit_text(d)}, "tickformat": tick_format(d)})
    hidden = {"visible": False, "showgrid": False, "zeroline": False}
    layout = {"xaxis": {**hidden, "constrain": "domain"},
              "yaxis": {**hidden, "autorange": "reversed", "scaleanchor": "x", "constrain": "domain"},
              "plot_bgcolor": "rgba(0,0,0,0)"}
    return [trace], layout, warns


# ── heatmap: x(category), y(category), value ─────
def draw_heatmap(df, content, displays):
    """히트맵: 색이 값. 칸이 적으면(80칸 이하) 칸 안에 값 표시
    약속: 필수 x(범주)·y(범주)·value / long 행 / 숫자 value"""
    enc, warns = content.encoding, []
    x_col, y_col, v_col = enc["x"], enc["y"], enc["value"]
    d = display_for(content, displays, "x") or display_for(content, displays, "y")
    xs, ys = categories(df, x_col), categories(df, y_col)
    table = {(str(r[y_col]), str(r[x_col])): r[v_col] for _, r in df.iterrows()}
    raw = [[table.get((y, x)) for x in xs] for y in ys]
    n_missing = sum(is_missing(v) for line in raw for v in line)
    if n_missing:
        warns.append(f"결측 {n_missing}칸")
    dg = None if d else fallback_digits(v for line in raw for v in line)    # 모듈 3이 display를 주지 않으면 값에서 자릿수를 정한다
    trace = go.Heatmap(
        x=xs, y=ys, z=[[scaled(v, d) for v in line] for line in raw],
        text=[[fmt(v, d, with_unit=False, digits=dg) for v in line] for line in raw],
        texttemplate="%{text}" if len(xs) * len(ys) <= 80 else None,
        customdata=[[fmt(v, d, digits=dg) for v in line] for line in raw],
        hovertemplate="%{y} · %{x}<br>%{customdata}<extra></extra>",
        colorscale=COLOR_SCALE, xgap=2, ygap=2, colorbar={"title": {"text": unit_text(d)}})
    layout = {"xaxis": {"title": axis_title(content.axis.get("x"), None), "type": "category"},
              "yaxis": {"title": axis_title(content.axis.get("y"), None), "type": "category", "autorange": "reversed"}}
    return [trace], layout, warns


# ── combo: x(time), y, y2, series ────────────────
def draw_combo(df, content, displays):
    """복합: options.series_axis로 지표별 축(y/y2)을, options.marks로 축별 표시(bar/line)를 정한다. y2는 오른쪽 축
    약속: 필수 x(시점)·y·y2 / 선택 series / long 행 (y·y2가 같은 값 열) / 숫자 y·y2"""
    enc, warns = content.encoding, []
    x_col, v_col, s_col = enc["x"], enc["y"], enc.get("series")
    marks = content.options.get("marks") or {"y": "bar", "y2": "line"}
    series_axis = content.options.get("series_axis") or {}
    xs = categories(df, x_col)
    show = len(xs) <= LABEL_MAX_POINTS
    traces = []
    for name, g in series_groups(df, s_col):
        role = series_axis.get(name)
        if role not in ("y", "y2"):
            warns.append(f"series_axis에 없는 계열 '{name}' → 왼쪽 축(y)")
            role = "y"
        d = display_for(content, displays, role)
        raw = aligned(g, x_col, xs, v_col)
        warns += missing_warning(raw, name)
        common = dict(x=xs, y=[scaled(v, d) for v in raw], name=name or v_col, yaxis="y2" if role == "y2" else "y",
                      cliponaxis=False, customdata=[fmt(v, d) for v in raw], hovertemplate="%{x}<br>" + HOVER)
        labels = [fmt(v, d, with_unit=False) for v in raw] if show else None
        if marks.get(role) == "bar":
            # 막대 라벨은 선·선 라벨과 겹치므로 붙이지 않는다 (값은 hover로). 선 라벨만 표시
            traces.append(go.Bar(**common, opacity=0.6))
        else:
            traces.append(go.Scatter(**common, text=labels, mode="lines+markers+text" if show else "lines+markers",
                                     textposition="top center"))
    y_spec, y2_spec = content.axis.get("y"), content.axis.get("y2")
    dy, dy2 = display_for(content, displays, "y"), display_for(content, displays, "y2")
    layout = {
        "xaxis": {"title": axis_title(content.axis.get("x"), None), "type": "category",
                  "categoryorder": "array", "categoryarray": xs},
        "yaxis": {"title": axis_title(y_spec, dy), "tickformat": tick_format(dy), **value_range(y_spec, dy, y_floor(content))},
        "yaxis2": {"title": axis_title(y2_spec, dy2), "tickformat": tick_format(dy2), "overlaying": "y",
                   "side": "right", "showgrid": False, **value_range(y2_spec, dy2)},
        "legend": {"orientation": "h", "x": 0.5, "xanchor": "center", "y": 1.08},
    }
    return traces, layout, warns


# ── scatter · bubble: x(numeric), y(numeric) [, size], label, series (joined 행) ──
def _points(df, content, displays, with_size=False):
    enc, warns = content.encoding, []
    x_col, y_col = enc["x"], enc["y"]
    z_col = enc.get("size") if with_size else None
    l_col, s_col = enc.get("label"), enc.get("series")
    dx, dy = display_for(content, displays, "x"), display_for(content, displays, "y")
    need = [x_col, y_col] + ([z_col] if z_col else [])
    bad = df[need].map(is_missing).any(axis=1)
    if bad.any():
        warns.append(f"값이 빠진 점 {int(bad.sum())}개 제외")
        df = df[~bad]
    show = bool(l_col) and len(df) <= 20
    if z_col:
        zmax = max(abs(v) for v in df[z_col]) or 1
        sizeref = 2 * zmax / (45 ** 2)          # 가장 큰 원의 지름 ≈ 45px
    traces = []
    for name, g in series_groups(df, s_col):
        labels = g[l_col].astype(str).tolist() if l_col else [""] * len(g)
        custom = [[lb, fmt(x, dx), fmt(y, dy), fmt(z, None) if z_col else ""]
                  for lb, x, y, z in zip(labels, g[x_col], g[y_col], g[z_col] if z_col else [None] * len(g))]
        marker = ({"size": [abs(v) for v in g[z_col]], "sizemode": "area", "sizeref": sizeref, "sizemin": 6,
                   "opacity": 0.65, "line": {"width": 1, "color": "white"}} if z_col else {"size": 10, "opacity": 0.8})
        tmpl = f"<b>%{{customdata[0]}}</b><br>{x_col}: %{{customdata[1]}}<br>{y_col}: %{{customdata[2]}}"
        if z_col:
            tmpl += f"<br>{z_col}: %{{customdata[3]}}"
        traces.append(go.Scatter(
            x=[scaled(v, dx) for v in g[x_col]], y=[scaled(v, dy) for v in g[y_col]], name=name or y_col,
            mode="markers+text" if show else "markers", text=labels if show else None,
            textposition="top center", cliponaxis=False,
            marker=marker, customdata=custom, hovertemplate=tmpl + "<extra></extra>"))
    layout = {"xaxis": {"title": axis_title(content.axis.get("x"), dx), "tickformat": tick_format(dx)},
              "yaxis": {"title": axis_title(content.axis.get("y"), dy), "tickformat": tick_format(dy)}}
    return traces, layout, warns


def draw_scatter(df, content, displays):
    """산점도: 점 20개 이하면 label을 점 옆에 표시
    약속: 필수 x·y / 선택 label·series / joined 행 [키…, 지표1, 지표2] / 숫자 x·y"""
    return _points(df, content, displays)


def draw_bubble(df, content, displays):
    """버블: 원 면적이 size 값
    약속: 필수 x·y·size / 선택 label·series / joined 행 / 숫자 x·y·size / size 음수 불가"""
    return _points(df, content, displays, with_size=True)


# ── dumbbell: label(category), start, end (joined 행) ──
def draw_dumbbell(df, content, displays):
    """덤벨: 범주마다 start·end 두 점을 선으로 잇는다 (가로). 범례 이름은 start·end 열 이름 (예: 2015, 2024)
    약속: 필수 label(범주)·start·end / joined 행 [범주, 시작값, 끝값] / 숫자 start·end"""
    enc, warns = content.encoding, []
    l_col, s_col, e_col = enc["label"], enc["start"], enc["end"]
    d = display_for(content, displays, "x")
    cats = categories(df, l_col)
    starts, ends = aligned(df, l_col, cats, s_col), aligned(df, l_col, cats, e_col)
    if n := sum(a is None or b is None for a, b in zip(starts, ends)):
        warns.append(f"한쪽 점이 없는 범주 {n}개")
    lx, ly = [], []
    for c, a, b in zip(cats, starts, ends):
        if a is not None and b is not None:
            lx += [scaled(a, d), scaled(b, d), None]
            ly += [c, c, None]
    show = len(cats) <= LABEL_MAX_POINTS
    traces = [go.Scatter(x=lx, y=ly, mode="lines", line={"color": "#bbb", "width": 4}, showlegend=False, hoverinfo="skip")]
    for col, vals, other in ((s_col, starts, ends), (e_col, ends, starts)):
        pos = ["middle left" if (v is not None and o is not None and v <= o) else "middle right" for v, o in zip(vals, other)]
        traces.append(go.Scatter(
            x=[scaled(v, d) for v in vals], y=cats, mode="markers+text" if show else "markers", name=str(col),
            marker={"size": 13}, text=[fmt(v, d, with_unit=False) for v in vals] if show else None,
            textposition=pos, cliponaxis=False, customdata=[fmt(v, d) for v in vals],
            hovertemplate="%{y}<br>" + HOVER))
    layout = {"xaxis": {"title": axis_title(content.axis.get("x"), d), "tickformat": tick_format(d)},
              "yaxis": {"title": l_col, "type": "category", "categoryorder": "array", "categoryarray": cats,
                        "autorange": "reversed"},
              "legend": {"orientation": "h", "x": 0.5, "xanchor": "center", "y": 1.08}}
    return traces, layout, warns


# ── 렌더러 등록 ───────────────────────────────────
RENDERERS = {
    "line": draw_line, "bar": draw_bar, "stacked_bar": draw_stacked_bar, "pyramid": draw_pyramid,
    "area": draw_area, "pie": draw_pie, "donut": draw_donut, "bubble": draw_bubble, "combo": draw_combo,
    "radar": draw_radar, "map": draw_map, "heatmap": draw_heatmap, "treemap": draw_treemap,
    "scatter": draw_scatter, "dumbbell": draw_dumbbell,
}

assert set(RENDERERS) <= set(CHART_TYPES), f"15종 밖의 렌더러: {set(RENDERERS) - set(CHART_TYPES)}"
IMPLEMENTED_TYPES = set(RENDERERS)
