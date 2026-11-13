"""
[NEW] 축 범위 계산 — 숫자 축의 min · max (명세 4장 axis.min/max, 8장 차트별 축 규칙)

  axis_range(values, rule) → (min, max)         값이 하나도 없으면 (None, None)

  rule           min                          max                              쓰는 차트
  free           데이터 최솟값 − 여백 후 내림   데이터 최댓값 + 여백 후 올림       line · combo · 이중 축 · scatter · bubble · dumbbell
  include_zero   min(0, 최솟값) (반올림 없음)   max(0, 최댓값) + 여백 후 올림       bar          (명세 8장 "y 범위에 0 포함")
  zero           0                            최댓값 + 여백 후 올림               stacked_bar · area  (명세 8장 "y.min = 0")
  symmetric      −M                           +M (M = 절댓값 최댓값 + 여백 후 올림) pyramid     (명세 8장 "좌우 대칭")

  - 눈금 간격(step)은 1·2·5 × 10ⁿ 중 목표 눈금 수(TARGET_TICKS)를 넘지 않는 가장 작은 값이다. min·max 는 step 의 배수로 맞춘다.
    step 은 여백을 더하기 전 데이터 범위(span)로 정한다 (여백까지 넣으면 step 이 한 단계 커져 범위가 헐거워진다).
  - 값이 모두 정수(개수)면 step ≥ 1 (개수 축에 3.5건 눈금이 생기지 않게).
  - 데이터가 0 이상이면 여백 때문에 min 이 음수로 내려가지 않는다 (0 이하 데이터는 max 가 0 위로 올라가지 않는다).
  - 값은 원값 기준이다. 표시 단위 환산은 displays 가 하므로 여기서 하지 않는다.
  - log 척도는 다루지 않는다 (scale="log" 는 만들지 않기로 했다).
"""
import math
from typing import Any

PAD = 0.05             # 데이터 범위의 5% 를 양쪽 여백으로
TARGET_TICKS = 5       # 눈금 간격을 정할 때 span 을 나눌 개수

RULES = ("free", "include_zero", "zero", "symmetric")


def numbers(values) -> list[float]:
    """숫자만 (None · 문자열 · bool · NaN · inf 는 뺀다)"""
    return [float(v) for v in values
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]


def nice_step(span: float, ticks: int = TARGET_TICKS, integer: bool = False) -> float:
    """span 을 ticks 칸으로 나눈 간격 이상인 1·2·5 × 10ⁿ. integer 면 1 이상"""
    raw = span / ticks
    exp = math.floor(math.log10(raw))
    frac = raw / 10 ** exp
    step = next(f for f in (1, 2, 5, 10) if frac <= f + 1e-9) * 10.0 ** exp
    return max(step, 1.0) if integer else step


def _snap(x: float, step: float, up: bool) -> float:
    """x 를 step 의 배수로 내림/올림. 부동소수 오차(0.30000000000000004)가 남지 않게 step 의 자릿수로 반올림"""
    k = math.ceil(x / step - 1e-9) if up else math.floor(x / step + 1e-9)
    return round(k * step, max(0, -math.floor(math.log10(step))))


def axis_range(values, rule: str = "free", *, pad: float = PAD, ticks: int = TARGET_TICKS):
    """→ (min, max). rule 은 모듈 머리말 표 참고"""
    if rule not in RULES:
        raise ValueError(f"알 수 없는 축 규칙: {rule} (허용: {', '.join(RULES)})")
    nums = numbers(values)
    if not nums:
        return None, None
    lo, hi = min(nums), max(nums)
    integer = all(v.is_integer() for v in nums)

    if rule == "symmetric":
        m = max(abs(lo), abs(hi)) or 1.0
        step = nice_step(2 * m, ticks, integer)
        top = _snap(m * (1 + pad), step, up=True)
        return -top, top

    if rule in ("zero", "include_zero"):
        base_lo = 0.0 if rule == "zero" else min(0.0, lo)
        base_hi = max(0.0, hi)
        span = base_hi - base_lo
        if span == 0:                                   # 값이 모두 0
            return base_lo, 1.0
        step = nice_step(span, ticks, integer)
        return base_lo, _snap(base_hi + pad * span, step, up=True)

    # free
    span = hi - lo
    if span == 0:                                       # 값이 모두 같다 → 그 값 둘레로 넓힌다
        delta = max(abs(hi) * pad, 1.0)
        step = nice_step(2 * delta, ticks, integer)
        low, high = lo - delta, hi + delta
    else:
        step = nice_step(span, ticks, integer)
        low, high = lo - pad * span, hi + pad * span
    if lo >= 0:                                         # 개수·비율은 여백 때문에 0 아래로 내려가지 않는다
        low = max(low, 0.0)
    if hi <= 0:
        high = min(high, 0.0)
    out_lo, out_hi = _snap(low, step, up=False), _snap(high, step, up=True)
    return (out_lo, out_hi) if out_lo != out_hi else (out_lo, _snap(out_hi + step, step, up=True))


def group_sums(keys, values) -> dict[Any, float]:
    """키(예: 같은 x)별 합계. 누적 막대의 max 는 개별 값이 아니라 이 합계의 최댓값이다. 숫자가 아닌 값은 뺀다"""
    out: dict[Any, float] = {}
    for k, v in zip(keys, values):
        if numbers([v]):
            out[k] = out.get(k, 0.0) + float(v)
    return out
