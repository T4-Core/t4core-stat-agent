"""
[NEW] 표시 설정 (displays) — 단위 판단, digits 기본값, 표시 문자열

  계산은 항상 원래 정밀도로 하고, 단위 환산·반올림은 표시할 때 여기서 한 번만 한다 (명세 4장 "표시 설정").
  format_value 는 차트·표·답변이 같은 모양을 쓰도록 모듈 5·6 도 이 함수를 부르라고 둔 것이다.
"""
import re
from decimal import ROUND_HALF_UP, Decimal

from backend.schemas.chart import Display

_UNIT = re.compile(r"\(([^()]+)\)\s*$")

# 단위 종류별 digits 기본값 (명세 4장 표). 표에 없는 단위는 OTHER_DIGITS
COUNT_UNITS = {"명", "건", "가구", "개", "호"}
RATE_UNITS = {"%", "천명당", "‰"}
MONEY_UNITS = {"원", "천원", "백만원"}
INDEX_UNIT = "index"
# HCX 가 단위 목록에서 한 단어로 골라도 되는 표준 단위 (planner.hcx_unit). 목록에 없는 단위는 승인하지 않는다 → 단위 없음
STANDARD_UNITS = COUNT_UNITS | RATE_UNITS | MONEY_UNITS | {
    "천명", "만명", "천가구", "천호", "십억원", "억원", "조원", "천달러", "백만달러", "세", "년", "개월", "일", "시간", "회", "배",
    "㎡", "㎢", "ha", "kg", "톤", "대"}
OTHER_DIGITS = 1
# 명세의 표시 예("조혼인율 4.7", "115.5")에서 단위를 붙이지 않은 것들
NO_SUFFIX_UNITS = {INDEX_UNIT, "천명당"}

# 결과 단위가 바뀌는 연산 (명세 4장). 여기 없는 연산은 입력 단위를 그대로 쓴다
# TODO(후속 명세): ratio 의 결과 단위는 아직 정해지지 않았다. 임시로 '배'
# rank 는 넣지 않는다: 값은 원래 단위 그대로이고 순위는 별도 필드(calculate._rank 의 extra["rank"])라서
RESULT_UNIT = {"growth_rate": "%", "cagr": "%", "share": "%", "index": INDEX_UNIT, "ratio": "배"}


def unit_of(item: str | None, fallback: str | None = None) -> str | None:
    """항목 이름의 괄호 부분 ('혼인건수(건)' → '건')

    괄호가 없으면 fallback(View metadata.unit)을 쓰되, 단위가 하나일 때만 쓴다.
    metadata.unit 은 '명 건' 처럼 여러 단위가 붙어 올 수 있어 기준이 못 된다 (명세 4장).
    """
    if item and (m := _UNIT.search(item)):
        return m.group(1).strip()
    if fallback and len(fallback.split()) == 1:
        return fallback.strip()
    return None


def strip_unit(item: str) -> str:
    """'혼인건수(건)' → '혼인건수' (축 이름·범례용)"""
    return _UNIT.sub("", item).strip()


def result_unit(op: str, unit: str | None) -> str | None:
    return RESULT_UNIT.get(op, unit)


def default_digits(unit: str | None, unit_scale: float = 1) -> int:
    if unit_scale > 1:          # 단위 환산을 쓴 경우가 단위 종류보다 우선 (192,507건 → 19.3만 건)
        return 1
    if unit in COUNT_UNITS or unit in MONEY_UNITS:
        return 0
    if unit in RATE_UNITS or unit == INDEX_UNIT:
        return 1
    return OTHER_DIGITS


def make_display(source_unit: str | None, display_unit: str | None = None, unit_scale: float = 1,
                 digits: int | None = None) -> Display:
    unit = source_unit or ""
    return Display(source_unit=unit, display_unit=unit if display_unit is None else display_unit,
                   unit_scale=unit_scale, digits=digits)


def register(displays: dict[str, Display], display: Display) -> str:
    """displays 에 넣고 display_ref 를 돌려준다. 같은 설정이 이미 있으면 그 키를 다시 쓴다

    같은 근거값을 쓰는 차트·표·답변이 같은 display_ref 를 가리켜야 세 곳의 숫자 모양이 같아진다.
    """
    for ref, d in displays.items():
        if d == display:
            return ref
    ref = f"d{len(displays) + 1}"
    displays[ref] = display
    return ref


def format_value(value: float | int | None, display: Display) -> str | None:
    """원값 ÷ unit_scale → digits 자리로 한 번 반올림 → display_unit"""
    if value is None:
        return None
    digits = display.digits if display.digits is not None else default_digits(display.source_unit, display.unit_scale)
    if display.digits is None and not display.source_unit and float(value).is_integer():
        digits = 0       # 단위를 모르는데 정수면 소수 자리를 붙이지 않는다 (44,565.0 → 44,565)
    # float 의 round() 는 은행가 반올림(0.5 → 짝수)이라 2.5 → 2 가 된다. 사람이 기대하는 사사오입으로 맞춘다
    scaled = Decimal(repr(value)) / Decimal(repr(display.unit_scale))
    text = f"{scaled.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP):,}"
    return text if display.display_unit in NO_SUFFIX_UNITS else text + display.display_unit
