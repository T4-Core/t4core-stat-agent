"""
모듈 5 표시 헬퍼 — 값 환산 · 표시 문자열 · 축 이름 · 축 범위 · 표 정리

  숫자 표시는 모듈 3의 format_value(backend/agent/chart_calculate/display.py)를 쓴다 → 차트 숫자와 답변(모듈 6) 숫자 모양이 같다.
  렌더러(draw_chart_renderers)와 tool(draw_chart_tool)이 함께 쓴다.
"""
import math

import pandas as pd

from backend.agent.chart_calculate.display import NO_SUFFIX_UNITS, default_digits, format_value
from backend.agent.chart_calculate.specs import SPECS

FONT_FAMILY = "Malgun Gothic"
# 계열 색 (Plotly 기본 색 순서). 질문 하나 안에서 같은 이름(지표 · 계열)은 어느 차트에서든 같은 색 → color_map
SERIES_COLORS = ["#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A", "#19D3F3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52"]
LABEL_MAX_POINTS = 12          # 계열당 점(막대)이 이 개수 이하면 값 라벨을 붙인다
COLOR_SCALE = "Blues"          # 색이 값인 차트(heatmap, map)


# ── 공통 헬퍼 ─────────────────────────────────────
def to_df(content):
    """columns + rows → DataFrame"""
    return pd.DataFrame(content.rows, columns=content.columns)


def is_missing(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def scaled(v, d):
    """원값 ÷ unit_scale (그래프 좌표용). None은 그대로"""
    return None if is_missing(v) else v / (d.unit_scale if d else 1)


def fmt(v, d, with_unit=True, digits=None):
    """표시 문자열: format_value(원값 ÷ unit_scale → digits 반올림 → 단위). with_unit=False면 단위 없이 (값 라벨용)
    display가 없으면 천 단위 쉼표만. digits를 주면 그 자리수로 맞추고, 없으면 정수 값에 소수점을 붙이지 않는다"""
    if is_missing(v):
        return ""
    if d is None:
        if digits is not None:
            return f"{v:,.{digits}f}"
        return f"{int(v):,}" if float(v).is_integer() else f"{v:,}"
    return format_value(v, d if with_unit else d.model_copy(update={"display_unit": ""}))


def fallback_digits(values, cap=2):
    """display가 없을 때 쓸 소수 자리: 값들 중 가장 긴 소수 자리 (최대 cap). 4.0과 3.9가 '4'·'3.9'로 섞이지 않게"""
    dg = 0
    for v in values:
        if not is_missing(v) and "." in (s := repr(float(v))) and "e" not in s:
            dg = max(dg, len(s.split(".")[1].rstrip("0")))
    return min(dg, cap)


def digits_of(d):
    return 0 if d is None else (d.digits if d.digits is not None else default_digits(d.source_unit, d.unit_scale))


def tick_format(d):
    """축 눈금 형식: 천 단위 쉼표 + display의 소수 자리 (Plotly 기본은 192k처럼 SI 접미사라 바꾼다)"""
    return f",.{digits_of(d)}f"


def unit_text(d):
    """표시 단위 (index·천명당처럼 단위를 붙이지 않는 것은 빈 문자열)"""
    return d.display_unit if d and d.display_unit and d.display_unit not in NO_SUFFIX_UNITS else ""


def axis_title(spec, d):
    """축 이름 = label + (display_unit)"""
    label, unit = ((spec.label if spec else None) or ""), unit_text(d)
    return f"{label}({unit})" if label and unit else (label or unit)


def display_for(content, displays, role=None):
    """역할의 표시 설정: axis[role].display_ref → 없으면 options.display_ref (축 없는 차트) → 없으면 None"""
    spec = content.axis.get(role) if role else None
    ref = (spec.display_ref if spec else None) or content.options.get("display_ref")
    return displays.get(ref) if ref else None


def value_range(spec, d, floor=None):
    """axis.min/max + 유형별 y 기준선(SPECS.axis_rules['y']) → Plotly 축 범위
    - axis.min·max가 둘 다 있으면 그 범위로 고정
    - 아니면 있는 값과 기준선(zero / include_zero → 0)을 범위에 포함 (예: 면적·누적 막대는 0부터)"""
    lo, hi = (scaled(spec.min, d), scaled(spec.max, d)) if spec else (None, None)
    if lo is not None and hi is not None:
        return {"range": [lo, hi]}
    include = [v for v in (lo, hi) if v is not None] + ([0] if floor in ("zero", "include_zero") else [])
    return {"autorangeoptions": {"include": include}} if include else {}


def y_rule(spec):
    """차트 규격(모듈 3 SPECS 의 ChartSpec) → y 기준선 규칙 (zero · include_zero, 그 밖이면 None)
    모듈 3 은 axis_rules({축: 규칙}) 를 쓴다. 예전 모듈 3 의 y_floor 도 읽는다 (54682ff 이전)"""
    rules = getattr(spec, "axis_rules", None)
    rule = rules.get("y") if isinstance(rules, dict) else getattr(spec, "y_floor", None)
    return rule if rule in ("zero", "include_zero") else None          # free · symmetric 등 → 기준 없음


def y_floor(content):
    """유형별 y 기준선: zero = y.min 0 / include_zero = 범위에 0 포함 / None = 기준 불필요"""
    return y_rule(SPECS[content.chart_type])


def categories(df, col):
    """열의 값 목록 (문자열, rows 순서 유지)"""
    return list(dict.fromkeys(df[col].astype(str)))


def series_groups(df, s_col):
    """범례(계열)별로 나누기. 계열 열이 없으면 하나"""
    if not s_col:
        return [(None, df)]
    return [(str(k), g) for k, g in df.groupby(df[s_col].astype(str), sort=False)]


def aligned(g, key_col, keys, val_col):
    """g를 keys 순서로 맞춘 원값 목록 (빠진 키는 None)"""
    g = g.assign(**{key_col: g[key_col].astype(str)}).drop_duplicates(subset=key_col, keep="first")
    s = g.set_index(key_col)[val_col].reindex(keys)
    return [None if is_missing(v) else v for v in s]


def missing_warning(raw, name):
    n = sum(v is None for v in raw)
    return [f"결측 {n}개{f' ({name})' if name else ''}"] if n else []


def nice_step(vmax, n=3):
    """0 ~ vmax를 n칸 정도로 나누는 보기 좋은 눈금 간격"""
    if not vmax or vmax <= 0:
        return 1
    raw = vmax / n
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


NICE_STEPS = (1, 2, 2.5, 5, 10)
X_TICK_LIMIT = 20              # 범주 x축 값이 이보다 많으면 눈금을 건너뛴다 (시점) / 기울인다 (이름)
SOURCE_GAP = 4                 # 출처 글자 아래 끝 ~ 그림 아래 끝 (px)


def nice_ceil(x):
    """x 이상인 보기 좋은 수 (1 · 2 · 2.5 · 5 × 10^k)"""
    if x <= 0:
        return 1
    mag = 10 ** math.floor(math.log10(x))
    return next(m * mag for m in NICE_STEPS if m * mag >= x * (1 - 1e-12))


def aligned_ticks(values, include_zero=False, n=5, fixed=None):
    """값 목록 → (range, tickvals). 눈금은 항상 n+1개 → 축 두 개(combo)의 눈금 · 격자가 같은 높이에 온다
    fixed=(lo, hi) 가 둘 다 있으면 그 범위를 n칸으로 나눈다"""
    if fixed and fixed[0] is not None and fixed[1] is not None:
        lo, hi = fixed
        step = (hi - lo) / n
        return [lo, hi], [round(lo + i * step, 10) for i in range(n + 1)]
    vals = [v for v in values if not is_missing(v)]
    if not vals:
        return None, None
    lo, hi = min(vals), max(vals)
    if include_zero:
        lo, hi = min(lo, 0), max(hi, 0)
    if lo == hi:
        pad = abs(lo) * 0.1 or 1
        lo, hi = lo - pad, hi + pad
    step = nice_ceil((hi - lo) / n)
    while True:
        start = math.floor(lo / step + 1e-9) * step
        if start + step * n >= hi - 1e-9:
            break
        step = nice_ceil(step * 1.0001)          # 다음 보기 좋은 간격
    ticks = [round(start + i * step, 10) for i in range(n + 1)]
    return [ticks[0], ticks[-1]], ticks


def tick_format_for(d, tickvals):
    """눈금 값을 직접 정했을 때의 형식: display 자릿수로 눈금 글자가 겹치면(0.8 · 1.0 · 1.2 → '1') 구분될 때까지 늘린다 (최대 4)"""
    dg = digits_of(d)
    vals = [v for v in tickvals or [] if v is not None]
    while dg < 4 and len({f"{v:.{dg}f}" for v in vals}) < len(vals):
        dg += 1
    return f",.{dg}f"


def x_ticks(n, kind="time"):
    """범주 x축 값이 많을 때(X_TICK_LIMIT 초과) 눈금 설정
    시점: dtick 으로 2 · 5 · 10 … 칸마다 하나 (12개 이하) / 이름(지역 등): 건너뛰지 않고 -45도로 기울인다"""
    if n <= X_TICK_LIMIT:
        return {}
    if kind == "time":
        step = next(s for s in (2, 5, 10, 20, 50, 100, 200) if n / s <= 12)
        return {"dtick": step, "tickangle": 0}
    return {"tickangle": -45}


def few_bars(n, reverse=False):
    """막대가 2개 이하면 범주 축을 4칸 폭으로 넓혀 막대가 화면을 꽉 채우지 않게 한다 → (범주 축 설정, bargap)"""
    if n > 2:
        return {}, None
    c = (n - 1) / 2
    lo, hi = c - 2, c + 2
    return {"range": [hi, lo] if reverse else [lo, hi]}, 0.5


def widen_digits(d, values, cap=4):
    """display 자릿수로 표시하면 서로 다른 값이 같은 글자가 될 때(합계출산율 1.24 · 1.17 → '1') 구분될 때까지 늘린다 (최대 cap)
    → (display, 늘린 자릿수 또는 None). display 가 없거나 값이 2개 미만이면 그대로"""
    vals = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and not is_missing(v)]
    if d is None or len(vals) < 2:
        return d, None
    n_raw = len({round(v / (d.unit_scale or 1), 9) for v in vals})       # 부동소수 잡음(-0.41999…)은 같은 값으로
    dg0 = dg = digits_of(d)
    while dg < cap and len({fmt(v, d.model_copy(update={"digits": dg})) for v in vals}) < n_raw:
        dg += 1
    return (d, None) if dg == dg0 else (d.model_copy(update={"digits": dg}), dg)


def trace_names(content):
    """렌더러가 붙일 trace 이름: 계열(series) · 그룹(group) 값, 둘 다 없으면 y 축 이름(없으면 y 열)"""
    names = []
    for role in ("series", "group"):
        col = content.encoding.get(role)
        if col and col in content.columns:
            i = content.columns.index(col)
            names += [str(r[i]) for r in content.rows]
    if not names and content.encoding.get("y"):
        y = content.axis.get("y")
        names = [(y.label if y and y.label else None) or content.encoding["y"]]
    return list(dict.fromkeys(names))


def color_map(contents):
    """차트 순서대로 처음 나온 이름에 색을 준다 → {이름: 색}. 색이 모자라면 처음부터 다시"""
    out = {}
    for c in contents:
        for n in trace_names(c):
            out.setdefault(n, SERIES_COLORS[len(out) % len(SERIES_COLORS)])
    return out


def apply_colors(fig, colors):
    """trace 이름이 colors 에 있으면 그 색으로 (선 · 점 · 막대 · 레이더). 점별 색(목록)이 이미 있으면 두지 않는다"""
    for t in fig.data:
        col = colors.get(str(t.name)) if t.name is not None else None
        if not col or t.type not in ("scatter", "bar", "scatterpolar"):
            continue
        if not isinstance(t.marker.color, (list, tuple)):
            t.marker.color = col
        if t.type != "bar":
            t.line.color = col


def source_text(links):
    """출처 annotation. HTML에서는 링크, PNG에서는 글자로 찍힌다"""
    if not links:
        return ""
    return "출처: " + ", ".join(f'<a href="{l["url"]}" target="_blank">{l["label"]}</a>' for l in links)
