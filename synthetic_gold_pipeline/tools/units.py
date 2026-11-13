"""단위 · 스케일 · 원본 값 파싱 (Calculation Tool 과 Adapter 가 함께 쓰는 결정론적 규칙).

- 단위는 (family, multiplier, kind) 로 관리한다. 같은 family 끼리만 변환·합산 가능.
- 원본 값의 결측 기호("-", "*", "X", "NaN", "", NULL …)는 절대 0 으로 바꾸지 않는다.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, getcontext

from synthetic_gold_pipeline.schemas.metadata import ValueKind

getcontext().prec = 40


NON_ADDITIVE_NAME = re.compile(r"평균|중위|중앙값|비율|비중|구성비|백분율|율$|률$|율\(|률\(|지수|밀도|성비|배율|당\s*\S*$")


def name_is_additive(itm_nm: str | None) -> bool:
    """항목 이름이 평균·비율·지수를 뜻하면 False ('평균 가구원수(명)', '고령인구비율(%)')"""
    return not NON_ADDITIVE_NAME.search(str(itm_nm or ""))


@dataclass(frozen=True)
class UnitInfo:
    raw: str
    canonical: str
    family: str | None
    multiplier: Decimal | None
    kind: ValueKind
    base_unit: str | None

    @property
    def additive(self) -> bool:
        return self.kind in (ValueKind.COUNT, ValueKind.AMOUNT)

    @property
    def known(self) -> bool:
        return self.family is not None and self.multiplier is not None


_SCALE = {"": Decimal(1), "십": Decimal(10), "백": Decimal(100), "천": Decimal(1000), "만": Decimal(10_000),
          "십만": Decimal(100_000), "백만": Decimal(1_000_000), "천만": Decimal(10_000_000),
          "억": Decimal(100_000_000), "십억": Decimal(1_000_000_000), "백억": Decimal(10_000_000_000),
          "천억": Decimal(100_000_000_000), "조": Decimal(1_000_000_000_000)}

# 기본 단위: family → (base 표기, kind)
_BASE = {
    "명": ("PERSON", ValueKind.COUNT), "인": ("PERSON", ValueKind.COUNT),
    "가구": ("HOUSEHOLD", ValueKind.COUNT), "세대": ("HOUSEHOLD", ValueKind.COUNT),
    "호": ("DWELLING", ValueKind.COUNT), "건": ("CASE", ValueKind.COUNT), "개": ("ITEM", ValueKind.COUNT),
    "개소": ("ESTABLISHMENT", ValueKind.COUNT), "원": ("KRW", ValueKind.AMOUNT), "달러": ("USD", ValueKind.AMOUNT),
}
_FIXED = {
    "%": ("PERCENT", Decimal(1), ValueKind.RATE, "%"), "퍼센트": ("PERCENT", Decimal(1), ValueKind.RATE, "%"),
    "%p": ("PERCENT_POINT", Decimal(1), ValueKind.RATE, "%p"),
    "‰": ("PERMILLE", Decimal(1), ValueKind.RATE, "‰"), "퍼밀": ("PERMILLE", Decimal(1), ValueKind.RATE, "‰"),
    "세": ("AGE_YEAR", Decimal(1), ValueKind.MEAN, "세"), "년": ("YEAR_DURATION", Decimal(1), ValueKind.MEAN, "년"),
    "지수": ("INDEX", Decimal(1), ValueKind.INDEX, "지수"), "배": ("RATIO", Decimal(1), ValueKind.RATE, "배"),
    "명/㎢": ("DENSITY", Decimal(1), ValueKind.RATE, "명/㎢"), "명/km²": ("DENSITY", Decimal(1), ValueKind.RATE, "명/㎢"),
}
# '인구 천명당', '천명당' 같은 비율 단위
_PER = re.compile(r"^(?:인구)?(십|백|천|만|십만)?(명|가구|건)당(?:.*)$")


def canonical_unit(raw: str | None) -> str:
    s = str(raw or "").strip()
    s = re.sub(r"\s+", "", s)
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"^\((.*)\)$", r"\1", s)
    return s


def unit_info(raw: str | None) -> UnitInfo:
    c = canonical_unit(raw)
    if not c:
        return UnitInfo(str(raw or ""), "", None, None, ValueKind.UNKNOWN, None)
    if c in _FIXED:
        fam, mul, kind, base = _FIXED[c]
        return UnitInfo(str(raw), c, fam, mul, kind, base)
    m = _PER.match(c)
    if m:
        return UnitInfo(str(raw), c, f"PER_{_BASE[m.group(2)][0]}_{m.group(1) or ''}", Decimal(1), ValueKind.RATE, c)
    for base in sorted(_BASE, key=len, reverse=True):
        if c.endswith(base):
            prefix = c[: -len(base)]
            if prefix in _SCALE:
                fam, kind = _BASE[base]
                return UnitInfo(str(raw), c, fam, _SCALE[prefix], kind, base)
    return UnitInfo(str(raw), c, None, None, ValueKind.UNKNOWN, None)


class UnitIncompatible(ValueError):
    pass


def conversion_factor(from_unit: str, to_unit: str) -> Decimal:
    a, b = unit_info(from_unit), unit_info(to_unit)
    if not (a.known and b.known):
        raise UnitIncompatible(f"알 수 없는 단위: {from_unit!r} → {to_unit!r}")
    if a.family != b.family:
        raise UnitIncompatible(f"단위 계열이 다름: {from_unit}({a.family}) → {to_unit}({b.family})")
    return a.multiplier / b.multiplier


def convert_value(value: Decimal, from_unit: str, to_unit: str) -> tuple[Decimal, Decimal]:
    f = conversion_factor(from_unit, to_unit)
    return value * f, f


def common_base_unit(units: list[str]) -> str:
    """같은 family 의 단위들 → 기본 단위 (예: 천명, 명 → 명). 하나라도 다른 family 면 오류."""
    infos = [unit_info(u) for u in units]
    if not all(i.known for i in infos):
        raise UnitIncompatible(f"알 수 없는 단위 포함: {units}")
    fams = {i.family for i in infos}
    if len(fams) != 1:
        raise UnitIncompatible(f"단위 계열이 다름: {units}")
    if len({i.canonical for i in infos}) == 1:
        return infos[0].canonical
    return infos[0].base_unit or infos[0].canonical


# ── 원본 값 파싱 ───────────────────────────────────────────────────
MISSING_SYMBOLS = {"-", "*", "X", "x", "…", "...", "..", "‥", "－", "−"}
NAN_STRINGS = {"nan", "NaN", "NAN", "NA", "N/A", "n/a", "null", "NULL", "None"}
_NUM = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")


@dataclass
class ParsedValue:
    status: str                    # NUMERIC | SYMBOL | EMPTY | NULL | NAN_STRING | INVALID
    value: Decimal | None
    raw: str | None
    symbol: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "NUMERIC" and self.value is not None


def parse_value(raw) -> ParsedValue:
    if raw is None:
        return ParsedValue("NULL", None, None)
    if isinstance(raw, float) and math.isnan(raw):
        return ParsedValue("NULL", None, None)
    if isinstance(raw, (int, Decimal)) and not isinstance(raw, bool):
        return ParsedValue("NUMERIC", Decimal(raw), str(raw))
    if isinstance(raw, float):
        if math.isinf(raw):
            return ParsedValue("INVALID", None, str(raw), notes=["infinite"])
        return ParsedValue("NUMERIC", Decimal(repr(raw)), str(raw))
    s = str(raw).strip()
    if s == "":
        return ParsedValue("EMPTY", None, str(raw))
    if s in NAN_STRINGS:
        return ParsedValue("NAN_STRING", None, s)
    if s in MISSING_SYMBOLS:
        return ParsedValue("SYMBOL", None, s, symbol=s)
    t = s.replace(" ", "")
    if _NUM.match(t):
        try:
            return ParsedValue("NUMERIC", Decimal(t.replace(",", "")), s)
        except InvalidOperation:  # pragma: no cover
            pass
    return ParsedValue("INVALID", None, s, notes=["not a number"])


def is_finite_decimal(v: Decimal | None) -> bool:
    return v is not None and v.is_finite()
