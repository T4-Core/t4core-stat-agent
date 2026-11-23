"""평가 정규형 (계획 2.4, D-24)

M3 결과는 표시 이전부터 % 단위다 (share = part ÷ total × 100, growth_rate · cagr 도 × 100).
기대값은 정규형으로 적고, 비교 직전에 관측값도 정규형으로 바꾼다. 모듈 입력(Oracle)에는 쓰지 않는다.
"""
from dataclasses import dataclass

PERCENT, POINT = "%", "%p"
SCALED = {"천명": ("명", 1000), "만명": ("명", 10000), "만 명": ("명", 10000), "천가구": ("가구", 1000),
          "천호": ("호", 1000), "천원": ("원", 1000), "백만원": ("원", 1_000_000), "억원": ("원", 100_000_000),
          "십억원": ("원", 1_000_000_000), "조원": ("원", 1_000_000_000_000)}
CONVERTIBLE = {u: base for u, (base, _) in SCALED.items()}


@dataclass(frozen=True)
class Norm:
    value: float | None
    unit: str | None


def normalize(value, unit: str | None) -> Norm:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return Norm(None, unit)
    u = (unit or "").strip() or None
    if u == PERCENT:
        return Norm(value / 100, "ratio")
    if u == POINT:
        return Norm(value / 100, "pp")
    if u == "배":
        return Norm(float(value), "times")
    if u in SCALED:
        base, k = SCALED[u]
        return Norm(value * k, base)
    return Norm(float(value), u)


def convertible(a: str | None, b: str | None) -> bool:
    """서로 다르지만 같은 기본 단위로 환산되는가 (천명 ↔ 명). %와 %p 는 환산하지 않는다"""
    if not a or not b or a == b:
        return False
    base = lambda u: CONVERTIBLE.get(u, u)  # noqa: E731
    return base(a) == base(b) and PERCENT not in (a, b) and POINT not in (a, b)


def close(pred: float | None, gold: float, atol: float = 0.0, rtol: float = 0.0) -> bool:
    if pred is None:
        return False
    return abs(pred - gold) <= atol + rtol * abs(gold)


def comparable(a: Norm, b_unit: str | None) -> bool:
    """정규형 단위가 같아야 비교한다. ratio 와 pp 는 서로 비교하지 않는다"""
    if a.unit in ("ratio", "pp") or b_unit in ("ratio", "pp"):
        return a.unit == b_unit
    return (a.unit or None) == (b_unit or None) or not a.unit or not b_unit
