"""평가기 기대 표시값 (criteria.md 4.2 (c)층)

팀 format_value 를 import 하지 않고 같은 명세로 독립 구현한다. 평가 대상 함수로 기대값을 만들면 그 함수의 결함을 잡지 못한다.
  원값 → Decimal(repr(v)) / Decimal(repr(unit_scale)) → quantize(10^-digits, ROUND_HALF_UP) → 0 이면 부호 제거 → 천 단위 쉼표 → 단위
자릿수 기본값 표(default_digits)와 단위 상수는 설정값이라 팀 모듈에서 가져온다. 반올림 · 부호 · 천명 규칙은 여기서 구현한다.
"""
from decimal import ROUND_HALF_UP, Decimal

from backend.agent.chart_calculate.display import NO_SUFFIX_UNITS, default_digits

CHEON, MAN, CHEON_TO_MAN = "천명", "만 명", 10


def digits_for(value, source_unit: str | None, unit_scale: float, digits: int | None, scaled: Decimal) -> int:
    if digits is not None:
        return digits
    d = default_digits(source_unit, unit_scale)
    if not source_unit and float(value).is_integer():
        d = 0
    if (source_unit, unit_scale) == (CHEON, CHEON_TO_MAN):
        d = 0 if scaled == 0 or abs(scaled) >= 100 else 1
    return d


def expected_display(value, source_unit: str | None, display_unit: str | None, unit_scale: float = 1,
                     digits: int | None = None) -> str | None:
    if value is None:
        return None
    scaled = Decimal(repr(value)) / Decimal(repr(unit_scale))
    dg = digits_for(value, source_unit, unit_scale, digits, scaled)
    rounded = scaled.quantize(Decimal(1).scaleb(-dg), rounding=ROUND_HALF_UP)
    if rounded == 0:
        rounded = abs(rounded)
    text = f"{rounded:,}"
    unit = display_unit if display_unit is not None else (source_unit or "")
    return text if unit in NO_SUFFIX_UNITS else text + unit


def from_display(value, display: dict | None) -> str | None:
    """Module3Output.displays[ref] (dict) 로 기대 표시값"""
    d = display or {}
    return expected_display(value, d.get("source_unit"), d.get("display_unit"), d.get("unit_scale") or 1, d.get("digits"))


def display_tolerance(display: dict | None) -> float:
    """문장에서 읽은 표시 숫자를 원값과 비교할 때의 원단위 허용오차 0.5 × 10^-digits × unit_scale"""
    d = display or {}
    scale = d.get("unit_scale") or 1
    dg = d.get("digits")
    if dg is None:
        dg = default_digits(d.get("source_unit"), scale)
    return 0.5 * 10 ** (-dg) * scale
