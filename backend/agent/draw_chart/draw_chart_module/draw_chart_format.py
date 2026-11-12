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
    """axis.min/max + 유형별 y 기준선(SPECS.y_floor) → Plotly 축 범위
    - axis.min·max가 둘 다 있으면 그 범위로 고정
    - 아니면 있는 값과 기준선(zero / include_zero → 0)을 범위에 포함 (예: 면적·누적 막대는 0부터)"""
    lo, hi = (scaled(spec.min, d), scaled(spec.max, d)) if spec else (None, None)
    if lo is not None and hi is not None:
        return {"range": [lo, hi]}
    include = [v for v in (lo, hi) if v is not None] + ([0] if floor in ("zero", "include_zero") else [])
    return {"autorangeoptions": {"include": include}} if include else {}


def y_floor(content):
    """유형별 y 기준선 (SPECS): zero = y.min 0 / include_zero = 범위에 0 포함 / None = 기준 불필요"""
    return SPECS[content.chart_type].y_floor


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


def source_text(links):
    """출처 annotation. HTML에서는 링크, PNG에서는 글자로 찍힌다"""
    if not links:
        return ""
    return "출처: " + ", ".join(f'<a href="{l["url"]}" target="_blank">{l["label"]}</a>' for l in links)
