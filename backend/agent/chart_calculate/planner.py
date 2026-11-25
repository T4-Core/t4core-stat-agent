"""
[NEW] 계획 세우기 (규칙 부분) — HCX 의 결정(Decision) + 모듈 2 의 charts[] → ChartPlan + displays

  역할 분담 (명세 4장)
    HCX   Decision 만 정한다: 어느 View 의 어느 행을 쓸지(record_id·select·item), 기간, 분모 범위, 질문용 연산
    규칙  나머지를 채운다: step_id, 갈래 나누기, output, 단위, display_ref, 구성비 분모 기본값

  이 파일은 HCX 를 부르지 않는다. Decision 을 만드는 쪽(HCX 호출·응답 파싱)은 decide.py (6b 단계).

  바로잡기: HCX 응답에서 규칙으로 확실히 고칠 수 있는 실수는 계획을 만들기 전에 고치고 notes 에 남긴다 (_Planner.normalize_*).
    - 피연산자가 아닌 것 (role "join_on", item 이 열 이름) → 버림
    - 피연산자 1개짜리 연산에 같은 항목을 여럿으로 쪼갬 → 조건을 합쳐 하나로
    - 기간 연산(from·to·base)인데 시점 조건에 그 시점이 없음 → 시점 조건에 보탬
    - 갈래가 여럿인 차트(combo …)의 역할이 그 차트에 없음 → 빈 역할에 순서대로
    - QueryBundle 필터의 시점·지역은 고정: 밖의 값을 고르면 고정 값으로 바꾼다 (fix_time, fix_region)
    - 증감·증감률(change·growth_rate)은 View 에 있는 시점마다 직전 시점 대비 (base "prev").
      시점 조건은 고정 시점(없으면 View 의 모든 시점). 시점이 둘이면 결과 하나, 다섯이면 넷
      구성비의 분모(denominator)는 고정하지 않는다 ('전국 대비 서울' 의 전국은 지역 필터 밖이어도 필요하다)
    - 질문에 연령 범위가 있고(미취학아동 = 0~5세) raw 가 나이별 행 여럿을 고르면 → 합계(aggregate sum) 하나로 (질문용·차트 모두)
    - aggregate 는 시점마다 따로 합친다 (by 시점). 여러 해를 한데 더하지 않는다
    - item 에 지표가 아니라 범주 값(0세, 서울특별시, 남자)을 적으면 → 그 열의 조건으로 옮긴다
    - 질문의 연령 범위(0~5세) 안에서 일부 나이만 고르면(['0세']) → View 의 그 범위 나이 전체로 (fix_age)
    - 같은 하위 질문·같은 연산·같은 View·같은 항목의 질문용 계산이 여럿이면 → 하나로 합친다
      (2026-11-11 '최근 2년 미취학아동수': HCX 가 나이마다 raw 를 하나씩 6개 만들어 응답이 출력 한도에서 끊겼다)
    (2026-11-10 테스트 화면 첫 실행에서 나온 실수들. tests/chart_calculate/test_hcx_regression.py)

  검증 방침: HCX 가 없는 열·값을 골라도 계획에서 빼지 않는다. 그대로 실행하면 계산 단계가 None + 사유로 처리하고
            (차트는 validation 의 data_present 실패), 여기서는 같은 사유를 ChartPlan.notes 에 미리 적어 QA 가 보게 한다.
"""
import re
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from backend.agent.chart_calculate import region_scope
from backend.agent.chart_calculate.condition import find_axis, item_column_value, selected_values
from backend.agent.chart_calculate.indicator import correspondence, is_category_label, matches_any
from backend.agent.chart_calculate.calculate import SELECTED_LABEL, TIME_COL, _only_unit_added, step_key
from backend.agent.chart_calculate.validate import TOTAL_LABELS, totals_in
from backend.agent.chart_calculate.display import (STANDARD_UNITS, data_digits, make_display, ratio_unit, register, result_unit,
                                                   unit_of)
from backend.agent.chart_calculate.select import (age_span, AGE_HINTS, CATEGORY_HINTS, ITEM_COL, REGION_HINTS, VALUE_COL, find_item_column,
                                                   select_rows)
from backend.core.korean import strip_unit
from backend.schemas.chart import (ChartPlan, ChartRequest, Denominator, Display, Measure, Operand, Plan, PlanOutput,
                                   Role, Select, Step, Withheld)
from backend.schemas.query import Filters, QueryBundle
from backend.schemas.record import Record

CHART_ROLES = set(get_args(Role))
TWO_OPERAND = {"diff", "ratio"}        # 피연산자 둘(a, b)을 한 단계에서 쓰는 연산
MULTI_OPERAND = TWO_OPERAND | {"combine"}   # 피연산자 여럿을 한 단계에서 쓰는 연산. 나머지 연산은 피연산자 1개
PERIOD_OPS = {"change", "growth_rate", "cagr", "index"}   # from·to·base 시점이 행에 있어야 하는 연산
# 갈래가 여럿인 차트: 갈래마다 축 역할 하나 (specs.SPECS 의 필수 역할 중 열에 연결되는 것, 순서대로)
MULTI_BRANCH = {"combo": ("y", "y2"), "scatter": ("x", "y"), "bubble": ("x", "y", "size"), "dumbbell": ("start", "end")}
REGION = "지역"                        # 고정 조건의 지역 키 (View 의 지역 열 이름은 표마다 다르다)
GROWTH_OPS = {"change", "growth_rate"}
# [NEW 11-16] 결과가 원 자료 값의 단위·자릿수를 그대로 잇는 연산 (growth_rate · cagr · share · index · ratio 는 계산 값이라 단위 기본 자릿수)
SOURCE_DIGITS_OPS = {"raw", "change", "diff", "aggregate", "extreme", "rank", "combine"}
AGE = "연령"                           # 고정 조건에 함께 싣는 참고 값 (합계 판단용, 고정하지는 않는다)
INTENT = "의도"
TARGET = "대상"                          # 고정 조건에 싣는 참고 값 (질문의 대상. 항목이 지표 대신 대상 이름일 수 있다: 1인가구)
INDICATOR = "지표"                       # 고정 조건에 싣는 참고 값 (질문의 지표. 계산에 쓴 항목이 이것과 대응하는지 확인한다)
SEX = "성별"                             # [NEW 11-25] 고정 조건에 싣는 참고 값 (행을 거르지 않는다). 지표 대응에서 '남자인구수' 를 인구수로 인정할 때만 쓴다
ORIGINAL = "원문"                        # [NEW 11-25] 고정 조건에 싣는 참고 값: 사용자의 원 질문 문장. 질문에 그대로 나온 항목 이름을 별칭으로 인정할 때만 쓴다
_SHARE_TAIL = re.compile(r"\s*(?:구성비|비율|비중)$")   # [NEW 11-25] share 의 지표 '보증부월세비율' → 분자 항목 '보증부월세'
_SUMMARY_EXACT = {"사례수", "표준편차", "중앙값", "성비"}  # [NEW 11-25 1-8] 조사표의 요약 값 행 (응답 분포의 조각이 아님)
_SUMMARY_FALSE = ("구성비",)                              # 질문에 있어도 요약 값을 물은 것이 아닌 말 ('구성비' 안의 '성비')


def _summary_word(value) -> str | None:
    """[NEW 11-25 1-8] 값이 요약 값 행이면 그 말 ('사례수' · '평균' …), 아니면 None. 띄어쓰기 · 단위 괄호 무시.
    '평균' 은 들어 있기만 하면 (평균 · 평균 가구원수 · 평균 매출액 · 가구당 평균인원수)"""
    bare = re.sub(r"\s+", "", strip_unit(str(value)))
    if bare in _SUMMARY_EXACT:
        return bare
    return "평균" if "평균" in bare else None
# [NEW 11-25] 성별 값 → 항목 이름에 붙는 수식어 (남자인구수 · 남인구 · 남성 인구)
SEX_MODIFIERS = {"남자": ("남자", "남", "남성"), "남": ("남자", "남", "남성"), "남성": ("남자", "남", "남성"),
                 "여자": ("여자", "여", "여성"), "여": ("여자", "여", "여성"), "여성": ("여자", "여", "여성")}
YEARLY = "매년"                         # 고정 조건에 싣는 참고 값 (해마다의 변화를 묻는 질문인지)
_YEARLY = re.compile(r"매년|해마다|매해|전년\s*대비|연도별\s*(?:증감|증가|감소|변화)")
COND_EXPR = "조건식"                     # [NEW 11-20] 고정 조건에 싣는 조건 목록 ([{field, op, value, unit, text, source}]). 값이 문자열 목록이 아니라 dict 목록이다
SURFACE = "원문표현"                     # [NEW 11-20] 항목 후보를 찾는 별칭 (질문 원문에 있던 CSV 표현)
WHOLE_TOTAL_LABELS = {"계", "합계", "총계", "전체"}   # [NEW 11-20] 분모로 쓸 수 있는 전체 행. '소계' 는 부분 범주의 합일 수 있어 뺀다 (validate.TOTAL_LABELS 는 그대로)
AXIS = "비교축"                         # 고정 조건에 싣는 참고 값 (범주 비교 질문인지)
_TIME_AXES = {"연도", "연도별", "시점", "년도", "해", "기간", "연간"}   # 비교축이 시간인 질문 (가장 많은 해)
TOTAL_FREE_OPS = {"rank", "extreme"}      # 범주 비교 질문이면 조건에서 총계(전국 · 계)를 빼는 연산
# [MOVED 11-11] AGE_HINTS · CATEGORY_HINTS → select.py
PER_CATEGORY_INTENTS = {"비교", "순위"}  # 범주끼리 견주는 질문은 합치지 않는다
# 질문의 지역이 '진짜 지역 이름'인지: 재작성 모듈이 지역 칸에 지역이 아닌 말('지역 혼인건수')을 넣는 경우가 있어, 그런 값 때문에 계산을 보류하지 않는다
# [CHANGED 11-16] 이전: 이름이 특별시·광역시·…·도 로 끝나는지만 봤다 → 시도 · 수도 · 연도 같은 말도 지역으로 판정해 계산 전체가 보류됐다 (검수 M3-11)
SIDO = {"서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시",
        "경기도", "강원도", "강원특별자치도", "충청북도", "충청남도", "전라북도", "전북특별자치도", "전라남도", "경상북도", "경상남도",
        "제주도", "제주특별자치도"}


class _RealRegion:
    """_REAL_REGION.search(이름) 과 같은 모양을 유지한다 (시도 이름과 정확히 같을 때만 참)"""

    @staticmethod
    def search(name: str):
        return name.strip() in SIDO or None


_REAL_REGION = _RealRegion()


_PERIOD_SUBSTITUTED = {"missing", "default", "latest_shift"}     # View 가 요청 시점을 다른 시점으로 바꿨음을 뜻하는 메모 유형


def _substituted_years(rec: Record) -> set[str]:
    """[NEW 11-17] View 가 '요청했지만 없어서 바꿨다' 고 기록한 시점들 (Record.notes · match.unmet 의 시점 메모 requested)"""
    out: set[str] = set()
    for n in [*rec.notes, *(rec.match.unmet if rec.match else [])]:
        if n.slot == "시점" and n.type in _PERIOD_SUBSTITUTED:
            req = n.requested if isinstance(n.requested, (list, tuple)) else [n.requested]
            out |= {str(y) for y in req if y is not None}
    return out


TITLE_MAX = 40
_NUMBER = re.compile(r"\d[\d,.]*")
_OK_NUMBER = re.compile(r"(19|20)\d{2}|\d{1,3}")     # 연도, 나이·기간 같은 작은 정수만


# [NEW 11-17] 제목에 쓰인 연산 이름 → 그 이름이 맞는 차트 계산. 긴 말부터 본다 ('연평균' 을 먼저 지워야 '평균' 이 잘못 걸리지 않는다)
_MEASURE_WORDS: list[tuple[str, set[str]]] = [
    ("연평균", {"cagr"}), ("증감률", {"growth_rate", "cagr"}), ("증가율", {"growth_rate", "cagr"}), ("감소율", {"growth_rate", "cagr"}),
    ("변화율", {"growth_rate", "cagr"}), ("증감", {"change", "growth_rate", "cagr"}), ("구성비", {"share"}), ("비중", {"share"}),
    ("순위", {"rank"}), ("지수", {"index"}), ("평균", {"aggregate"}), ("합계", {"aggregate", "combine"}), ("차이", {"diff"})]


# 연산 이름(합계 · 평균 · 지수 · 순위)을 품고 있는 실제 지표 이름. 긴 이름부터 지운다
_INDICATOR_NAMES = ("합계출산율", "평균초혼연령", "평균출산연령", "평균기대수명", "평균가구원수", "평균수명", "평균연령", "노령화지수", "고령화지수",
                    "노년부양비", "출산순위", "출생순위", "소비자물가지수", "생산자물가지수")

_QUESTION_TITLE = re.compile(r"[?？]\s*$|(?:는지|나요|인가요?|일까요?|입니까|습니까|알려\s*줘|알려\s*주세요|어때요?)\s*[?？.]?\s*$")


def clean_title(title: str | None, measure: str | None = None) -> tuple[str | None, str | None]:
    """HCX 제목 검사 → (쓸 제목, 버린 사유). 계산 값(1,551,484 / 24.8)이 제목에 들어가지 않게 숫자를 본다.
    [CHANGED 11-17] measure 를 주면 제목의 연산 이름이 차트 계산과 맞는지도 본다: 원값(raw) 차트에 '매년 증감률 추이' 라는
    제목이 붙었다 (보고서 11.3 H4, 실제 HCX)"""
    t = " ".join((title or "").split())
    if not t:
        return None, None
    if len(t) > TITLE_MAX:
        return None, f"제목이 {TITLE_MAX}자를 넘음"
    if bad := [n for n in _NUMBER.findall(t) if not _OK_NUMBER.fullmatch(n)]:
        return None, f"제목에 연도·나이가 아닌 숫자 {bad}"
    if _QUESTION_TITLE.search(t):     # [NEW 11-17] '2023년 인구가 가장 많은 시도는?' 처럼 질문 문장을 제목으로 썼다 (실제 HCX, 보고서 12.3)
        return None, "제목이 질문 문장"
    rest = t
    for name in _INDICATOR_NAMES:      # [NEW 11-18] 지표 이름 안의 말은 연산 이름이 아니다 ('합계출산율' 의 '합계', '평균연령' 의 '평균'. Q23, F9)
        rest = rest.replace(name, " ")
    for word, ops in _MEASURE_WORDS if measure else []:
        if word in rest:
            if measure not in ops:
                return None, f"제목의 '{word}' 이 차트 계산({measure})과 다름"
            rest = rest.replace(word, " ")
    return t, None


def sub_question_ids(bundle: QueryBundle) -> list[tuple[str, str]]:
    """[(하위 질문 ID, 문장)]. 하위 질문이 없으면 원 질문 하나

    TODO(임시): 하위 질문 ID 형식은 확정 전이다 (명세 9장 'Record.id 형식'). 지금은 '{query_id}-{순번}'.
    """
    qid = bundle.query_id or "q"
    return [(f"{qid}-{i}", s) for i, s in enumerate(bundle.sub_questions or [bundle.original], 1)]


def _fixed_of(f: Filters | None) -> dict[str, list[str]]:
    """필터에서 코드로 고정할 것: 시점·지역. 대상은 View 의 열 값이 아니라 프롬프트로만 고정한다"""
    out: dict[str, list[str]] = {}
    if f and f.시점:
        out[TIME_COL] = sorted(str(y) for y in f.시점)
    if f and f.지역:     # 지역이 없으면(= 전국 또는 '시도별' 같은 비교) 고정하지 않는다
        out[REGION] = list(f.지역)
    if f and f.연령 and (f.연령.from_ is not None or f.연령.to is not None):
        out[AGE] = [str(f.연령.from_ or 0), "" if f.연령.to is None else str(f.연령.to)]
    if f and f.원문표현:
        out[SURFACE] = [str(x) for x in f.원문표현]
    if f and f.조건식:
        out[COND_EXPR] = [c.model_dump() for c in f.조건식]
    if f and f.지표:
        out[INDICATOR] = [str(x) for x in f.지표]
    if f and f.대상:
        out[TARGET] = [str(x) for x in f.대상]
    if f and f.성별:
        out[SEX] = [str(x) for x in f.성별]
    if f and f.의도:
        out[INTENT] = [f.의도]
    if f and f.비교축:     # [NEW 11-17] 범주 비교 질문 ('시도별', '높은 지역'). 순위 · 극값에서 총계를 뺄지 정한다
        out[AXIS] = [f.비교축]
    return out


def fixed_conditions(bundle: QueryBundle | None) -> dict[str, dict[str, list[str]]]:
    """하위 질문 ID → 고정 조건. 하위 질문마다 sub_filters 가 있으면 그것, 없으면 상위 filters"""
    if bundle is None:
        return {}
    main, subs = _fixed_of(bundle.filters), bundle.sub_filters or []
    pairs = sub_question_ids(bundle)
    out = {sid: dict(_fixed_of(subs[i]) if i < len(subs) and subs[i] is not None else main) for i, (sid, _) in enumerate(pairs)}
    # [NEW 11-20] 조건식 은 하위 필터가 있어도 상위 조건과 합친다. 하위 필터가 우선이면 상위에만 있는 조건(숫자 기준)이 본 질문에서 사라진다.
    #   역할 단위(분모·조건)는 질문이 아니라 제외한다
    if main.get(COND_EXPR):
        for i, (sid, _) in enumerate(pairs):
            sf = subs[i] if i < len(subs) else None
            if sf is not None and sf.역할:
                continue
            have = out[sid].get(COND_EXPR) or []
            out[sid][COND_EXPR] = [*have, *[c for c in main[COND_EXPR] if c not in have]]
    # [NEW 11-17] '매년 · 해마다 · 전년 대비' 를 묻는 질문 (보고서 11.3 H3). 하위 질문 문장에서 찾고, 하위 질문이 하나면 원 질문에서도 찾는다
    #   (재작성기가 '매년' 을 '연도별 증감률' 로 바꿔 적는다)
    whole = " ".join([bundle.original, bundle.rewritten or ""]) if len(pairs) == 1 else ""
    for sid, text in pairs:
        if _YEARLY.search(text) or _YEARLY.search(whole):
            out[sid][YEARLY] = ["1"]
        if bundle.original:                  # [NEW 11-25] 원 질문 문장 (A-1: 질문에 그대로 나온 항목 이름을 별칭으로)
            out[sid][ORIGINAL] = [bundle.original]
    return out


# ── HCX 가 정하는 것 ─────────────────────────────────────────────
class Pick(BaseModel):
    """View 에서 값을 가져올 곳 하나"""
    model_config = ConfigDict(coerce_numbers_to_str=True)
    role: str | None = Field(None, description="차트 갈래면 축 역할(y, y2, x, size, start, end), "
                                               "계산 피연산자면 a·b·value·part. 비우면 순서로 정한다")
    record_id: str
    item: str | None = None
    select: Select = Field(default_factory=dict)
    sign: Literal["+", "-"] | None = Field(None, description="combine 전용: + 더하기, - 빼기 (생략하면 +)")
    unit: str | None = Field(None, description="HCX 가 고른 단위. item 괄호 단위가 없을 때만 쓰고, View metadata.unit 안에 있어야 한다")
    note: str | None = Field(None, description="[NEW 11-18] 코드가 항목을 바꾼 사유. Operand.note 로 이어져 답변의 주의사항이 된다 (HCX 응답에는 없다)")


class _Args(BaseModel):
    """연산 인자 (Step 과 같은 이름). LLM 이 연도를 숫자로 줘도 문자열로 받는다"""
    model_config = ConfigDict(populate_by_name=True, coerce_numbers_to_str=True)
    join_on: list[str] | None = None
    denominator: Denominator | None = None
    from_: str | None = Field(None, alias="from")
    to: str | None = None
    base: str | None = None
    agg: str | None = None
    top_n: int | None = None
    kind: str | None = None          # [NEW 11-16] extreme: max | min
    order: str | None = None         # [NEW 11-16] rank: desc | asc

    def step_args(self) -> dict:
        return {k: v for k, v in self.model_dump(include=set(_Args.model_fields)).items() if v is not None} \
            | ({"denominator": self.denominator} if self.denominator else {})


class ChartDecision(_Args):
    chart_id: str
    title: str | None = Field(None, description="질문의 말로 쓴 차트 제목 (검사를 통과하면 Plan.title)")
    record_id: str | None = Field(None, description="기본 View. operands 가 있으면 비워도 된다 (첫 피연산자의 View)")
    select: Select = Field(default_factory=dict)
    operands: list[Pick] = Field(default_factory=list, description="갈래가 여럿(combo·scatter·bubble)이거나 "
                                                                   "View 가 여럿(diff·ratio)일 때만 적는다")


class AnswerDecision(_Args):
    sub_question_id: str | None = None
    op: Measure
    operands: list[Pick] = Field(default_factory=list)


class Decision(BaseModel):
    charts: list[ChartDecision] = Field(default_factory=list)
    answers: list[AnswerDecision] = Field(default_factory=list)


# ── 규칙 ─────────────────────────────────────────────────────────
class _Planner:
    def __init__(self, records: list[Record], fixed: dict[str, dict[str, list[str]]] | None = None):
        self.records = {r.id: r for r in records}
        self.fixed = fixed or {}
        self.displays: dict[str, Display] = {}
        self.notes: list[str] = []
        self.warnings: list[str] = []          # [NEW 11-13] 사용자에게 알릴 사유 (ChartPlan.warnings)
        self.withheld: set[str] = set()        # [NEW 11-13] 조건이 맞지 않아 계산을 보류한 계획 (tag)
        self.withheld_list: list[Withheld] = []   # [NEW 11-20] 보류 범위 (ChartPlan.withheld)
        self.scope: dict[str, tuple[str | None, str | None, str | None]] = {}   # tag → (하위 질문 ID, chart_id, 연산)
        self.alias_ok: set[tuple[str, str]] = set()   # (record_id, 항목) — 지표 대응 검사를 별칭(원문표현·조건 값)으로 통과한 항목
        self.answer_sub: dict[str, str] = {}      # 질문용 step_id → 하위 질문 ID (같은 세트의 차트 단계를 찾을 때 쓴다)

    def note(self, tag: str, text: str):
        self.notes.append(f"{tag}: {text}")

    def withhold(self, tag: str, note: str, warning: str):
        """계산을 보류한다. 개발자용 note 와 사용자용 warning 을 함께 남긴다"""
        self.withheld.add(tag)
        self.note(tag, f"{note} → 계산하지 않음")
        self.warnings.append(warning)
        sub, chart, op = self.scope.get(tag, (None, None, None))
        self.withheld_list.append(Withheld(sub_question_id=sub, chart_id=chart, op=op, text=warning))

    def same_view_total(self, tag: str, picks: list[Pick], d: "_Args", expected: list[str], fixed: dict | None = None) -> "_Args | None":
        """[NEW 11-20] 비중의 분모 View 가 세트 밖이면, 분자와 **같은 View 의 전체 행**(계 · 합계 · 총계 · 전체)을 분모로 쓸 수 있는지 (KOS-26 A-4).
        분자 실제 행마다, 공유 축(부분 값이 든 열)과 값 열을 뺀 **나머지 모든 열**의 값이 같은 전체 행이 정확히 하나 있고 원 단위가 같을 때만.
        select 에 적힌 열만 비교하면 View 에 섞인 성별 · 지역 · 분류가 다른 행(남자 부분 ÷ 여자 계)을 분모로 잡는다. '소계' 는 쓰지 않는다.
        **분모로 넓힐 수 있는 축은 부분 값이 든 열뿐이다** — 부분의 항목이 있는 열, 그리고 부분을 정한 조건식(점유형태=보증부월세)의 열.
        성별 · 지역 같은 다른 열의 '계' 로 넓히면 질문의 모집단 조건이 바뀐다 (남자 가구주 중 비율인데 성별 계의 부분 값이 분모가 된다).
        올바른 분모가 없으면 None (기존대로 denominator_outside 가 보류한다)"""
        den = d.denominator
        if not expected or den is None or den.scope != "question" or den.operand is None or den.operand.record_id in expected or not picks:
            return None
        part = picks[0]
        rec = self.records.get(part.record_id)
        if rec is None or part.record_id not in expected:
            return None
        sel = select_rows(rec, part.select, part.item)
        if not sel.rows:
            return None
        cols = [c for c in rec.table.columns if c != VALUE_COL]
        ordered = self._part_axes(rec, part, fixed or {})
        for axis in ordered:
            ai = rec.table.columns.index(axis)
            part_vals = {str(r[sel.col(axis)]) for r in sel.rows}
            labels = {str(r[ai]) for r in rec.table.rows} & WHOLE_TOTAL_LABELS
            if len(part_vals) != 1 or len(labels) != 1 or part_vals & labels:
                continue
            total = next(iter(labels))
            others = [c for c in cols if c != axis]
            totals = {}
            for r in rec.table.rows:
                if str(r[ai]) == total:
                    totals.setdefault(tuple(str(r[rec.table.columns.index(c)]) for c in others), []).append(r)
            matched, ok = [], True
            for r in sel.rows:
                key = tuple(str(r[sel.col(c)]) for c in others)
                hit = totals.get(key) or []
                if len(hit) != 1:
                    ok = False
                    break
                matched.append(hit[0])
            if not ok:
                continue
            coords = {c: list(dict.fromkeys(str(r[rec.table.columns.index(c)]) for r in matched)) for c in others}
            item_total = total if axis == ITEM_COL else None
            den_select = {c: v for c, v in coords.items() if c != ITEM_COL}
            if axis != ITEM_COL:
                den_select[axis] = [total]
            item = item_total if axis == ITEM_COL else (coords.get(ITEM_COL) or [None])[0]
            if item is None and ITEM_COL in coords and len(coords[ITEM_COL]) != 1:
                continue
            u_part, u_total = self.unit(part.record_id, part.item, part.select), self.unit(part.record_id, item, den_select)
            if u_part != u_total:
                continue
            self.note(tag, f"분모 View {den.operand.record_id} 가 세트 밖 → 같은 View 의 '{total}' 행을 분모로 씀 (열 '{axis}', 나머지 좌표 일치)")
            operand = Operand(record_id=part.record_id, item=item, select=den_select, unit=u_total,
                              note=f"같은 표의 '{total}' 행을 분모로 씀")
            return d.model_copy(update={"denominator": den.model_copy(update={"operand": operand})})
        return None

    def sum_denominator(self, tag: str, d: "_Args") -> "_Args":
        """[NEW 11-25 D-2] 비중의 분모가 'A + B' 이면 → 분모가 같은 표의 항목 A · B 를 모두 고르게 한다 (calculate._share 가 더한다).
        HCX 가 분모 항목을 '남자인구수+여자인구수' 로 적거나(→ '항목 없음'), 분모 설명(basis)은 '남자 인구수 + 여자 인구수' 인데
        항목은 분자와 같은 '남자인구수' 로 적었다(→ 남자 ÷ 남자 = 100%). 15유형 원그래프 2건.
        '+' 로 나눈 이름이 2개 이상이고 모두 그 표의 항목 열에 있을 때만 바꾼다 (띄어쓰기 · 단위 괄호 무시). 하나라도 없으면 그대로"""
        den = d.denominator
        if den is None or den.scope != "question" or den.operand is None:
            return d
        op = den.operand
        src = op.item if op.item and "+" in op.item else (den.basis if den.basis and "+" in den.basis else None)
        rec = self.records.get(op.record_id)
        if not src or rec is None or ITEM_COL not in rec.table.columns:
            return d
        col = rec.table.columns.index(ITEM_COL)
        by_name = {re.sub(r"\s+", "", strip_unit(str(r[col]))): str(r[col]) for r in rec.table.rows}
        names = [n for n in re.split(r"\s*\+\s*", src) if n.strip()]
        hits = [by_name.get(re.sub(r"\s+", "", strip_unit(n))) for n in names]
        if len(names) < 2 or None in hits or len(set(hits)) < 2:
            return d
        items = list(dict.fromkeys(hits))
        self.note(tag, f"비중의 분모 '{src}' → 같은 표의 항목 {items} 의 합")
        operand = op.model_copy(update={"item": None, "select": {**op.select, ITEM_COL: items}})
        return d.model_copy(update={"denominator": den.model_copy(update={"operand": operand})})

    def _part_axes(self, rec: Record, part: Pick, fixed: dict) -> list[str]:
        """부분(분자)의 값이 들어 있는 열: 항목이 있는 열 + 조건식의 '=' 조건이 적용되는 열. 순서대로, 중복 없이"""
        axes: list[str] = []
        item = part.item or (str(v[0]) if len(v := part.select.get(ITEM_COL) or []) == 1 else None)
        if item and (hit := find_item_column(list(rec.table.columns), rec.table.rows, item)):
            axes.append(hit[0])
        alias = {i for rid, i in self.alias_ok if rid == rec.id}
        for c in fixed.get(COND_EXPR) or []:
            if c.get("op") == "=" and (col := find_axis(rec, c, alias).column) and col not in axes:
                axes.append(col)
        return [a for a in axes if a not in (TIME_COL, VALUE_COL)]

    def denominator_outside(self, tag: str, d: "_Args", expected: list[str]) -> bool:
        """비중의 분모를 세트(view_ids) 밖 View 에서 가져오면 다른 범위의 총계로 나누게 된다 (40% 가 20% 로 바뀐다) → 보류"""
        den = d.denominator
        if not expected or den is None or den.scope != "question" or den.operand is None:
            return False
        if den.operand.record_id in expected:
            return False
        self.withhold(tag, f"분모 View {den.operand.record_id} 가 세트(view_ids) {expected} 밖",
                      "비중의 분모로 쓸 자료가 이 질문에 정해진 자료가 아니라서 비중을 계산하지 못했습니다.")
        return True

    def check(self, tag: str, record_id: str, select: Select, item: str | None):
        """고른 열·값이 View 에 실제로 있는지. 없으면 notes 에만 적는다 (파일 설명의 '검증 방침')"""
        rec = self.records.get(record_id)
        if rec is None:
            self.note(tag, f"View 없음: {record_id}")
            return
        for err in select_rows(rec, select, item).errors:
            self.note(tag, err)

    def check_set(self, tag: str, expected: list[str], used: list[str | None]):
        """[NEW] HCX 가 세트(모듈 2 의 view_ids) 밖의 View 를 골랐는지. 계획은 그대로 두고 notes 에만 적는다.
        expected 가 비어 있으면(view_ids 를 안 받은 옛 입력) 아무것도 하지 않는다"""
        if not expected:
            return
        stray = list(dict.fromkeys(r for r in used if r and r not in expected))
        if stray:
            self.note(tag, f"HCX 가 모듈 2 의 View(view_ids)가 아닌 {stray} 를 골랐다 (세트: {expected})")

    def unit(self, record_id: str, item: str | None, select: Select) -> str | None:
        rec = self.records.get(record_id)
        if item is None and len(items := select.get(ITEM_COL) or []) == 1:
            item = str(items[0])
        return unit_of(item, rec.metadata.get("unit") if rec else None)

    def source_digits(self, op: str, picks: list[tuple[str, str | None, Select]], unit: str | None,
                      agg: str | None = None) -> int | None:
        """결과가 원 자료 값을 잇는 연산이면 그 행들의 소수 자릿수 (최대 3). 합계출산율 0.721 이 '1명' 이 되지 않게 (검수 M3-03)"""
        if op not in SOURCE_DIGITS_OPS:
            return None
        values = []
        for record_id, item, select in picks:
            rec = self.records.get(record_id)
            if rec is not None:
                sel = select_rows(rec, select, item)
                if VALUE_COL in sel.columns:         # [CHANGED 11-16] 이전: r[-1] — 값 열이 마지막이 아니면 항목 이름을 읽었다 (검수 3)
                    values += [r[sel.col(VALUE_COL)] for r in sel.rows]
        return data_digits(values, unit, integer_rule=not (op == "aggregate" and agg == "mean"))

    def ref(self, op: str, units: list[str | None], digits: int | None = None) -> str:
        """결과 단위로 표시 설정을 등록 → display_ref. 같은 단위의 결과는 같은 키를 쓴다

        TODO(후속): 표시 단위 환산(192,507건 → 19.3만 건)은 아직 누가 정할지 없다. 지금은 원 단위 그대로(unit_scale 1).
        """
        if op == "ratio" and len(units) == 2:
            unit = ratio_unit(units[0], units[1])           # calculate._pair 와 같은 규칙
        else:
            unit = result_unit(op, units[0] if units else None)
        return register(self.displays, make_display(unit, auto_digits=digits))

    # ── 바로잡기 ─────────────────────────────────────────────────
    def drop_non_operands(self, tag: str, picks: list[Pick]) -> list[Pick]:
        """HCX 가 join_on 같은 연산 인자를 피연산자로 적은 것 (role "join_on", item 이 View 의 열 이름)"""
        keep = []
        for p in picks:
            rec = self.records.get(p.record_id)
            if p.role == "join_on" or (rec is not None and p.item in rec.table.columns):
                self.note(tag, f"피연산자가 아님 → 버림 (role={p.role}, item={p.item})")
            else:
                keep.append(p)
        return keep

    def category_item_to_condition(self, tag: str, picks: list[Pick], quiet: bool = False) -> list[Pick]:
        """item 에 범주 값을 적은 것 → 그 열의 조건으로. item 이 '항목' 열에 있으면 그대로 (진짜 지표)"""
        out, moved = [], {}
        for p in picks:
            rec = self.records.get(p.record_id)
            if rec is None or p.item is None:
                out.append(p)
                continue
            cols, rows = rec.table.columns, rec.table.rows
            in_col = lambda c: c in cols and any(str(r[cols.index(c)]) == p.item for r in rows)  # noqa: E731
            if in_col(ITEM_COL):
                out.append(p)
                continue
            col = next((c for c in cols if any(h in c for h in CATEGORY_HINTS) and in_col(c)), None)
            if col is None:
                out.append(p)
                continue
            have = [str(v) for v in p.select.get(col, [])]
            moved.setdefault(col, []).append(p.item)
            out.append(p.model_copy(update={"item": None, "select": {**p.select, col: list(dict.fromkeys(have + [p.item]))}}))
        if not quiet:
            for col, items in moved.items():
                self.note(tag, f"item {items} 은 지표가 아니라 {col} 값 → 조건으로 옮김")
        return out

    def merge_answers(self, answers: list["AnswerDecision"]) -> list["AnswerDecision"]:
        """같은 하위 질문·연산·View·항목의 질문용 계산(피연산자 1개짜리)을 하나로. 피연산자를 모아 두면 normalize 가 조건을 합친다"""
        out: list[AnswerDecision] = []
        where: dict[tuple, int] = {}
        count: dict[tuple, int] = {}
        for a in answers:
            picks = self.category_item_to_condition("", a.operands, quiet=True)
            if a.op in MULTI_OPERAND or len(picks) != 1:
                out.append(a)
                continue
            key = (a.sub_question_id, a.op, picks[0].record_id, picks[0].item)
            if key in where:
                prev = out[where[key]]
                out[where[key]] = prev.model_copy(update={"operands": prev.operands + a.operands})
                count[key] += 1
            else:
                where[key], count[key] = len(out), 1
                out.append(a)
        for (sid, op, _, _), n in count.items():
            if n > 1:
                self.note(sid or "answers", f"같은 {op} 계산 {n}개를 하나로 합침 (범주마다 따로 적은 것)")
        return out

    def merge_same_item(self, tag: str, op: str, picks: list[Pick], keep_first: bool) -> list[Pick]:
        """피연산자 1개짜리 연산에 같은 View·항목을 여럿으로 쪼갠 것 → 조건을 합쳐 하나로 (예: a=2024, b=2021)

        항목이 다르면 keep_first=True(질문용)는 항목마다 하나씩 돌려준다 — 부른 쪽(answer)이 항목마다 단계를 만든다.
        차트는 항목이 다르면 갈래로 두므로 그대로 둔다.
        [CHANGED] 이전: 항목이 다르면 질문용은 첫 번째만 쓰고 나머지를 버렸다 (답변에서 그 항목의 수치가 사라졌다).
                  keep_first 라는 이름은 그 흔적이다 (호출부 시그니처를 바꾸지 않으려고 남겼다)
        """
        if len(picks) <= 1:
            return picks
        if not keep_first and any((p.record_id, p.item) != (picks[0].record_id, picks[0].item) for p in picks):
            return picks
        groups: dict[tuple, list[Pick]] = {}
        for p in picks:
            groups.setdefault((p.record_id, p.item), []).append(p)
        out = [self._merge_group(tag, op, g) for g in groups.values()]
        if len(out) > 1:
            self.note(tag, f"{op} 는 피연산자 1개 → 항목마다 따로 계산 ({[p.item for p in out]})")
        return out

    def _merge_group(self, tag: str, op: str, group: list[Pick]) -> Pick:
        """같은 View·항목의 피연산자들의 조건을 합친다"""
        if len(group) == 1:
            return group[0]
        merged: Select = {}
        for p in group:
            for col, vals in p.select.items():
                have = merged.setdefault(col, [])
                have += [v for v in vals if str(v) not in map(str, have)]
        # 어느 한 피연산자에 없는 열 조건 = 그 피연산자는 그 열을 전부 썼다 → 합친 조건에서도 뺀다
        merged = {c: v for c, v in merged.items() if all(c in p.select for p in group)}
        self.note(tag, f"{op} 는 피연산자 1개 → 같은 항목의 피연산자를 하나로 합침 ({len(group)}개, 조건 {merged})")
        return group[0].model_copy(update={"select": merged, "role": None})

    def fill_period(self, tag: str, op: str, select: Select, d: _Args) -> Select:
        """기간 연산인데 시점 조건에 from·to·base 시점이 빠졌으면 보탠다

        시점 조건을 지우지 않는 이유: base="prev" 나 index 처럼 구간 전체가 필요한 연산이 있다.
        """
        if op not in PERIOD_OPS or TIME_COL not in select:
            return select
        have = [str(v) for v in select[TIME_COL]]
        add = [t for t in dict.fromkeys((d.from_, d.to, d.base)) if t and t != "prev" and t not in have]
        if not add:
            return select
        self.note(tag, f"{op} 의 시점 조건에 계산 시점을 보탬 ({have} → {have + add})")
        return {**select, TIME_COL: have + add}

    def fix_branch_roles(self, tag: str, chart_type: str, picks: list[Pick]) -> list[Pick]:
        """갈래가 여럿인 차트에서 그 차트에 없는 역할(예: "combo") → 아직 안 쓴 역할을 순서대로"""
        roles = MULTI_BRANCH.get(chart_type)
        if not roles or len(picks) < 2:
            return picks
        free = [r for r in roles if r not in {p.role for p in picks}]
        out = []
        for p in picks:
            if p.role not in roles and free:
                new = free.pop(0)
                self.note(tag, f"{chart_type} 갈래 역할 {p.role} → {new} ({p.item})")
                p = p.model_copy(update={"role": new})
            out.append(p)
        return out

    def fixed_for(self, tag: str, sub_ids: list[str | None]) -> dict[str, list[str]]:
        """하위 질문의 고정 조건. ID 를 못 찾았을 때는 하위 질문이 하나뿐일 때만 그 조건을 쓴다.
        [CHANGED 11-16] 이전: 못 찾으면 첫 번째 하위 질문의 조건을 썼다 → 2025년 질문에 2021년이 고정됐다 (검수 M3-05)"""
        hit = next((self.fixed[s] for s in sub_ids if s in self.fixed), None)
        if hit is not None:
            return hit
        if len(self.fixed) == 1:
            return next(iter(self.fixed.values()))
        if self.fixed:
            self.note(tag, f"하위 질문 ID {[s for s in sub_ids if s]} 를 찾지 못해 고정 조건을 적용하지 않음 (하위 질문 {list(self.fixed)})")
        return {}

    def two_points(self, tag: str, op: str, select: Select, d: _Args, years: list[str] | None) -> tuple[Select, _Args] | None:
        """[NEW 11-16] 질문용 증감·증감률: 처음 → 끝 두 시점으로 값 하나 ('최근 5년 얼마나 변했어' = 2021 → 2025 24.8%).
        HCX 가 from·to 를 주면 그것, 안 주고 고정 시점이 둘 이상이면 고정 시점의 처음과 끝. 해마다 보려면 HCX 가 base 'prev' 를 적는다.
        그 밖(시점 정보 없음)이면 None → 기존 규칙. 고정 시점 밖의 시점은 고정 시점의 처음·끝으로 바꾼다 (검수 M3-02, 결정 D-1)"""
        start, end = d.from_, d.to
        if years and len(years) >= 2:
            if not (start and end):
                start, end = years[0], years[-1]
            elif start not in years or end not in years:
                self.note(tag, f"{op}: 기간 {start}~{end} 이 고정 시점 {years[0]}~{years[-1]} 밖 → 고정 시점의 처음과 끝")
                start, end = years[0], years[-1]
        if not (start and end):
            return None
        new = {**select, TIME_COL: years} if years else select
        self.note(tag, f"{op}: 처음 → 끝 두 시점으로 계산 ({start} → {end})")
        return new, d.model_copy(update={"base": None, "from_": start, "to": end})

    def fix_time(self, tag: str, op: str, select: Select, d: _Args, years: list[str] | None,
                 answer: bool = False, yearly: bool = False) -> tuple[Select, _Args]:
        """고정 시점 적용. 기간 연산은 기간 전체를 쓰고 계산 방식을 정하고, 그 밖의 연산은 고정 시점 밖의 값만 바꾼다

        증감·증감률(change·growth_rate): 차트용은 시점마다 직전 시점 대비(추이). 질문용(answer)은 두 시점으로 값 하나, HCX 가 base 'prev' 를 적으면 직전 시점 대비"""
        if op in GROWTH_OPS and answer and yearly and d.base != "prev":
            # [NEW 11-17] '매년 증감률' 에 HCX 가 두 시점(from · to)을 골랐다 (실제 HCX, H3) → 아래 직전 시점 대비 규칙으로
            self.note(tag, f"{op}: 질문이 매년 · 전년 대비를 물어 직전 시점 대비로 계산")
        elif op in GROWTH_OPS and answer and d.base != "prev" and (two := self.two_points(tag, op, select, d, years)):
            return two
        if op in GROWTH_OPS:     # 증감·증감률: 시점마다 직전 시점 대비. HCX 가 두 시점(from·to)만 골랐어도 시점 전체로
            new = {**select, TIME_COL: years} if years else {k: v for k, v in select.items() if k != TIME_COL}
            upd = {"base": "prev", "from_": None, "to": None}
            if new != select or any(getattr(d, k) != v for k, v in upd.items()):
                where = f"고정 시점 {years[0]}~{years[-1]}" if years else "View 의 모든 시점"
                self.note(tag, f"{op}: 시점마다 직전 시점 대비로 계산 ({where})")
            return new, d.model_copy(update=upd)
        if not years:
            return select, d
        have = [str(v) for v in select.get(TIME_COL, [])]
        if op == "cagr" and len(years) >= 2:
            how, upd = f"{years[0]} → {years[-1]}", {"base": None, "from_": years[0], "to": years[-1]}
        elif op == "index" and len(years) >= 2:
            base = d.base if d.base in years else years[0]
            how, upd = f"기준 시점 {base}", {"base": base, "from_": None, "to": None}
        else:
            if have and not set(have) <= set(years):
                self.note(tag, f"시점 {have} 은 고정 시점 {years} 밖 → {years}")
                return {**select, TIME_COL: years}, d
            return select, d
        new = {**select, TIME_COL: years}
        if new != select or any(getattr(d, k) != v for k, v in upd.items()):
            self.note(tag, f"{op}: 고정 시점으로 계산 — {how}")
        return new, d.model_copy(update=upd)

    def add_fixed_time(self, tag: str, select: Select, years: list[str] | None, record_id: str | None) -> Select:
        """[NEW 11-16] 질문에 시점이 고정돼 있는데 HCX 가 시점 조건을 빼면 View 의 모든 시점이 계산에 든다
        ('2025년 혼인건수' 가 2021~2025 다섯 값으로 나왔다). View 에 시점 열이 있으면 고정 시점을 조건으로 넣는다 (검수 M3-10)"""
        rec = self.records.get(record_id or "")
        if not years or TIME_COL in select or rec is None or TIME_COL not in rec.table.columns:
            return select
        self.note(tag, f"시점 조건이 없어 고정 시점 {years} 을 넣음")
        return {**select, TIME_COL: years}

    def fix_region(self, tag: str, select: Select, regions: list[str] | None, record_id: str | None) -> Select:
        """지역 열(열 이름에 행정구역·지역·시도·시군구)의 값이 고정 지역 밖이면 고정 지역으로. 일부만 고른 것은 그대로

        고정 지역 중 그 열에 실제로 있는 값만 쓴다. 하나도 없으면 고정하지 않는다
        (재작성 모듈이 지역 칸에 지역이 아닌 말을 넣는 경우가 있다. 예: 2026-11-11 '지역 혼인건수')
        """
        rec = self.records.get(record_id or "")
        if not regions or rec is None:
            return select
        cols = rec.table.columns
        # [NEW 11-13] 질문의 지역(시도 이름)이 View 의 지역 열에 하나도 없으면 다른 지역의 값을 대신 쓰지 않는다 (서울 질문에 부산 값)
        region_cols = [c for c in cols if any(h in c for h in REGION_HINTS)]
        real = [r for r in regions if _REAL_REGION.search(r)]
        if real and region_cols:
            has = {str(r[cols.index(c)]) for c in region_cols for r in rec.table.rows}
            if not set(real) & has and not region_scope.within(rec, real):
                self.withhold(tag, f"질문의 지역 {real} 이 {region_cols} 에 없음 (View 의 지역: {sorted(has)[:5]})",
                              f"질문의 지역({', '.join(real)}) 자료가 없어 계산하지 못했습니다 (받은 자료의 지역: {', '.join(sorted(has)[:3])}).")
                return select
        for col in [c for c in select if c in cols and any(h in c for h in REGION_HINTS)]:
            have = {str(r[cols.index(col)]) for r in rec.table.rows}
            usable = [r for r in regions if r in have]
            vals = [str(v) for v in select[col]]
            if not usable:
                self.note(tag, f"고정 지역 {regions} 이 {col} 에 없음 → 지역은 고정하지 않음")
            elif not set(vals) <= set(usable):
                self.note(tag, f"{col} {vals} 은 고정 지역 {usable} 밖 → {usable}")
                select = {**select, col: usable}
        return select

    def fix_age(self, tag: str, select: Select, age: list[str] | None, record_id: str | None) -> Select:
        """질문 연령 범위 안의 일부 나이만 고른 것 → View 에서 그 범위에 드는 나이 전체 ('미취학아동' 인데 ['0세'] 만)

        View 는 이미 그 범위로 잘려 온다. 범위 밖 나이를 고른 것, 나이로 읽을 수 없는 값('계')은 건드리지 않는다.
        """
        rec = self.records.get(record_id or "")
        if not age or rec is None:
            return select
        lo, hi = int(age[0] or 0), (int(age[1]) if age[1] else None)
        inside = lambda s: s is not None and s[0] >= lo and (hi is None or (s[1] is not None and s[1] <= hi))  # noqa: E731
        cols = rec.table.columns
        for col in [c for c in select if c in cols and any(h in c for h in AGE_HINTS)]:
            have = list(dict.fromkeys(str(r[cols.index(col)]) for r in rec.table.rows))
            in_range = [v for v in have if inside(age_span(v))]
            chosen = [str(v) for v in select[col]]
            if in_range and all(inside(age_span(v)) for v in chosen) and set(chosen) < set(in_range):
                self.note(tag, f"{col} {chosen} → 질문 연령 {lo}~{'' if hi is None else hi}세에 드는 값 전체 {in_range}")
                select = {**select, col: in_range}
        return select

    def present_years(self, tag: str, years: list[str] | None, record_id: str | None) -> list[str] | None:
        """[NEW 11-17] 고정 시점 중 View 의 시점 열에 실제로 있는 것만. 하나도 없으면 None (고정하지 않는다).
        View 모듈은 명시한 연도가 표에 없으면 다른 연도로 바꾸고 notes 에 적는다 (missing · default). 그 View 에 질문의 연도를 다시
        조건으로 넣으면 고를 행이 없어 '2026년 자료가 없습니다' 로 끝났다 (자체 검토 A-1). 지역 고정(fix_region)과 같은 규칙이다"""
        rec = self.records.get(record_id or "")
        if not years or rec is None or TIME_COL not in rec.table.columns:
            return years
        ti = rec.table.columns.index(TIME_COL)
        have = {str(r[ti]) for r in rec.table.rows}
        kept = [y for y in years if y in have]
        if kept == years:
            return years
        gone = [y for y in years if y not in have]
        # [CHANGED 11-17 외부 피드백] 이전: View 에 없으면 무조건 뺐다 → 메모 없는 입력에서 2026 질문이 조용히 2025 값으로 답했다.
        #   View 가 그 시점의 대체를 기록했을 때(build_view.match_period 의 missing · default, 최신값 조회의 latest_shift)만 뺀다
        if not set(gone) <= _substituted_years(rec):
            self.note(tag, f"고정 시점 {gone} 이 자료에 없고 View 에 대체 기록도 없음 → 고정 시점 그대로 (계산하지 않음)")
            return years
        self.note(tag, f"고정 시점 {gone} 이 자료에 없음 → " + (f"있는 시점 {kept} 만 고정" if kept else "시점은 고정하지 않음"))
        if kept:      # 기간이 줄었다 (2021~2026 → 2021~2025). View 메모만으로는 계산 기간이 바뀐 것을 알 수 없어 사용자에게 알린다
            span = f"{kept[0]}~{kept[-1]}" if len(kept) > 1 else kept[0]
            self.warnings.append(f"{', '.join(f'{y}년' for y in gone)} 자료가 없어 {span}년 자료로 계산했습니다.")
        return kept or None

    def fix_select(self, tag: str, op: str, select: Select, d: _Args, fixed: dict,
                   record_id: str | None = None, answer: bool = False) -> tuple[Select, _Args]:
        years = self.present_years(tag, fixed.get(TIME_COL), record_id)      # [CHANGED 11-17] 이전: fixed.get(TIME_COL) 그대로 (A-1)
        select, d = self.fix_time(tag, op, select, d, years, answer, yearly=bool(fixed.get(YEARLY)))
        select = self.add_fixed_time(tag, select, years, record_id)
        select = self.cover_time_range(tag, op, select, years, record_id, fixed)
        select = self.fix_region(tag, select, fixed.get(REGION), record_id)
        select = self.fix_age(tag, select, fixed.get(AGE), record_id)
        select = self.drop_named_totals(tag, op, select, fixed)
        select = self.drop_summary_rows(tag, select, fixed, record_id)     # [NEW 11-25 1-8] 사례수 · 평균 같은 요약 값 행
        return self.fill_period(tag, op, select, d), d

    def drop_summary_rows(self, tag: str, select: Select, fixed: dict, record_id: str | None) -> Select:
        """[NEW 11-25 1-8] 고른 행의 한 열에 요약 값 행(사례수 · 평균 · 표준편차 · 중앙값 · 성비)과 일반 행이 섞이면 → 그 열을 일반 행으로 좁힌다.
        조사표는 응답 비율(%) 열에 사례수(명) · 평균(점)을 같은 열의 값으로 둔다 (원본 표 989개 중 사례수 106 · 평균 21 · 성비 16).
        View 에는 행마다 단위가 남지 않아 함께 계산 · 그리면 단위가 섞인다 (합성 사할린 만족도 표: 막대로 대체되며 '사례수 95.9%').
        빼지 않는 경우: 질문에 그 말이 있음('만족도 평균 점수는?') · 고른 행이 모두 요약 값 · 총계 행(계 · 합계 · 전국 — 기존 규칙에 맡긴다)"""
        rec = self.records.get(record_id) if record_id else None
        if rec is None:
            return select
        sel = select_rows(rec, select, None)
        if not sel.rows:
            return select
        question = re.sub(r"\s+", "", " ".join(fixed.get(ORIGINAL) or []))
        for word in _SUMMARY_FALSE:              # '구성비' 의 '성비' 는 성비를 물은 것이 아니다
            question = question.replace(word, "")
        out = dict(select)
        for col in sel.columns:
            if col in (TIME_COL, VALUE_COL):
                continue
            vals = list(dict.fromkeys(str(r[sel.col(col)]) for r in sel.rows))
            if len(vals) < 2:
                continue
            drop = [v for v in vals if (w := _summary_word(v)) and w not in question]
            regular = [v for v in vals if not _summary_word(v)]
            if drop and regular:
                out[col] = [v for v in vals if v not in drop]
                self.note(tag, f"열 '{col}' 의 요약 값 {drop} 은 분포 · 구성의 조각이 아니라서 뺌 (사례수 · 평균처럼 단위가 다른 행)")
        return out

    def drop_named_totals(self, tag: str, op: str, select: Select, fixed: dict) -> Select:
        """[NEW 11-17] 범주 비교 질문(비교축이 있거나 의도가 순위)의 순위 · 극값은 조건에 적힌 총계(전국 · 계)를 뺀다.
        HCX 가 '시도별 순위' 에 지역 17개를 전국까지 모두 나열하면, 조건에 이름이 있다는 이유로 전국이 1위가 됐다 (외부 피드백 남은 한계).
        총계만 고른 조건('전국' 하나)은 그대로 둔다. 전국을 직접 견주는 질문은 비교축이 없으므로 이 규칙에 걸리지 않는다"""
        if op not in TOTAL_FREE_OPS or not (fixed.get(AXIS) or "순위" in fixed.get(INTENT, [])):
            return select
        out = dict(select)
        for col, vals in select.items():
            names = [str(v) for v in vals]
            if (total := totals_in(col, names)) and set(names) - total:
                out[col] = [v for v in vals if str(v) not in total]
                self.note(tag, f"범주 비교 질문이라 {col} 조건의 총계 {sorted(total)} 를 뺌")
        return out

    def _aliases(self, fixed: dict) -> list[str]:
        """항목 후보를 찾는 별칭: 원문표현 + '=' 조건의 값. 승인은 correspondence 의 측정 호환 검사가 한다 (이름 일치만으로 승인하지 않는다)"""
        conds = [str(c["value"]) for c in fixed.get(COND_EXPR) or [] if c.get("op") == "="]
        return list(dict.fromkeys([*(fixed.get(SURFACE) or []), *conds]))

    @staticmethod
    def _indicator_terms(fixed: dict, op: str | None = None) -> tuple[list[str], frozenset[str]]:
        """[NEW 11-25] (대응을 검사할 지표, 허용 수식어). 1-2 · 15유형 테스트에서 차트 계획 누락 11건 중 9건의 원인.
        - 허용 수식어 = 고정 조건의 성별 값 + 지표 칸에 섞인 성별 단어 (별칭 포함: 남자 → 남자 · 남 · 남성)
        - 지표 칸의 성별 단어는 지표가 아니므로 뺀다 ('남자, 인구' → '인구'). 빼고 남는 지표가 없으면 대상을 지표로 쓴다
          (대상도 없으면 빈 목록 → 지표 검사를 하지 않는다. 지금도 지표가 없으면 검사하지 않는다)
        질문에 성별이 없으면 수식어가 없어 지금과 같다 (총인구를 물었는데 남자인구수로 답하지 않는다)
        [NEW 11-25 A-2] op 가 share 면 '○○비율 · ○○비중 · ○○구성비' 지표에 분자 '○○' 도 함께 넣는다.
          비중을 계산하는 피연산자는 분자 항목이다 ('보증부월세비율' 을 물으면 표의 '보증부월세'). 원래 지표도 남긴다.
          share 가 아니면 그대로 (비율 지표는 이름이 같을 때만 — 비율 표의 값을 그대로 답하는 경우)"""
        raw = [str(x) for x in fixed.get(INDICATOR) or []]
        in_ind = [x for x in raw if re.sub(r"\s+", "", x) in SEX_MODIFIERS]
        # [CHANGED 11-25 C] 지표 칸의 성별 단어가 있으면 그것이 이 하위 질문의 성별 (성별 칸은 질문 전체의 '남자, 여자' 일 수 있다).
        #   이전: 둘을 합쳐 '남자' 하위 질문에도 '여자' 수식어를 허용했다
        mods = {m for s in (in_ind or fixed.get(SEX) or []) for m in SEX_MODIFIERS.get(re.sub(r"\s+", "", str(s)), ())}
        wanted = [x for x in raw if x not in in_ind]
        if in_ind and not wanted:
            wanted = [str(x) for x in fixed.get(TARGET) or []]
        if op == "share":
            parts = [p for w in wanted if (p := _SHARE_TAIL.sub("", w)) and p != w]
            wanted = list(dict.fromkeys([*wanted, *parts]))
        return wanted, frozenset(mods)

    @staticmethod
    def _requested_sexes(fixed: dict) -> set[str]:
        """[NEW 11-25 C] 이 하위 질문이 요청한 성별 하나 ({'남자'} · {'여자'}). 남녀 둘 다이거나 성별이 없으면 빈 집합 (검사하지 않는다).
        지표 칸의 성별 단어가 성별 칸보다 우선 ('남자' 하위 질문인데 성별 칸은 질문 전체의 '남자, 여자')"""
        raw = [re.sub(r"\s+", "", str(x)) for x in fixed.get(INDICATOR) or []]
        words = [x for x in raw if x in SEX_MODIFIERS] or [re.sub(r"\s+", "", str(x)) for x in fixed.get(SEX) or []]
        canon = {SEX_MODIFIERS[w][0] for w in words if w in SEX_MODIFIERS}
        return canon if len(canon) == 1 else set()

    @staticmethod
    def _item_sex(item: str) -> str | None:
        """[NEW 11-25 C] 항목 이름이 성별로 시작하면 그 성별 ('여자인구수' → 여자). 한 글자(남 · 여)는 보지 않는다 ('남녀인구' 를 남자로 읽지 않게)"""
        name = re.sub(r"\s+", "", strip_unit(item or ""))
        for word, canon in (("남자", "남자"), ("남성", "남자"), ("여자", "여자"), ("여성", "여자")):
            if name.startswith(word) and len(name) > len(word):
                return canon
        return None

    def _sex_conflict(self, item: str, sexes: set[str]) -> bool:
        """항목의 성별이 이 하위 질문이 요청한 성별과 다른가 (남자를 물었는데 여자인구수)"""
        s = self._item_sex(item)
        return bool(sexes) and s is not None and s not in sexes

    @staticmethod
    def _in_question(rec: Record, item: str, fixed: dict) -> bool:
        """[NEW 11-25 A-1] 항목 이름(단위 괄호 제외, 띄어쓰기 무시)이 원 질문 문장에 그대로 있고, 표의 '항목' 열 값인가. 두 글자 미만은 보지 않는다.
        '항목' 열 값만 본다: 범주 열의 값('가구원수별' 의 '2인')을 항목으로 적은 경우까지 인정하면, 그 범주의 모든 항목
        (계 · 침실수 1 · 거실수 0 …)이 한 계산에 섞였다 (재현: '2인 가구는 몇 집' 이 192개 값 목록이 됨)"""
        name = re.sub(r"\s+", "", strip_unit(item or ""))
        text = re.sub(r"\s+", "", " ".join(fixed.get(ORIGINAL) or []))
        if len(name) < 2 or name not in text or ITEM_COL not in rec.table.columns:
            return False
        col = rec.table.columns.index(ITEM_COL)
        return any(re.sub(r"\s+", "", strip_unit(str(r[col]))) == name for r in rec.table.rows)

    def _has_indicator_item(self, rec: Record, wanted: list[str], strict: bool, modifiers=frozenset()) -> bool:
        """View 의 항목 열에 요청한 지표 자체(이름 경로)에 대응하는 항목이 있는가. 있으면 별칭 항목은 분류 값이라 지표로 승인하지 않는다"""
        if ITEM_COL not in rec.table.columns:
            return False
        col = rec.table.columns.index(ITEM_COL)
        return any(correspondence(i, unit_of(i, rec.metadata.get("unit")), wanted, [], (), strict, modifiers) == "name"
                   for i in dict.fromkeys(str(r[col]) for r in rec.table.rows))

    def _item_via(self, rec: Record, item: str, fixed: dict, strict: bool, op: str | None = None) -> str | None:
        """항목이 요청 지표에 대응하는 경로(name · target · alias). 대응하지 않으면 None. 별칭으로 승인한 항목은 alias_ok 에 남긴다
        [NEW 11-25 A-1] 항목 이름이 원 질문 문장에 그대로 있으면 별칭 후보로 넣는다 (질의 분석이 원문표현을 놓친 회차에서
          '화성군 보증부월세 비율' 이 보류됐다). 승인 조건은 다른 별칭과 같다: 측정 호환이 True (가구수 ↔ 단위 가구) ·
          표에 지표 이름 그대로인 항목이 없을 것"""
        wanted, mods = self._indicator_terms(fixed, op)      # [CHANGED 11-25] 이전: fixed.get(INDICATOR) 그대로 · 수식어 없음
        aliases = self._aliases(fixed)
        if self._in_question(rec, item, fixed):
            aliases = [*aliases, item]
        via = correspondence(item, unit_of(item, rec.metadata.get("unit")), wanted, fixed.get(TARGET) or [],
                             aliases, strict, mods)
        if via == "alias" and self._has_indicator_item(rec, wanted, strict, mods):
            return None
        if via == "alias":
            self.alias_ok.add((rec.id, item))
        return via

    def check_indicator(self, tag: str, picks: list[Pick], fixed: dict, op: str | None = None) -> list[Pick]:
        """[NEW 11-18] 계산에 쓸 항목이 질문의 지표와 대응하는지 (F7 · F16). '시도별 인구 순위' 에 출생성비 표가 와도 HCX 가 총출생성비를 골라
        순위를 냈다 (Q08). 대응하지 않으면 → 같은 View 에 대응하는 항목이 하나뿐이면 그 항목으로 바꾸고, 아니면 계산하지 않는다.
        View 가 '지표와 맞는 항목 없음' 이라고 적었으면 수식어 허용 없이 이름이 같을 때만 대응으로 본다
        [CHANGED 11-20] 이전: corresponds(item, wanted, targets, strict) — 대상 이름이 맞으면 측정 대상이 달라도(가구원수 ↔ 가구수) 승인했고,
        원문표현 · 조건 값은 쓰지 않았다. 이제 항목의 원 단위로 측정 호환을 확인하고(indicator.correspondence), 별칭 경로를 더했다.
        항목이 정해지지 않은 피연산자(item 없음, select 의 항목이 하나로 안 정해짐)는 선택된 행의 항목 전체를 검사한다 (check_rows_indicator)
        [CHANGED 11-25] op: 계산 종류 (share 면 '○○비율' 지표의 분자 '○○' 도 대응으로 본다 — _indicator_terms)"""
        wanted, _ = self._indicator_terms(fixed, op)         # [CHANGED 11-25] 지표 칸의 성별 단어를 뺀 지표 (보류 문구도 이것으로)
        # [NEW 11-25 C] 이 하위 질문이 요청한 성별 하나. 지표가 성별 단어뿐이라(지표 '남자') 지표 검사를 건너뛰는 경우에도 성별은 본다.
        #   '남자' 하위 질문에 여자인구수 표가 짝지어져 HCX 가 여자인구수를 고르면 여자 값이 남자 값으로 계산됐다 (15유형 T2-pie)
        sexes = self._requested_sexes(fixed)
        if not wanted and not sexes:
            return picks
        out = []
        for p in picks:
            rec = self.records.get(p.record_id)
            item = p.item or (str(v[0]) if len(v := p.select.get(ITEM_COL) or []) == 1 else None)
            if rec is not None and item is None and ITEM_COL in rec.table.columns:
                sel = self.check_rows_indicator(tag, p.record_id, p.select, fixed, op) if wanted else p.select
                out.append(p if sel is None else p.model_copy(update={"select": sel}))
                continue
            if rec is None or item is None or is_category_label(item):     # 항목이 나이 · 성별 같은 구분 값이면 지표를 알 수 없다
                out.append(p)
                continue
            strict = any(n.slot == "지표" and n.type == "default" for n in rec.notes)

            def fits(name: str) -> bool:
                # 개수 지표면 대상 이름 · 별칭도 허용(측정 호환 True 일 때), 비율 지표면 지표 이름만 (검토 11) + [C] 요청한 성별과 다르지 않을 것
                return (not wanted or bool(self._item_via(rec, name, fixed, strict, op))) and not self._sex_conflict(name, sexes)

            if fits(item):
                out.append(p)
                continue
            col = rec.table.columns.index(ITEM_COL) if ITEM_COL in rec.table.columns else None
            # 지표가 성별 단어뿐이면(wanted 없음) 그 성별로 시작하는 항목만 대안 (계 · 다른 지표로 바꾸지 않는다)
            alts = list(dict.fromkeys(str(r[col]) for r in rec.table.rows
                                      if fits(str(r[col])) and (wanted or self._item_sex(str(r[col])) in sexes))) if col is not None else []
            sex_txt = ", ".join(sorted(sexes))
            asked = f"요청 지표 {wanted}" if wanted else f"요청한 성별 {sex_txt}"
            if len(alts) == 1:
                new = alts[0]
                self.note(tag, f"항목 '{item}' 은 {asked} 와 다름 → View 의 '{new}' 로 바꿈")
                sel = {**p.select, ITEM_COL: [new]} if ITEM_COL in p.select else p.select
                by_sex = self._sex_conflict(item, sexes) or not wanted
                note = (f"요청한 성별({sex_txt})에 맞는 항목 '{new}' 으로 계산함 (고른 '{item}' 은 다른 성별)" if by_sex else
                        f"요청한 지표({', '.join(wanted)})에 맞는 항목 '{new}' 으로 계산함 (고른 '{item}' 은 다른 지표)")   # 기존 문구 그대로
                out.append(p.model_copy(update={"item": new if p.item else None, "select": sel, "note": note}))
                continue
            if self._sex_conflict(item, sexes):
                self.withhold(tag, f"항목 '{item}' 이 요청한 성별 {sex_txt} 과 다름 (View 의 대응 항목: {alts or '없음'})",
                              f"요청한 성별({sex_txt})의 값이 이 표에 없어 계산하지 못했습니다 (표의 항목: {item}).")
            else:
                self.withhold(tag, f"항목 '{item}' 이 요청 지표 {wanted} 와 대응하지 않음 (View 의 대응 항목: {alts or '없음'})",
                              f"요청한 지표({', '.join(wanted)})가 이 표에 없어 계산하지 못했습니다 (표의 항목: {item}).")
            out.append(p)
        return out

    def check_rows_indicator(self, tag: str, record_id: str, select: Select, fixed: dict, op: str | None = None) -> Select | None:
        """[NEW 11-20] 항목이 정해지지 않은 선택(차트의 상위 select 등)이 실제로 고르는 행의 항목을 모두 검사한다 (KOS-26 A-3).
        이전: item 이 없으면 검사를 건너뛰어, 인구수를 요구하면서 출생성비 View 에 시점만 고른 차트가 보류 없이 통과했다.
        모두 대응하면 그대로, 대응하는 항목이 하나뿐이면 항목 열 조건을 그 항목으로 좁히고, 아니면 보류한다 (None)"""
        wanted, _ = self._indicator_terms(fixed, op)         # [CHANGED 11-25] 지표 칸의 성별 단어를 뺀 지표 (share 면 분자 포함)
        rec = self.records.get(record_id)
        if not wanted or rec is None or ITEM_COL not in rec.table.columns:
            return select
        sel = select_rows(rec, select, None)
        if not sel.rows:
            return select                      # 행이 없는 사유는 다른 검증이 낸다
        ii = sel.col(ITEM_COL)
        items = list(dict.fromkeys(str(r[ii]) for r in sel.rows))
        if all(is_category_label(i) for i in items):
            return select
        strict = any(n.slot == "지표" and n.type == "default" for n in rec.notes)
        good = [i for i in items if not is_category_label(i) and self._item_via(rec, i, fixed, strict, op)]
        bad = [i for i in items if not is_category_label(i) and i not in good]
        if not bad:
            return select
        if len(good) == 1:
            self.note(tag, f"선택한 행의 항목 {items} 중 요청 지표 {wanted} 에 대응하는 '{good[0]}' 만 남김")
            return {**select, ITEM_COL: [good[0]]}
        if not good and (narrowed := self._narrow_by_other_column(tag, rec, sel, select, fixed, strict, op)) is not None:
            return narrowed                    # 지표 이름이 항목 열이 아니라 분류 열(종류별 …)에 있는 표 (find_item_column 과 같은 가정)
        self.withhold(tag, f"선택한 행의 항목 {items} 이 요청 지표 {wanted} 와 대응하지 않음 (대응 항목: {good or '없음'})",
                      f"요청한 지표({', '.join(wanted)})가 이 표에 없어 계산하지 못했습니다 (표의 항목: {', '.join(items[:3])}).")
        return None

    def _narrow_by_other_column(self, tag: str, rec: Record, sel, select: Select, fixed: dict, strict: bool,
                                op: str | None = None) -> Select | None:
        """지표 이름이 든 다른 열(시점 · 값 · 지역 · 연령 · 성별 제외)을 찾아 그 열의 선택을 요청 지표에 대응하는 값으로 좁힌다.
        대응하는 값이 하나라도 있다고 선택 전체를 승인하면 안 된다 (종류별 열에 출생아수 100 · 사망자수 999 가 같이 있는데 출생아수를 물은 경우).
        대응하는 열이 없으면 None. 좁힌 select 로 고르는 행은 모두 요청 지표에 대응한다 (좁힌 열의 값이 전부 good 이므로)"""
        for col in sel.columns:
            if col in (ITEM_COL, VALUE_COL, TIME_COL) or any(h in col for h in CATEGORY_HINTS):
                continue
            vals = list(dict.fromkeys(str(r[sel.col(col)]) for r in sel.rows))
            good = [v for v in vals if self._item_via(rec, v, fixed, strict, op)]
            if not good:
                continue
            if len(good) == len(vals):
                return select
            self.note(tag, f"열 '{col}' 의 값 {vals} 중 요청 지표 {fixed.get(INDICATOR)} 에 대응하는 {good} 만 남김")
            return {**select, col: good}
        return None

    # ── 조건 적용 (KOS-26 A-2) ──────────────────────────────────
    def check_conditions(self, tag: str, picks: list[Pick], fixed: dict) -> list[Pick]:
        """[NEW 11-20] 질문의 조건(조건식)을 피연산자의 행 선택에 적용했는지. 적용하지 못한 조건이 하나라도 있으면 계산하지 않는다.
        이전: 슬롯의 조건이 표에 적용되지 못해도 알림 없이 조건 없는 값이 정상 답으로 나갔다 (장래가구추계 가구원수>=5).
        비교 연산(>=, < …)은 아직 지원하는 연산이 없어 항상 보류한다. '=' 조건은 분류 축을 식별해 선택을 맞추고, 못 찾으면 보류한다"""
        conds = fixed.get(COND_EXPR) or []
        if not conds:
            return picks
        for c in conds:
            if c["op"] != "=":
                self.withhold(tag, f"조건 '{c['text']}' 의 비교 연산({c['op']})은 지원하지 않음",
                              f"'{c['text']}' 같은 조건부 집계는 아직 지원하지 않아 계산하지 못했습니다.")
                return picks
        out = []
        for p in picks:
            rec = self.records.get(p.record_id)
            for c in conds if rec is not None else []:
                p = self.apply_condition(tag, rec, p, c)
                if tag in self.withheld:
                    return picks
            out.append(p)
        return out

    def apply_condition(self, tag: str, rec: Record, p: Pick, c: dict) -> Pick:
        """'=' 조건 하나를 피연산자에 적용. 열을 못 찾으면 보류"""
        ax = find_axis(rec, c, {i for rid, i in self.alias_ok if rid == rec.id})

        def fail(why: str):
            self.withhold(tag, f"조건 {c['text']} 을 적용하지 못함: {why}", f"'{c['text']}' 조건을 적용할 자료가 없어 계산하지 못했습니다.")

        if ax.column is None:
            fail(ax.why)
            return p
        value = str(c["value"])
        if ax.column == ITEM_COL:
            item = p.item or (str(v[0]) if len(v := p.select.get(ITEM_COL) or []) == 1 else None)
            shown = item_column_value(rec, item)
            if shown is None or strip_unit(shown) != strip_unit(value):
                fail(f"고른 항목 '{item}' 이 조건 값 '{value}' 과 다름")
            return p
        if [str(v) for v in p.select.get(ax.column) or []] == [value]:
            return p
        self.note(tag, f"조건 {c['text']}: 열 '{ax.column}' 의 선택을 {p.select.get(ax.column)} → [{value}] 로 맞춤")
        return p.model_copy(update={"select": {**p.select, ax.column: [value]}})

    def violated_condition(self, record_id: str, select: Select, item: str | None, fixed: dict) -> str | None:
        """[NEW 11-20] 최종 선택이 조건을 어기는지 — 병합 · 보정 뒤 범위가 다시 넓어졌는지 (KOS-26 A-2 ③). 어기면 조건 문장, 아니면 None"""
        rec = self.records.get(record_id)
        if rec is None:
            return None
        for c in fixed.get(COND_EXPR) or []:
            if c["op"] != "=":
                return c["text"]
            ax = find_axis(rec, c, {i for rid, i in self.alias_ok if rid == rec.id})
            if ax.column is None:
                return c["text"]
            value = str(c["value"])
            have = selected_values(rec, select, item, ax.column) or set()
            if ax.column == ITEM_COL:
                have = {strip_unit(v) for v in have}
                value = strip_unit(value)
            if have and have != {value}:
                return c["text"]
        return None

    def check_columns(self, tag: str, p: Pick) -> Select:
        """[NEW 11-18] select 의 열이 View 에 없을 때 (F13). 이전: 계산 전체가 '열 없음' 으로 실패했다 (HCX 가 '대상' 열을 넣은 Q02).
        그 조건이 이미 적용된 것이 확인될 때만 버린다 — 조건 값이 고른 항목 이름에 들어 있을 때 ('대상: 혼인' ↔ 혼인건수).
        그 밖의 조건(남녀구분=여자)은 버리면 질문과 다른 값(전체)을 계산하므로 계산하지 않는다"""
        rec = self.records.get(p.record_id)
        if rec is None:
            return p.select
        cols = set(rec.table.columns)
        unknown = [c for c in p.select if c not in cols]
        if not unknown:
            return p.select
        # [CHANGED 11-18] 이전: 항목 이름 + View 설명(lexical_text)에 단어가 있으면 적용된 것으로 봤다 → 설명에 '남자 여자' 가 있으면 남녀구분=여자 를
        #   지우고 전체 100명을 계산했다 (검토 2). 실제로 고른 **항목 이름**에 조건 값이 들어 있을 때만 (대상: 혼인 ↔ 항목 혼인건수)
        applied = " ".join([p.item or "", *[str(v) for v in p.select.get(ITEM_COL) or []]])
        keep = {c: v for c, v in p.select.items() if c in cols}
        for c in unknown:
            vals = [str(v) for v in p.select[c]]
            if vals and all(v in applied for v in vals):
                self.note(tag, f"조건 {c}={vals} 은 표에 열이 없지만 고른 항목 이름에 이미 반영되어 있어 버림")
            else:
                self.withhold(tag, f"조건 {c}={vals} 을 적용할 열이 표에 없음 (표의 열: {sorted(cols)})",
                              f"조건 '{c}: {', '.join(vals)}' 을 적용할 열이 표에 없어 계산하지 못했습니다.")
                return p.select
        return keep

    def cover_time_range(self, tag: str, op: str, select: Select, years: list[str] | None, record_id: str | None,
                         fixed: dict | None = None) -> Select:
        """[NEW 11-18] 시점끼리 견주는 극값 · 순위는 비교할 시점을 빠짐없이 골라야 한다 (F12). HCX 에게 연도 40개만 보여 주던 때 1970~2009 만 골라
        '가장 많은 해' 가 틀렸다 (Q33). 질문이 기간을 줬으면 그 기간(View 에 있는 해), 아니면 View 의 모든 시점으로 넓힌다"""
        rec = self.records.get(record_id or "")
        chosen = [str(v) for v in select.get(TIME_COL) or []]
        # 시점을 둘 이상 골랐거나, 질문이 해끼리 견주는데(비교축 연도) 기간을 정하지 않았을 때 (HCX 가 한 해만 골라도 전체 기간으로) — 검토 10.
        # 질문이 한 해를 직접 정한 경우(years 에 있음)나 시도별 순위처럼 비교축이 시점이 아닌 경우는 건드리지 않는다
        time_axis = bool(set((fixed or {}).get(AXIS, [])) & _TIME_AXES) and not years
        if op not in TOTAL_FREE_OPS or not chosen or (len(chosen) < 2 and not time_axis) or rec is None or TIME_COL not in rec.table.columns:
            return select
        ti = rec.table.columns.index(TIME_COL)
        have = list(dict.fromkeys(str(r[ti]) for r in rec.table.rows))
        want = [y for y in have if not years or y in years]
        missing = [y for y in want if y not in set(chosen)]
        if not missing:
            return select
        self.note(tag, f"{op} 의 시점 {len(chosen)}개가 비교할 시점 {len(want)}개에 모자람 → 빠진 {len(missing)}개({missing[0]}~{missing[-1]})를 넣음")
        return {**select, TIME_COL: want}

    def normalize(self, tag: str, op: str, picks: list[Pick], d: _Args, chart_type: str | None = None,
                  fixed: dict | None = None) -> tuple[list[Pick], _Args]:
        picks = self.category_item_to_condition(tag, self.drop_non_operands(tag, picks))
        picks = self.check_indicator(tag, picks, fixed or {}, op)
        if op in TWO_OPERAND:
            if len(picks) > 2:
                self.note(tag, f"{op} 는 피연산자 2개 → 앞의 2개만 씀 (버린 항목: {[p.item for p in picks[2:]]})")
                picks = picks[:2]
        elif op == "combine":                # 더하고 빼는 값들이라 같은 항목이어도 합치지 않는다
            if len(picks) < 2:
                self.note(tag, f"combine 은 피연산자 2개 이상이 필요 (받은 것 {len(picks)}개)")
        elif chart_type is None or chart_type not in MULTI_BRANCH:
            picks = self.merge_same_item(tag, op, picks, keep_first=chart_type is None)
        if chart_type:
            picks = self.fix_branch_roles(tag, chart_type, picks)
        out, d2 = [], d
        for p in picks:
            p = p.model_copy(update={"select": self.check_columns(tag, p)})
            sel, d2 = self.fix_select(tag, op, p.select, d, fixed or {}, p.record_id, answer=chart_type is None)
            out.append(p.model_copy(update={"select": sel}))
        if tag in self.withheld:                      # 지역 불일치 등 → 이 계산의 피연산자를 비운다
            return [], d2
        # [NEW 11-20] 조건식 적용 + 최종 선택이 조건을 어기지 않는지 (merge · fix_select 가 범위를 넓힌 경우를 잡는다)
        out = self.check_conditions(tag, out, fixed or {})
        for p in out if tag not in self.withheld else []:
            if bad := self.violated_condition(p.record_id, p.select, p.item, fixed or {}):
                self.withhold(tag, f"최종 선택이 조건 '{bad}' 을 만족하지 않음", f"'{bad}' 조건을 적용할 자료가 없어 계산하지 못했습니다.")
        if tag in self.withheld:
            return [], d2
        return out, d2

    def actual_item(self, tag: str, record_id: str, item: str | None, select: Select) -> tuple[str | None, str | None]:
        """요청한 항목이 View 의 항목과 괄호 단위만 다르면('인구(명)' ↔ '인구(천명)') View 의 이름을 돌려준다 (notes 에 남긴다).
        [NEW 11-16] 이전에는 계산 단계(load_series)만 바로잡아 display_ref·답변·차트 축이 요청한 단위('50명')로 남았다 (검수 1)"""
        rec = self.records.get(record_id)
        if rec is None or item is None:
            return item, None
        found = select_rows(rec, select, item).item
        if found and found != item and _only_unit_added(item, found):      # [NEW 11-18] '(명)' 만 덧붙은 이름은 같은 항목: 바꿨다는 안내 없이 View 이름을 쓴다
            return found, None
        if found and found != item:
            self.note(tag, f"항목 '{item}' 은 자료의 '{found}' 로 바꿈 (괄호 단위가 다름)")
            # 답변에도 전달한다: Operand.note → CalcResult.note → 모듈 6 주의사항 (검수 6. 이전에는 notes 에만 남아 답변에서 사라졌다)
            return found, f"항목 '{item}' 은 자료의 '{found}' 로 계산함"
        return item, None

    def operand(self, tag: str, pick: Pick, role: str) -> Operand:
        item, why = self.actual_item(tag, pick.record_id, pick.item, pick.select)
        pick = pick.model_copy(update={"item": item})
        self.check(tag, pick.record_id, pick.select, pick.item)
        unit, source = self.unit_with_source(pick.record_id, pick.item, pick.select)
        if unit is None and (unit := self.hcx_unit(tag, pick)):
            source = "hcx"
        return Operand(role=role, record_id=pick.record_id, item=pick.item, select=pick.select, unit=unit,
                       unit_source=source, note=pick.note or why)

    def unit_with_source(self, record_id: str, item: str | None, select: Select) -> tuple[str | None, str | None]:
        rec = self.records.get(record_id)
        if item is None and len(items := select.get(ITEM_COL) or []) == 1:
            item = str(items[0])
        if bracket := unit_of(item):
            return bracket, "item"
        if table := unit_of(item, rec.metadata.get("unit") if rec else None):     # [CHANGED 11-24] 이전: item 없이 → 단위가 여러 개인 표는 항상 없음
            return table, "table"
        return None, None

    def hcx_unit(self, tag: str, pick: Pick) -> str | None:
        """항목 이름·metadata.unit 으로 단위를 정하지 못할 때 HCX 가 고른 단위. View 의 단위 목록 안에 있을 때만 믿는다

        KOSIS 가 표 단위로만 단위를 주는 표가 있다 (DT_1B81A23: 모든 행이 '명 가임여자 1명당 명').
        단위 자체에 띄어쓰기가 있어 코드로는 나눌 수 없고, 어느 항목의 단위인지도 데이터에 없다 → HCX 가 고르고 코드는 검사만.
        """
        rec = self.records.get(pick.record_id)
        listed = str(rec.metadata.get("unit") or "") if rec else ""
        if not pick.unit or not listed:
            return None
        # [CHANGED 11-11] 이전: pick.unit in listed (부분 문자열) — '가임여자 1명당 명' 의 '1명당' 도 승인했다 (검수)
        # 승인: 목록 전체와 같음 (단위가 하나뿐인 표) / 표준 단위이면서 목록 안에 띄어쓰기로 구분된 한 단어로 있음
        unit = pick.unit.strip()
        if unit == listed.strip() or (unit in STANDARD_UNITS and unit in listed.split()):
            return unit
        self.note(tag, f"HCX 단위 '{pick.unit}' 은 View 단위 목록 '{listed}' 의 단위로 확인되지 않음 → 단위 없음")
        return None

    def args(self, tag: str, op: str, d: _Args) -> dict:
        args = d.step_args()
        if op == "share":      # 분모 범위가 질문에 없으면 선택 항목의 합 + "선택 항목 내 비중" 표시 (명세 4장)
            den = args.get("denominator") or Denominator(scope="selected")
            if den.scope == "selected" and not den.label:
                den = den.model_copy(update={"label": SELECTED_LABEL})
            if den.scope == "question" and den.operand:
                self.check(tag, den.operand.record_id, den.operand.select, den.operand.item)
            args["denominator"] = den
        if op == "rank" and args.get("kind"):
            # [NEW 11-17] '가장 적은 해' 에 HCX 가 extreme 대신 rank + kind=min (+ order=desc) 를 냈다. rank 는 kind 를 읽지 않아
            #   큰 값부터 셌다 (보고서 11.3 H1). kind 가 질문의 뜻(가장 적은 · 많은)이라 order 보다 우선한다
            order = "asc" if args.pop("kind") == "min" else "desc"
            if args.get("order") != order:
                self.note(tag, f"rank 의 kind 를 정렬 방향으로 바꿈 → order {order}")
            args["order"] = order
        return args

    def columns(self, record_id: str) -> list[str]:
        rec = self.records.get(record_id)
        return list(rec.table.columns) if rec else []

    def range_total(self, tag: str, picks: list[Pick], fixed: dict) -> bool:
        """질문에 연령 범위가 있는데 raw 가 나이별 행 여럿을 골랐는가 (미취학아동수 → 0세·1세 … 5세 나열)"""
        if len(picks) != 1 or AGE not in fixed or set(fixed.get(INTENT, [])) & PER_CATEGORY_INTENTS:
            return False
        rec = self.records.get(picks[0].record_id)
        if rec is None:
            return False
        sel = select_rows(rec, picks[0].select, picks[0].item)
        distinct = {c: {str(r[sel.col(c)]) for r in sel.rows} for c in sel.columns if c != VALUE_COL}
        age_col = next((c for c, v in distinct.items() if any(h in c for h in AGE_HINTS) and len(v) > 1), None)
        if age_col is None:
            return False
        if distinct[age_col] & TOTAL_LABELS:      # '계' 가 섞이면 더할 때 두 번 센다 → 바꾸지 않는다
            self.note(tag, f"{age_col} 에 합계 행이 섞여 있어 합치지 않음 ({sorted(distinct[age_col] & TOTAL_LABELS)})")
            return False
        # 연령·시점 밖의 열이 여러 값이면(총인구와 성비, 서울과 부산) 더하면 서로 다른 것이 섞인다 → 바꾸지 않는다
        mixed = [c for c, v in distinct.items() if c not in (age_col, TIME_COL) and len(v) > 1]
        if mixed:
            self.note(tag, f"{', '.join(mixed)} 에 값이 여럿이라 연령 합계를 내지 않음 ({ {c: sorted(distinct[c]) for c in mixed} })")
            return False
        return True

    def widen_age_items(self, tag: str, picks: list[Pick], fixed: dict) -> list[Pick] | None | str:
        """[NEW 11-18] 나이가 `항목` 열 값(0세 · 1세 …)인 표에서 질문의 연령 범위(0~5세)를 합산한다 (F6, Q11 '미취학아동 수').
        이전: HCX 가 ['0세'] 만 골라도 그대로 0세 값(233,617명)을 답했다 (분류 열의 연령만 범위를 적용했다).
        → 범위에 드는 나이 항목 전체를 골라 합계(aggregate)로. 범위를 빈틈 · 겹침 없이 덮지 못하면 합계라고 답하지 않고 보류한다.
        반환: 바꾼 피연산자 목록 | None(해당 없음) | "withheld"(보류)"""
        if len(picks) != 1 or AGE not in fixed or set(fixed.get(INTENT, [])) & PER_CATEGORY_INTENTS:
            return None
        p = picks[0]
        rec = self.records.get(p.record_id)
        if rec is None or ITEM_COL not in rec.table.columns:
            return None
        ci = rec.table.columns.index(ITEM_COL)
        labels = list(dict.fromkeys(str(r[ci]) for r in rec.table.rows))
        ages = {v: age_span(v) for v in labels if v not in TOTAL_LABELS}
        chosen = [p.item] if p.item else [str(v) for v in p.select.get(ITEM_COL) or []]
        if not ages or any(s is None for s in ages.values()) or not chosen or any(ages.get(c) is None for c in chosen):
            return None                                           # 항목이 나이 구분이 아니다 (지표 이름이거나 일부만 나이)
        lo, hi = int(fixed[AGE][0] or 0), (int(fixed[AGE][1]) if fixed[AGE][1] else None)
        inside = lambda s: s[0] >= lo and (hi is None or (s[1] is not None and s[1] <= hi))  # noqa: E731
        in_range = sorted((v for v, s in ages.items() if inside(s)), key=lambda v: ages[v][0])
        if not set(chosen) <= set(in_range):
            return None                                           # 범위 밖 나이를 물었다: 건드리지 않는다
        spans = [ages[v] for v in in_range]
        gaps = [(a[1] + 1, b[0] - 1) for a, b in zip(spans, spans[1:]) if a[1] is not None and a[1] + 1 < b[0]]
        overlaps = [(a, b) for a, b in zip(spans, spans[1:]) if a[1] is None or b[0] <= a[1]]
        ends_ok = bool(spans) and spans[0][0] == lo and (spans[-1][1] == hi if hi is not None else spans[-1][1] is None)
        if gaps or overlaps or not ends_ok:
            why = "겹치는 구간이 있음" if overlaps else (f"빠진 나이 {gaps}" if gaps else "범위의 처음이나 끝 구간이 없음")
            self.withhold(tag, f"연령 {lo}~{'' if hi is None else hi}세 합계: {why} (자료의 나이: {in_range})",
                          f"연령 {lo}~{'' if hi is None else hi}세 전체를 덮는 자료가 없어 합계를 내지 못했습니다.")
            return "withheld"
        self.note(tag, f"나이가 항목 열 값이라 연령 {lo}~{'' if hi is None else hi}세의 항목 {in_range} 를 모두 골라 합계로 계산")
        return [p.model_copy(update={"item": None, "select": {**p.select, ITEM_COL: in_range}})]

    def two_roles(self, tag: str, picks: list[Pick]) -> list[str]:
        """diff · ratio 의 역할 (a, b). HCX 가 하나만 적거나 둘 다 같은 이름을 적어도 서로 달라야 한다.
        [CHANGED 11-16] 이전: 역할이 없으면 위치로 정했다 → ['b', 없음] 이 ['b', 'b'] 가 되어 같은 피연산자끼리 뺐다 (검수 M3-07)"""
        want = [p.role if p.role in ("a", "b") else None for p in picks]
        if len(set(w for w in want if w)) < len([w for w in want if w]):       # 둘 다 같은 역할: 어느 쪽이 a 인지 알 수 없다
            self.note(tag, f"피연산자 역할이 겹침 {[p.role for p in picks]} → 적은 순서대로 a, b")
            want = [None] * len(picks)
        free = [r for r in "ab" if r not in want]
        return [w or free.pop(0) for w in want]

    def step(self, tag: str, step_id: str, op: str, picks: list[Pick], d: _Args) -> Step:
        """picks 를 피연산자로 쓰는 단계 하나"""
        if op in TWO_OPERAND:
            roles = self.two_roles(tag, picks[:2])
        elif op == "combine":
            roles = ["term"] * len(picks)
        else:
            roles = ["part" if op == "share" else "value"] * len(picks)
        operands = [self.operand(tag, p, r) for p, r in zip(picks, roles)]
        if op == "combine":
            operands = [o.model_copy(update={"sign": p.sign or "+"}) for o, p in zip(operands, picks)]
            if len({o.unit for o in operands}) > 1:
                self.note(tag, f"combine 피연산자의 단위가 다름: {[o.unit for o in operands]} (계산하지 않음)")
        extra = {}
        if op == "aggregate":            # 시점마다 따로 합친다. HCX 스키마에는 by 가 없어 코드가 정한다
            rec = self.records.get(picks[0].record_id) if picks else None
            if rec is not None and TIME_COL in rec.table.columns:
                extra["by"] = [TIME_COL]
        digits = self.source_digits(op, [(o.record_id, o.item, o.select) for o in operands], operands[0].unit if operands else None, d.agg)
        return Step(step_id=step_id, op=op, operands=operands,
                    display_ref=self.ref(op, [o.unit for o in operands], digits), **self.args(tag, op, d), **extra)

    # ── 차트용 ───────────────────────────────────────────────────
    def plan(self, chart: ChartRequest, d: ChartDecision) -> Plan | None:
        tag, op = chart.chart_id, chart.measure
        self.scope[tag] = (chart.sub_question_ids[0] if len(chart.sub_question_ids) == 1 else None, tag, op)
        self.withheld.discard(tag)
        fixed = self.fixed_for(tag, chart.sub_question_ids)
        picks, d2 = self.normalize(tag, op, d.operands, d, chart.chart_type, fixed)
        select, d3 = self.fix_select(tag, op, d.select, d, fixed, d.record_id or (picks[0].record_id if picks else None))
        d = d2 if d.operands else d3
        if tag in self.withheld:
            return None
        record_id = d.record_id or (picks[0].record_id if picks else None)
        if record_id is None:
            self.note(tag, "record_id 가 없어 차트 계획을 만들지 않음")
            return None
        self.check_set(tag, chart.view_ids, [record_id, *(p.record_id for p in picks)])
        if not picks:      # [NEW 11-20] 피연산자가 없으면 상위 record_id · select 가 고르는 행 전체의 항목을 검사한다 (KOS-26 A-3)
            narrowed = self.check_rows_indicator(tag, record_id, select, fixed, op)
            if narrowed is not None:
                checked = self.check_conditions(tag, [Pick(record_id=record_id, select=narrowed)], fixed)
                select = checked[0].select
                if tag not in self.withheld and (bad := self.violated_condition(record_id, select, None, fixed)):
                    self.withhold(tag, f"최종 선택이 조건 '{bad}' 을 만족하지 않음", f"'{bad}' 조건을 적용할 자료가 없어 계산하지 못했습니다.")
            if tag in self.withheld:
                return None
        d = self.sum_denominator(tag, d)                     # [NEW 11-25 D-2] 분모 'A + B' → 항목들의 합
        d = self.same_view_total(tag, picks, d, chart.view_ids, fixed) or d
        if self.denominator_outside(tag, d, chart.view_ids):
            return None
        output, step_op = None, op
        # 연령 범위의 값 하나를 묻는 질문이면 차트도 나이별이 아니라 합계로 (질문용 계산과 같은 규칙)
        if op == "raw" and self.range_total(tag, picks or [Pick(record_id=record_id, select=select)], fixed):
            self.note(tag, f"차트 raw → aggregate(sum): 연령 {fixed[AGE][0]}~{fixed[AGE][1]}세 범위의 값 하나를 묻는 질문")
            step_op, d = "aggregate", d.model_copy(update={"agg": "sum"})
        if not picks:                                  # 갈래 하나, 상위 record_id·select 를 그대로 쓴다
            self.check(tag, record_id, select, None)
            by = {"by": [TIME_COL]} if step_op == "aggregate" and TIME_COL in self.columns(record_id) else {}
            unit = self.unit(record_id, None, select)
            steps = [Step(step_id="s1", op=step_op,
                          display_ref=self.ref(step_op, [unit], self.source_digits(step_op, [(record_id, None, select)], unit, d.agg)),
                          **self.args(tag, step_op, d), **by)]
        elif op in MULTI_OPERAND or len(picks) == 1:   # 단계 하나에 피연산자 여럿 (또는 하나)
            if op in TWO_OPERAND and len(picks) != 2:
                self.note(tag, f"{op} 는 피연산자 2개가 필요 (받은 것 {len(picks)}개)")
            steps = [self.step(tag, "s1", step_op, picks, d)]
        else:                                          # 갈래 여럿 → 갈래마다 단계 하나, output 이 축 역할에 연결
            steps = [self.step(tag, f"s{i}", op, [p], d) for i, p in enumerate(picks, 1)]
            output = [PlanOutput(step_id=s.step_id, role=p.role) for s, p in zip(steps, picks) if p.role in CHART_ROLES]
            if len(output) < len(picks):
                self.note(tag, "축 역할이 없는 갈래가 있음 (차트에 쓰이지 않음)")
            output = output or None
        title, why = clean_title(d.title, step_op)
        if why:
            self.note(tag, f"HCX 제목 '{d.title}' 버림 ({why}) → 규칙 제목")
        return Plan(chart_id=chart.chart_id, sub_question_ids=chart.sub_question_ids, record_id=record_id,
                    chart_type=chart.chart_type, fallback_chart=chart.fallback_chart, measure=op, select=select,
                    steps=steps, output=output, title=title,
                    fallback_charts=chart.fallback_charts or ([chart.fallback_chart] if chart.fallback_chart else []))

    # ── 질문용 ───────────────────────────────────────────────────
    def answer(self, n: int, d: AnswerDecision, charts: list[ChartRequest]) -> list[Step]:
        """질문용 계산 하나 → 단계 하나. 단, 피연산자 1개짜리 연산에 항목이 여럿이면 항목마다 단계 (a1-1, a1-2 …)

        [CHANGED] 이전: Step | None 을 돌려줬다 (항목이 여럿이면 첫 항목만 남았다)
        diff·ratio·combine 은 여러 피연산자를 한 단계에서 쓰므로 쪼개지 않는다.
        """
        tag = d.sub_question_id or f"a{n}"
        self.scope[tag] = (d.sub_question_id, None, d.op)
        self.withheld.discard(tag)       # [NEW 11-16] 보류는 계산 하나마다 따로 — 같은 하위 질문의 다른 답변까지 지우지 않는다 (검수 M3-04)
        # [NEW] 세트: 이 하위 질문이 속한 세트들. 세트 형식 입력(view_ids 가 하나라도 있음)에서 View 가 없는 세트뿐이면 계산하지 않는다
        sets = [c for c in charts if d.sub_question_id in c.sub_question_ids]
        expected = list(dict.fromkeys(v for c in sets for v in c.view_ids))
        if sets and not expected and any(c.view_ids for c in charts):
            why = "; ".join(dict.fromkeys(c.reason for c in sets if c.reason)) or "모듈 2 가 View 를 정하지 못함"
            self.note(tag, f"{why} → 질문용 계산을 만들지 않음")
            return []
        # [CHANGED 11-20] 이전: 분모 검사를 normalize 앞에서 했다 → 같은 View 의 총계 행으로 분모를 바꾸려면 분자의 최종 선택이 필요해 뒤로 옮겼다
        picks, d = self.normalize(tag, d.op, d.operands, d, fixed=self.fixed_for(tag, [d.sub_question_id]))
        if tag in self.withheld:
            return []
        d = self.sum_denominator(tag, d)                     # [NEW 11-25 D-2] 분모 'A + B' → 항목들의 합
        d = self.same_view_total(tag, picks, d, expected, self.fixed_for(tag, [d.sub_question_id])) or d
        if self.denominator_outside(tag, d, expected):
            return []
        if not picks:                             # answer_steps 는 피연산자를 항상 적는다 (명세 4장)
            self.note(tag, f"질문용 계산 {d.op} 에 피연산자가 없어 건너뜀")
            return []
        self.check_set(tag, expected, [p.record_id for p in picks])
        # 질문용 연산(HCX)과 모듈 2 의 measure(차트용)를 대조. 다른 것은 오류가 아니다 (차트는 추이, 답은 증감률일 수 있다)
        # → 둘 다 그대로 실행하고, 다르다는 사실만 QA 가 볼 수 있게 남긴다
        for c in charts:
            if c.chart_type and d.sub_question_id in c.sub_question_ids and c.measure != d.op:
                self.note(tag, f"질문용 연산 {d.op} ≠ 모듈 2 measure {c.measure} ({c.chart_id})")
        fixed = self.fixed_for(tag, [d.sub_question_id])
        groups = [picks] if d.op in MULTI_OPERAND else [[p] for p in picks]     # 단계 하나에 쓸 피연산자들
        steps = []
        for i, group in enumerate(groups, 1):
            op, args = d.op, d
            if op == "rank" and d.kind and (d.top_n or 1) <= 1:
                # [NEW 11-17] rank + kind (+ top_n 1) = '가장 ○○한 것'. rank 는 같은 시점 안에서만 순위를 매겨 '가장 적은 해' 를
                #   답하지 못하고, kind 도 읽지 않았다 (보고서 11.3 H1, 실제 HCX) → 최댓값 · 최솟값(extreme)
                self.note(tag, f"rank + kind={d.kind} → extreme (가장 ○○한 것 하나를 묻는 계산)")
                op, args = "extreme", d.model_copy(update={"top_n": None, "order": None})
            widened = self.widen_age_items(tag, group, fixed) if op == "raw" else None
            if widened == "withheld":
                return []
            if widened:                                      # 나이가 항목 열 값인 표 (F6)
                group, op, args = widened, "aggregate", d.model_copy(update={"agg": "sum"})
            elif op == "raw" and self.range_total(tag, group, fixed):
                self.note(tag, f"raw → aggregate(sum): 연령 {fixed[AGE][0]}~{fixed[AGE][1]}세 범위의 값 하나를 묻는 질문")
                op, args = "aggregate", d.model_copy(update={"agg": "sum"})
            steps.append(self.step(tag, f"a{n}" if len(groups) == 1 else f"a{n}-{i}", op, group, args)
                         .model_copy(update={"sub_question_id": d.sub_question_id}))
        self.answer_sub.update({st.step_id: d.sub_question_id for st in steps})
        return steps

    def fill_missing_answers(self, plans: list[Plan], answers: list[Step], asked: set[str | None], start: int) -> list[Step]:
        """[NEW 11-25] HCX 가 질문용 계산(answers)을 비운 하위 질문 → 그 차트의 단계를 질문용 단계로 복사한다 (체크리스트 1-9).
        저장된 실행 137건에서 수치를 묻는 질문은 100건 모두 answers 를 냈지만, '~를 그래프로 보여줘' 처럼 차트만 요청한 질문은
        37건 중 14건에서 HCX 가 answers 를 비웠다 → 질문용 계산이 0개라 모듈 6 이 '계산된 결과가 없어 수치 답변을 만들 수 없습니다' 를 냈다.
        - 채우는 경우: HCX 가 그 하위 질문에 대해 결정을 **하나도** 내지 않았고(asked 에 없음), 질문용 단계도 없을 때
          (결정을 냈는데 보류 · 생략된 경우는 이유가 있으므로 채우지 않는다)
        - 차트 하나가 하위 질문 둘 이상에 걸치면 어느 질문의 답인지 정할 수 없어 채우지 않는다 (notes 에만)
        - 앞 단계 결과를 받는 차트 단계(input)는 질문용으로 옮길 수 없어 그 차트는 채우지 않는다
        - 복사한 단계는 차트 단계와 같은 계산이라 reuse() 가 차트 결과에 연결한다 (다시 계산하지 않는다).
          피연산자를 생략한 차트 단계는 _Ctx.series · step_key 와 같은 모양(role value · 계획의 record_id · select)으로 적는다"""
        have = {self.answer_sub.get(a.step_id) for a in answers}
        out, n = [], start
        for pl in plans:
            subs = [s for s in pl.sub_question_ids if s]
            if not subs or any(s in have or s in asked for s in subs):
                continue
            if len(subs) > 1:
                self.note(pl.chart_id, f"HCX 가 질문용 계산을 비웠지만 차트가 하위 질문 {subs} 에 걸쳐 있어 채우지 않음")
                continue
            if any(st.input for st in pl.steps) or not pl.steps:
                self.note(pl.chart_id, "HCX 가 질문용 계산을 비웠지만 차트 단계가 앞 단계 결과를 받아 질문용으로 옮기지 않음")
                continue
            sid = subs[0]
            made = []
            for i, st in enumerate(pl.steps, 1):
                ops = st.operands or [Operand(role="value", record_id=pl.record_id, select=pl.select)]
                step_id = f"a{n}" if len(pl.steps) == 1 else f"a{n}-{i}"
                made.append(st.model_copy(update={"step_id": step_id, "operands": ops, "sub_question_id": sid}))
                self.answer_sub[step_id] = sid
            self.note(sid, f"HCX 가 질문용 계산을 비워 차트 계산 {', '.join(f'{pl.chart_id}.{st.step_id}' for st in pl.steps)} 을 "
                           f"질문용({', '.join(s.step_id for s in made)})으로 씀")
            have.add(sid)
            out += made
            n += 1
        return out

    def narrow_to_answered_item(self, plan: Plan, answers: list[Step]) -> Plan:
        """[NEW 11-18] 값 조회(raw) 차트가 View 의 항목을 전부 그리지 않고 질문이 묻는 항목만 그리게 한다 (F11, Q01).
        '2025년 서울 인구는?' 에 인구(천명) 옆에 조출생률 · 조사망률(인구천명당)이 한 막대그래프에 섞여 작은 막대가 보이지 않았다.
        build_charts 가 answer_steps 보다 먼저 돌아 차트 단계 안에서는 질문용 계산을 볼 수 없으므로, 두 계획이 모두 나온 **계획 단계에서** 차트의
        select 를 좁힌다 (계산 뒤에 행만 지우면 검증 · 축 · 계산 재사용이 어긋난다). 같은 하위 질문의 질문용 단계들이 같은 View 에서
        **하나의 같은 항목**만 쓸 때만 좁히고, 항목이 여럿이거나 차트가 항목을 이미 정했으면 그대로 둔다"""
        rec = self.records.get(plan.record_id)
        if plan.measure != "raw" or rec is None or ITEM_COL not in rec.table.columns or plan.select.get(ITEM_COL):
            return plan
        if any(s.operands for s in plan.steps):                  # 단계가 피연산자(항목)를 직접 정했다
            return plan
        ii = rec.table.columns.index(ITEM_COL)
        if len({str(r[ii]) for r in rec.table.rows}) < 2:
            return plan
        mine = {a.step_id for a in answers if self.answer_sub.get(a.step_id) in plan.sub_question_ids}
        items = set()
        for a in answers:
            if a.step_id not in mine:
                continue
            for o in a.operands or []:
                if o.record_id == plan.record_id:
                    items.add(o.item or "")
        if len(items) != 1 or "" in items:
            return plan
        item = next(iter(items))
        self.note(plan.chart_id, f"값 조회 차트를 질문이 묻는 항목 '{item}' 만 그리도록 좁힘 (View 항목 {len({str(r[ii]) for r in rec.table.rows})}개)")
        select = {**plan.select, ITEM_COL: [item]}
        # [NEW 11-18 검토 6] 항목을 좁히면 단위가 정해진다 (인구(천명)). 좁히기 전에 만든 표시 설정(단위 없음 · 배율 1)을 그대로 두면
        #   같은 값이 차트에서는 '9,340', 답변에서는 '934만 명' 으로 나온다 → 단계마다 표시 설정을 다시 확정한다
        unit = self.unit(plan.record_id, None, select)
        steps = [st.model_copy(update={"display_ref": self.ref(st.op, [unit], self.source_digits(st.op, [(plan.record_id, None, select)], unit, st.agg))})
                 if st.display_ref else st for st in plan.steps]
        return plan.model_copy(update={"select": select, "steps": steps})

    def final_conditions(self, plans: list[Plan], answers: list[Step]) -> tuple[list[Plan], list[Step]]:
        """[NEW 11-20] 계획이 확정된 뒤(narrow_to_answered_item 이후) 최종 선택이 조건식을 어기는 계획 · 단계를 뺀다 (KOS-26 A-2 ③)"""
        keep_plans, keep_answers = [], []
        for pl in plans:
            fixed = self.fixed_for(pl.chart_id, pl.sub_question_ids)
            refs = [(o.record_id, o.select, o.item) for st in pl.steps for o in (st.operands or [])]
            if any(not st.operands for st in pl.steps) or not pl.steps:
                refs.append((pl.record_id, pl.select, None))
            if bad := next((b for r, sel, it in refs if (b := self.violated_condition(r, sel, it, fixed))), None):
                self.withhold(pl.chart_id, f"확정한 선택이 조건 '{bad}' 을 만족하지 않음", f"'{bad}' 조건을 적용할 자료가 없어 계산하지 못했습니다.")
                continue
            keep_plans.append(pl)
        for st in answers:
            sid = st.sub_question_id
            fixed = self.fixed_for(sid or st.step_id, [sid])
            if bad := next((b for o in st.operands or [] if (b := self.violated_condition(o.record_id, o.select, o.item, fixed))), None):
                self.scope.setdefault(sid or st.step_id, (sid, None, st.op))
                self.withhold(sid or st.step_id, f"확정한 선택이 조건 '{bad}' 을 만족하지 않음", f"'{bad}' 조건을 적용할 자료가 없어 계산하지 못했습니다.")
                continue
            keep_answers.append(st)
        return keep_plans, keep_answers

    def reuse(self, plans: list[Plan], answers: list[Step]) -> dict[str, str]:
        """[NEW] 질문용 단계 중 같은 세트(하위 질문이 같은 차트)의 차트 단계와 같은 계산인 것 → {질문용 step_id: '{chart_id}.{step_id}'}.
        같은 계산 = 연산이 실제로 읽는 인자까지 같다 (calculate.USED_ARGS). 같은 지표인데 조건만 달라 숫자가 어긋날 수 있으면 notes 에 남긴다"""
        out: dict[str, str] = {}
        for a in answers:
            key, sid = step_key(a, None, self.records), self.answer_sub.get(a.step_id)
            if key is None or sid is None:
                continue
            near = None
            for p in plans:
                if sid not in p.sub_question_ids:
                    continue
                for c in p.steps:
                    if step_key(c, p, self.records) == key:
                        out[a.step_id] = f"{p.chart_id}.{c.step_id}"
                        break
                    if near is None and c.op == a.op and _what(c, p) == _what(a):
                        near = f"{p.chart_id}.{c.step_id}"
                if a.step_id in out:
                    break
            if a.step_id not in out and near:
                self.note(a.step_id, f"같은 세트의 차트 단계 {near} 와 같은 지표인데 조건이 달라 숫자가 다를 수 있음 (따로 계산)")
        return out


def _what(step: Step, default: Plan | None = None) -> list:
    """어떤 지표를 쓰는 단계인지: (View, 항목) 목록. 조건(select)은 보지 않는다"""
    if step.operands:
        return [(o.record_id, o.item) for o in step.operands]
    return [(default.record_id, None)] if default is not None else []


def make_plan(charts: list[ChartRequest], records: list[Record], decision: Decision,
              bundle: QueryBundle | None = None) -> tuple[ChartPlan, dict[str, Display]]:
    """→ (ChartPlan, displays). 모듈 2 가 차트 없음(chart_type None)으로 판단한 것은 plans 에 넣지 않는다"""
    p = _Planner(records, fixed_conditions(bundle))
    by_chart = {d.chart_id: d for d in decision.charts}
    plans = []
    for chart in charts:
        if chart.chart_type is None:
            continue
        if chart.chart_id not in by_chart:
            p.note(chart.chart_id, "계획 결정이 없어 차트 계획을 만들지 않음")
            continue
        if plan := p.plan(chart, by_chart[chart.chart_id]):
            plans.append(plan)
    merged = p.merge_answers(decision.answers)
    answers = [s for n, d in enumerate(merged, 1) for s in p.answer(n, d, charts)]
    # [NEW 11-25] HCX 가 비운 하위 질문의 질문용 계산을 차트 단계로 채운다 (1-9). 번호는 HCX 결정 다음부터
    answers += p.fill_missing_answers(plans, answers, {d.sub_question_id for d in merged}, len(merged) + 1)
    plans = [p.narrow_to_answered_item(pl, answers) for pl in plans]
    plans, answers = p.final_conditions(plans, answers)
    reuse = p.reuse(plans, answers)
    withheld = list({(w.sub_question_id, w.chart_id, w.text): w for w in p.withheld_list}.values())
    return ChartPlan(plans=plans, answer_steps=answers, answer_reuse=reuse, notes=list(dict.fromkeys(p.notes)),
                     warnings=list(dict.fromkeys(p.warnings)), withheld=withheld), p.displays
