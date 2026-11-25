"""
[NEW] 행 선택 — Record.table.rows 에 select 조건을 적용하고, 계산에 쓸 수 있는지(검증 ① 데이터 존재) 함께 본다

  View 행 모양 (build_view): [시점, 분류 열…, 항목, 값]  — 시점은 문자열('2025'), 값은 숫자 또는 None
  계산 근거는 이 행뿐이다. Record.source 로 원본을 다시 조회하지 않는다 (명세 2장).
"""
import math
import re
from dataclasses import dataclass, field
from typing import Any

from backend.core.korean import strip_unit
from backend.schemas.record import Record

VALUE_COL = "값"
ITEM_COL = "항목"
# 범주 열을 이름으로 알아본다 (값이 지표가 아니라 범주인 열). 계산·계획·차트 구성이 같이 쓴다
REGION_HINTS = ("행정구역", "지역", "시도", "시군구")
AGE_HINTS = ("연령", "세별", "나이")          # 연령별, 5세별, 모의 연령(5세계급)별 …
CATEGORY_HINTS = AGE_HINTS + REGION_HINTS + ("성별",)
# [MOVED 11-25 6-5] calculate.py → 여기 (계산 · 차트 이름 · 답변 이름이 같이 쓴다. calculate.INDICATOR_HINTS 로도 그대로 읽힌다)
INDICATOR_HINTS = ("항목", "종류", "지표")   # 분류 열이지만 지표를 담는 이름 (DT_1B8000G '종류별', '기본항목별')
MISSING_TEXT = {"", "-", "…", "..."}          # KOSIS 가 빈 값을 표시하는 문자


_AGE = re.compile(r"(\d+)\s*(?:[-~]\s*(\d+))?\s*세(\s*이상)?")


def age_span(label: str) -> tuple[int, int | None] | None:
    """'0세' → (0, 0), '15~19세' → (15, 19), '65세 이상' → (65, None). 나이가 아니면 None ('계', '합계')"""
    m = _AGE.fullmatch(label.strip())
    if not m:
        return None
    lo = int(m[1])
    return lo, (None if m[3] else int(m[2] or lo))


def _with_description(wanted: str, have: set[str]) -> str:
    """[NEW 11-18] HCX 가 값의 앞부분만 적은 경우: '중위 추계' ↔ '중위 추계(기본 추계: 출산율-중위 / …)'. 설명 괄호가 붙은 값 하나만 있으면 그 값으로 읽는다.
    이전: 시나리오별에 없는 값으로 계산 전체가 실패했다 (Q01 · Q24). 이름 바로 뒤가 설명 괄호일 때만 · 후보가 하나뿐일 때만 · 나이 구간이 아닐 때만 (서울 ↔ 서울특별시, 65세 ↔ 65세 이상 은 건드리지 않는다)"""
    if wanted in have or len(wanted) < 2:
        return wanted
    if age_span(wanted) is not None:
        return wanted                      # 나이 · 연령 구간은 정확히 맞아야 한다 ('65세' 를 '65세 이상' 으로 바꾸지 않는다. 검토 12)
    hits = [v for v in have if v.startswith(wanted) and v[len(wanted):len(wanted) + 1] in ("(", "（")]
    return hits[0] if len(hits) == 1 else wanted


# [NEW 11-25] 정식 행정구역 이름 (옛 · 새 공식 명칭). 줄임말('서울' · '강원')은 맞추지 않는다 —
#   '이름 앞부분만 맞는다고 같은 지역으로 보지 않는다' (tests/chart_calculate/test_fix_1118_safety_nets.py)
_FULL_REGION = re.compile(r"(특별시|광역시|특별자치시|특별자치도|도|시)$")


def _same_region(col: str, wanted: str, have: set[str]) -> str | None:
    """[NEW 11-25 B-1] 지역 열에서 같은 시도의 다른 표기 (강원특별자치도 ↔ 강원도, 전북특별자치도 ↔ 전라북도, 세종특별자치시 ↔ 세종시 …).
    표준화는 검색 · View 쪽 사전(backend.rag.ingestion.normalize.std_geo_name — View 를 만들 때 지역을 알아보는 사전)을 그대로 쓴다.
    같은 질문 안에서도 표마다 시도 이름이 달라(출생아수 표는 강원특별자치도, 사망자수 표는 강원도) HCX 가 한쪽 이름을 다른 표에 적으면
    '시군구별에 없는 값' 으로 계산이 비었다 (15유형 테스트 버블 2 · 산점도 1). 표준 이름이 같은 값이 표에 하나뿐일 때만 바꾼다"""
    if not any(h in col for h in REGION_HINTS) or not _FULL_REGION.search(wanted.strip()):
        return None
    from backend.rag.ingestion.normalize import std_geo_name     # pandas · duckdb 를 불러오므로 값이 없을 때만 (모듈 로딩에 영향 없게)
    std = std_geo_name(wanted)
    hits = [v for v in have if _FULL_REGION.search(v.strip()) and std_geo_name(v) == std]
    return hits[0] if len(hits) == 1 else None


def _default_scenario(col: str, wanted: str, have: set[str]) -> str | None:
    """[NEW 11-25 B-2] 장래추계 시나리오 열에서 기본 시나리오를 앞부분만 적은 값 ('중위' → '중위 추계(기본 추계: 출산율-중위 / …)').
    기본 시나리오 판단은 검색 · View 쪽 기준(normalize.SCENARIO_DEFAULT_RE · SCENARIO_RE — View 가 기본 시나리오를 고를 때 쓰는 것)을 그대로 쓴다.
    조건 값과 표의 값이 둘 다 기본 시나리오이고, 표에 기본 시나리오 값이 하나뿐일 때만 바꾼다"""
    from backend.rag.ingestion.normalize import SCENARIO_DEFAULT_RE, SCENARIO_RE
    if not SCENARIO_RE.search(col) or not SCENARIO_DEFAULT_RE.search(wanted.strip()):
        return None
    hits = [v for v in have if SCENARIO_DEFAULT_RE.search(v.strip())]
    return hits[0] if len(hits) == 1 else None


def _match_value(col: str, wanted: str, have: set[str]) -> str:
    """조건 값 → 표에 적힌 값. 표에 그대로 있으면 그 값 (대부분). 없을 때만: 설명 괄호 → 같은 시도의 다른 표기 → 기본 시나리오
    [NEW 11-25] 이전: 설명 괄호(_with_description)만 맞췄다"""
    if wanted in have:
        return wanted
    got = _with_description(wanted, have)
    if got != wanted:
        return got
    return _same_region(col, wanted, have) or _default_scenario(col, wanted, have) or wanted


def is_category(col: str) -> bool:
    """지역·연령·성별처럼 더해도 되는 범주 열인가 (아니면 시점이거나 지표 열)"""
    return any(h in col for h in CATEGORY_HINTS)


def to_number(v: Any) -> int | float | None:
    """값 셀 → 숫자. 빈 값·기호·숫자가 아닌 문자열은 None. 원래 정밀도를 지키려고 int/float 는 그대로 돌려준다"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v if math.isfinite(v) else None       # [CHANGED 11-16] 이전: nan 만 거름 — inf 가 계산에 들어갔다 (검수 M3-18)
    s = str(v).strip().replace(",", "")
    if s in MISSING_TEXT:
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    return n if math.isfinite(n) else None          # [NEW 11-16] 문자열 nan · inf 도 숫자로 받지 않는다 (검수 M3-18)


def truncated_reason(record: Record) -> str | None:
    """행이 잘려 들어온 View 는 합계·순위·구성비가 틀릴 수 있어 계산에 쓰지 않는다"""
    for n in record.notes:
        if n.type == "truncated":
            return f"truncated: {n.text}"
    return None


def find_item_column(columns: list[str], rows: list[list], item: str) -> tuple[str, Any] | None:
    """operands[].item 이 가리키는 (열 이름, View 에 적힌 값). 없으면 None

    명세가 모호한 부분: View 의 항목 열은 '항목' 인데 명세 예시는 분류 열('종류별')에 항목 값을 넣는다.
    → '항목' 열을 먼저 보고, 없으면 그 값을 가진 다른 열을 찾는다. 팀 합의가 나오면 이 함수만 고친다.
    정확히 같은 값이 없으면 단위 괄호를 떼고 한 번 더 비교한다 ('혼인건수(건)' ↔ '혼인건수').
    """
    order = ([ITEM_COL] if ITEM_COL in columns else []) + [c for c in columns if c not in (ITEM_COL, VALUE_COL)]
    # [CHANGED 11-18] 이전: 끝 괄호를 모두 뗐다 → '인구(1세이상)(명)' 의 '(명)' 만 떼야 하는데 '(1세이상)' 도 떼어 다른 항목과 섞일 수 있었다.
    #                 단위로 읽히는 끝 괄호만 양쪽에서 뗀다 (설명 괄호는 항목 이름의 일부)
    bare = strip_unit(item)
    for exact in (True, False):
        for col in order:
            i = columns.index(col)
            for r in rows:
                cell = str(r[i])
                if cell == item if exact else strip_unit(cell) == bare:
                    return col, r[i]
    return None


@dataclass
class Selection:
    columns: list[str]
    rows: list[list] = field(default_factory=list)        # 값이 있는 행만. 값 열은 숫자로 바뀌어 있다
    errors: list[str] = field(default_factory=list)       # 이 선택으로 계산하면 안 되는 이유 (검증 ① 실패)
    dropped: list[dict] = field(default_factory=list)     # 값이 비어 제외한 행의 키 {열: 값}
    item: str | None = None                               # [NEW 11-16] View 에서 실제로 찾은 항목 이름 (요청한 이름과 괄호 단위만 다를 수 있다. 검수 M3-12)

    @property
    def ok(self) -> bool:
        return not self.errors

    def col(self, name: str) -> int:
        return self.columns.index(name)


def select_rows(record: Record, select: dict[str, list] | None = None, item: str | None = None) -> Selection:
    """select({열: [값…]}) 와 item 으로 행을 고른다

    - 비교는 문자열로 한다 (LLM 이 시점을 2025 로 주든 '2025' 로 주든 같은 값).
    - item 을 주면 그 항목 하나로 좁힌다 (select 의 같은 열 조건보다 우선).
    - 값이 빈 행은 rows 에서 빼고 dropped 에 남긴다. 그 행이 꼭 필요한지는 부르는 쪽이 판단한다
      (예: growth_rate 의 from 시점이 dropped 에 있으면 계산 불가, 추이 차트면 결측 제외 경고).
    """
    cols, rows = list(record.table.columns), record.table.rows
    sel = Selection(columns=cols)
    if why := truncated_reason(record):
        sel.errors.append(why)
    if VALUE_COL not in cols:
        sel.errors.append(f"'{VALUE_COL}' 열 없음")
        return sel

    conds: dict[int, set[str]] = {}
    for name, wanted in (select or {}).items():
        if name not in cols:
            sel.errors.append(f"열 없음: {name}")
            continue
        i = cols.index(name)
        have = {str(r[i]) for r in rows}
        wanted = [_match_value(name, str(w), have) for w in wanted]      # [CHANGED 11-25] 이전: _with_description 만
        if absent := [w for w in wanted if str(w) not in have]:
            sel.errors.append(f"{name}에 없는 값: {absent}")
        conds[i] = {str(w) for w in wanted}
    if item is not None:
        if hit := find_item_column(cols, rows, item):
            conds[cols.index(hit[0])] = {str(hit[1])}
            sel.item = str(hit[1])
        else:
            sel.errors.append(f"항목 없음: {item}")

    vi = cols.index(VALUE_COL)
    for r in rows:
        if not all(str(r[i]) in want for i, want in conds.items()):
            continue
        n = to_number(r[vi])
        if n is None:
            sel.dropped.append({c: r[j] for j, c in enumerate(cols) if j != vi})
        else:
            sel.rows.append([*r[:vi], n, *r[vi + 1:]])
    if not sel.rows:
        sel.errors.append("조건에 맞는 값이 없음")
    return sel
