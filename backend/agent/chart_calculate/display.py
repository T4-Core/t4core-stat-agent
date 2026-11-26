"""
[NEW] 표시 설정 (displays) — 단위 판단, digits 기본값, 표시 문자열

  계산은 항상 원래 정밀도로 하고, 단위 환산·반올림은 표시할 때 여기서 한 번만 한다 (명세 4장 "표시 설정").
  format_value 는 차트·표·답변이 같은 모양을 쓰도록 모듈 5·6 도 이 함수를 부르라고 둔 것이다.
"""
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from backend.schemas.chart import Display

from backend.agent.chart_calculate.select import INDICATOR_HINTS, ITEM_COL
from backend.core.korean import UNIT_TAIL as _UNIT, strip_unit, unit_tail  # noqa: F401  [MOVED 11-17] core/korean.py


def indicator_name(item: str | None, coords: dict[str, Any] | None) -> str | None:
    """[NEW 11-25 6-5] 화면에 쓸 지표 이름 (단위 괄호 포함 원래 값. 쓰는 쪽에서 strip_unit)

    항목 열 값에 단위 괄호가 없고, 같은 행의 지표형 분류 열(이름에 항목 · 종류 · 지표가 든 열. 항목 열 자체는 빼고) 값 중
    단위 괄호가 있는 것이 정확히 하나면 그 값을 쓴다. 아니면 항목 값 그대로.
      DT_1B8000G: 항목 '출생사망혼인이혼' · 종류별 '조혼인율(천명당)' → '조혼인율(천명당)'
    단위 괄호가 없는 값('거처종류별: 계')은 지표 이름인지 알 수 없어 쓰지 않는다.
    차트의 축 · 범례 · 제목(모듈 3 content.shown_item, 5-0)과 답변의 계산 이름(모듈 6 facts.item)이 같은 규칙을 쓴다.
    이름만 바꾼다 — 행을 찾는 데는 항목 값을 그대로 쓴다"""
    if item and unit_tail(item):
        return item
    hits = [str(v) for c, v in (coords or {}).items()
            if c != ITEM_COL and any(h in c for h in INDICATOR_HINTS) and unit_tail(str(v))]
    return hits[0] if len(hits) == 1 else item

# 단위 종류별 digits 기본값 (명세 4장 표). 표에 없는 단위는 OTHER_DIGITS
COUNT_UNITS = {"명", "건", "가구", "개", "호"}
RATE_UNITS = {"%", "%p", "천명당", "‰"}
MONEY_UNITS = {"원", "천원", "백만원"}
INDEX_UNIT = "index"
# HCX 가 단위 목록에서 한 단어로 골라도 되는 표준 단위 (planner.hcx_unit). 목록에 없는 단위는 승인하지 않는다 → 단위 없음
STANDARD_UNITS = COUNT_UNITS | RATE_UNITS | MONEY_UNITS | {
    "천명", "만명", "천가구", "천호", "십억원", "억원", "조원", "천달러", "백만달러", "세", "년", "개월", "일", "시간", "회", "배",
    "㎡", "㎢", "ha", "kg", "톤", "대"}
OTHER_DIGITS = 1
# 명세의 표시 예("조혼인율 4.7", "115.5")에서 단위를 붙이지 않은 것들
NO_SUFFIX_UNITS = {INDEX_UNIT, "천명당"}

# 결과 단위가 바뀌는 연산 (명세 4장). 여기 없는 연산은 입력 단위를 그대로 쓴다 (change · diff 의 % → %p 는 아래 result_unit)
# TODO(후속 명세): ratio 의 결과 단위는 아직 정해지지 않았다. 임시로 '배'
# rank 는 넣지 않는다: 값은 원래 단위 그대로이고 순위는 별도 필드(calculate._rank 의 extra["rank"])라서
RESULT_UNIT = {"growth_rate": "%", "cagr": "%", "share": "%", "index": INDEX_UNIT, "ratio": "배"}


def unit_of(item: str | None, fallback: str | None = None) -> str | None:
    """항목 이름의 괄호 부분 ('혼인건수(건)' → '건')

    괄호가 없으면 fallback(View metadata.unit)을 쓰되, 단위가 하나일 때만 쓴다.
    metadata.unit 은 '명 건' 처럼 여러 단위가 붙어 올 수 있어 기준이 못 된다 (명세 4장).
    [NEW 11-24] 단위가 여러 개면 항목 이름(끝의 '수' 를 뗀 것)이 그 단위로 끝나는 것이 정확히 하나일 때만 그 단위를 쓴다.
      '가구 명' + '일반가구수' → 가구 ('일반가구' 가 '가구' 로 끝남) · '일반가구원수' → 없음 ('일반가구원').
      이전: 항상 없음 → 다른 표의 분모와 단위를 맞춰 볼 수 없어 비중을 계산하지 못했다 ('가구 / ?', 골든셋 SG-05ddfdd48569)
    """
    if unit := unit_tail(item):       # [CHANGED 11-18] 이전: 끝 괄호를 모두 단위로 읽음 ('인구(1세이상)' → '1세이상')
        return unit
    units = (fallback or "").split()
    if len(units) == 1:
        return units[0]
    stem = re.sub(r"수$", "", re.sub(r"\s+|\(.*?\)", "", item or ""))
    hits = [u for u in dict.fromkeys(units) if stem.endswith(u)] if stem else []
    return hits[0] if len(hits) == 1 else None


# [NEW 11-13] 비율(%)끼리의 증감·차이는 %p 다 (15.2% → 17.8% 는 2.6%p 증가). growth_rate · cagr 는 상대 변화율이라 % 그대로
PERCENT_POINT = "%p"
POINT_OPS = {"change", "diff"}


def ratio_unit(a: str | None, b: str | None) -> str | None:
    """ratio 의 결과 단위: 같으면 배, 다르면 a/b. 한쪽이라도 모르면 단위 없음 (예전에는 건/None 글자가 나왔다. 검수 M3-14)"""
    if a == b:
        return RESULT_UNIT["ratio"]
    return f"{a}/{b}" if a and b else None


def result_unit(op: str, unit: str | None) -> str | None:
    if op in POINT_OPS and unit == "%":
        return PERCENT_POINT
    return RESULT_UNIT.get(op, unit)


MAX_DATA_DIGITS = 3      # [NEW 11-16] 원 자료의 소수 자릿수를 따르되 최대 3자리 (검수 D-2)


def decimals_of(value: float | int | None, cap: int = MAX_DATA_DIGITS) -> int:
    """값의 소수 자릿수 (최대 cap). 0.1 + 0.2 = 0.30000000000000004 같은 부동소수 오차는 6자리 반올림으로 없앤 뒤 센다"""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return 0
    exp = Decimal(repr(round(float(value), 6))).normalize().as_tuple().exponent
    return min(max(-exp, 0), cap) if isinstance(exp, int) else 0


def data_digits(values, unit: str | None, integer_rule: bool = True) -> int | None:
    """계산하지 않은 원 자료 값들의 표시 자릿수. 단위 기본값보다 소수가 더 필요할 때만 값을 돌려준다 (아니면 None = 기본값).
    '합계출산율 0.721명' 이 단위(명)의 기본 자릿수 0 때문에 '1명' 이 되던 것을 막는다 (검수 M3-03)"""
    need = max((decimals_of(v) for v in values), default=0)
    # integer_rule=False: 평균처럼 정수 입력에서도 소수가 생기는 결과 (50 · 51 의 평균 50.5). 입력이 정수라는 이유로 0자리로 하지 않는다 (검수 6)
    if integer_rule and need == 0 and unit and unit not in COUNT_UNITS | RATE_UNITS | MONEY_UNITS | {INDEX_UNIT}:
        return 0           # 표에 없는 단위(천명 · 만원)의 정수 값에 '50.0천명' 처럼 소수를 붙이지 않는다
    return need if need > default_digits(unit) else None


def default_digits(unit: str | None, unit_scale: float = 1) -> int:
    if unit_scale > 1:          # 단위 환산을 쓴 경우가 단위 종류보다 우선 (192,507건 → 19.3만 건)
        return 1
    if unit in COUNT_UNITS or unit in MONEY_UNITS:
        return 0
    if unit in RATE_UNITS or unit == INDEX_UNIT:
        return 1
    return OTHER_DIGITS


CHEON_MYEONG, MAN_MYEONG, CHEON_TO_MAN = "천명", "만 명", 10     # 9,340천명 → 934만 명 (읽기 쉬운 단위. 결정: 천명 단위만 환산)


def make_display(source_unit: str | None, display_unit: str | None = None, unit_scale: float = 1,
                 digits: int | None = None, *, auto_digits: int | None = None) -> Display:
    """표시 설정. digits 는 **호출자가 정한** 자릿수(명시 설정), auto_digits 는 원 자료에서 코드가 구한 자릿수(자동 값)다.
    [CHANGED 11-18] 이전: 둘을 구분하지 않아 천명 자료의 명시 digits 도 버렸다 (검토 9). 천명 자료는 단위 환산(display_unit · unit_scale ·
    digits)을 하나도 정하지 않았을 때만 만 명으로 보여 준다: 자릿수는 값 크기로 format_value 가 정한다(자동 값은 환산 뒤에 맞지 않아 쓰지 않는다)"""
    unit = source_unit or ""
    if unit == CHEON_MYEONG and display_unit is None and unit_scale == 1 and digits is None:
        return Display(source_unit=unit, display_unit=MAN_MYEONG, unit_scale=CHEON_TO_MAN, digits=None)
    return Display(source_unit=unit, display_unit=unit if display_unit is None else display_unit,
                   unit_scale=unit_scale, digits=digits if digits is not None else auto_digits)


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
    # float 의 round() 는 은행가 반올림(0.5 → 짝수)이라 2.5 → 2 가 된다. 사람이 기대하는 사사오입으로 맞춘다
    scaled = Decimal(repr(value)) / Decimal(repr(display.unit_scale))
    digits = display.digits if display.digits is not None else default_digits(display.source_unit, display.unit_scale)
    if display.digits is None and not display.source_unit and float(value).is_integer():
        digits = 0       # 단위를 모르는데 정수면 소수 자리를 붙이지 않는다 (44,565.0 → 44,565)
    if display.digits is None and (display.source_unit, display.display_unit, display.unit_scale) == (CHEON_MYEONG, MAN_MYEONG, CHEON_TO_MAN):
        digits = 0 if scaled == 0 or abs(scaled) >= 100 else 1      # [NEW 11-18] 934만 명 · 37.9만 명 · 0만 명 (100만 이상은 소수 없이)
    rounded = scaled.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    if rounded == 0:
        rounded = abs(rounded)      # [NEW 11-16] -0.04 → '-0.0%' · -0.4 → '-0건' 이 아니라 '0.0%' · '0건' (검수 M3-16)
    text = f"{rounded:,}"
    return text if display.display_unit in NO_SUFFIX_UNITS else text + display.display_unit
