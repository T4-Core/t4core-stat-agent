"""③-1 요청한 나눔 (고도화 2단계) — 표의 여러 값 열 중 질문이 나눠 달라고 한 것만 범주·계열로 쓴다 (규칙)

  requested_axes(sub_filter, filters)  → 질문이 요청한 나눔 (비교축 · 성별 2개 이상 · 지역 여러 곳)
  column_axis(col, values)             → 열이 어떤 축인지 (지역 · 연령 · 성별 · 그 밖이면 열 이름)
  classify_dims(dims, …)               → 열마다 requested(요청한 나눔) / range(범위 구성 요소) / extra(그 밖)

  - range : 연령 슬롯이 범위('65세 이상')이거나 대상이 연령을 뜻하는 말('고령자')인데 연령을 나눠 달라고 하지 않음
            → View 가 범위를 잘게 펼친 연령 구간 (더하면 요청한 값) → 범주에서 뺀다
  - extra : 요청하지 않았는데 값이 여러 개인 열 → 범주에서 빼고 경고
  - 안전장치: 요청한 나눔이 하나도 열에 맞지 않고 의도가 비교·순위·구성비면 extra 를 범주로 남긴다 (fallback)
"""
import re

from .chart_type_rules import (AGE_TARGET_WORDS, AXIS_COLUMN_HINTS, AXIS_WORDS, CATEGORY_INTENTS, REGION_SUFFIXES,
                               SEX_WORDS, TOTAL_WORDS)

TIME = "시점"
_AGE_VALUE = re.compile(r"\d+\s*(세|살)|세\s*이상|세이상")


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _pick(sub_filter, filters, key):
    """슬롯 값: 하위질문 조건이 있으면 그것, 없으면 전체 질문 조건"""
    return _as_list((sub_filter or {}).get(key)) or _as_list((filters or {}).get(key))


def requested_axes(sub_filter, filters):
    """질문이 요청한 나눔 (순서 유지). 시점은 비교축에 연도·시점이 있을 때만 들어간다"""
    axes = []
    for w in _pick(sub_filter, filters, "비교축"):
        a = AXIS_WORDS.get(str(w).strip(), str(w).strip())
        if a and a not in axes:
            axes.append(a)
    sexes = {s for s in _pick(sub_filter, filters, "성별") if s not in TOTAL_WORDS}
    if len(sexes) >= 2 and "성별" not in axes:
        axes.append("성별")
    regions = [r for r in _pick(sub_filter, filters, "지역") if r not in TOTAL_WORDS]
    if len(regions) >= 2 and "지역" not in axes:
        axes.append("지역")
    return axes


def age_is_range(sub_filter, filters):
    """연령이 '나눔'이 아니라 '범위'로 요청됐는가 (연령 슬롯이 있거나 대상이 연령을 뜻하는 말)"""
    return bool(_pick(sub_filter, filters, "연령")) or any(
        any(t in str(x) for t in AGE_TARGET_WORDS) for x in _pick(sub_filter, filters, "대상"))


def column_axis(col, values):
    """열 → 축 이름 (지역 · 연령 · 성별). 알아보지 못하면 열 이름 그대로"""
    name = str(col)
    for axis, hints in AXIS_COLUMN_HINTS.items():
        if any(h in name for h in hints):
            return axis
    vals = [str(v).strip() for v in values if str(v).strip() not in TOTAL_WORDS]
    if vals and all(any(w in v for w in SEX_WORDS) or v in ("남", "여") for v in vals):
        return "성별"
    if vals and all(_AGE_VALUE.search(v) for v in vals):
        return "연령"
    if vals and all(any(v.endswith(s) for s in REGION_SUFFIXES) for v in vals):
        return "지역"
    return name


def classify_dims(dims, sub_filter, filters, intents=None):
    """dims(값이 2개 이상인 열 목록: {"name", "col", "values", "n"}) → (요청한 나눔 dims, 뺀 dims, 메모 문장, 요청한 축)
    요청한 나눔 dims 는 질문이 요청한 순서로 정렬하고 각 dim 에 "axis" 를 붙인다. 뺀 dims 에는 "kind"(range · extra)"""
    req = requested_axes(sub_filter, filters)
    age_range = age_is_range(sub_filter, filters) and "연령" not in req
    kept, dropped, notes = [], [], []
    for d in dims:
        axis = column_axis(d["col"], d["values"])
        d = {**d, "axis": axis}
        if axis in req or any(a not in AXIS_COLUMN_HINTS and a != TIME and a in str(d["col"]) for a in req):
            kept.append(d)
        elif axis == "연령" and age_range:
            dropped.append({**d, "kind": "range"})
        else:
            dropped.append({**d, "kind": "extra"})

    # 안전장치: 요청한 나눔이 표의 어느 열에도 맞지 않으면, 비교·순위·구성비 질문은 그 밖 열을 범주로 남긴다
    if not kept and set(intents or []) & set(CATEGORY_INTENTS):
        back = [d for d in dropped if d["kind"] == "extra"]
        if back:
            kept = [{k: v for k, v in d.items() if k != "kind"} for d in back]
            dropped = [d for d in dropped if d["kind"] != "extra"]
            notes += [f"요청한 나눔에 맞는 열이 없어 '{d['col']}'({d['n']}개)을 범주로 씀" for d in kept]

    order = {a: i for i, a in enumerate(req)}
    kept.sort(key=lambda d: order.get(d["axis"], len(order)))
    for d in dropped:
        if d["kind"] == "range":
            notes.append(f"'{d['col']}' {d['n']}구간은 요청한 연령 범위의 구성 요소라 합계로 봄")
        else:
            notes.append(f"요청하지 않은 나눔 '{d['col']}'({d['n']}개)은 차트 판단에서 제외")
    return kept, dropped, notes, req
