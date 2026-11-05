"""
[NEW] 판단(Judge) 모듈 — "받은 View 가 질문 조건을 실제로 담았는가" 를 슬롯 단위로 판정

  흐름 (실시간, 질문마다 1번)
    tool_rewrite ─▶ view_bundle + adapter notes
    tool_views   ─▶ ViewResult
                       │
                       ▼
             judge(JudgeRequest) ─▶ JudgeResult ─▶ 오케스트레이터 (pass 면 답변, 아니면 reasons 를 보고 결정)

  판정 단위 (작은 것 → 큰 것)
    SlotCheck   슬롯 하나       예) 이 View 의 '시점' 은 요청과 맞는가
    RecordJudge View 하나       슬롯 판정들을 모아 점수
    UnitJudge   검색 단위 하나  (상위 질의 또는 서브질문) 가장 잘 맞는 View 의 점수
    JudgeResult 질문 전체       단위들을 config.unit_aggregate 규칙으로 합침

    실제 판정 로직은 backend/rag/judge/*.py 에 있다. 이 파일은 입력/출력 스키마 정의만 한다.
    통과 기준은 아직 팀에서 정하는 중이라 코드에 고정하지 않고 JudgeConfig 로 뺐다 (기본값은 임시값).
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.schemas.query import QueryBundle   # 질의 모듈 → View 모듈 입력 (view_bundle)
from backend.schemas.view import ViewResult     # View 모듈 출력 (단위별 Record + notes).


class SlotStatus(str, Enum):
    """슬롯 하나의 판정 결과"""
    match = "match"                   # 요청한 조건이 View 에 모두 있다
    partial = "partial"               # 일부만 있거나, 비슷한 값으로 대체되었다 (예: 2024 요청 → 최신 2023 사용)
    missing = "missing"               # 요청했는데 View 에 없다 (예: 20대를 물었는데 연령 분류가 없는 표)
    unsupported = "unsupported"       # View 단계 이전(재작성·변환)에서 이미 빠졌다 (예: 국적, 전출지)
    not_requested = "not_requested"   # 사용자가 묻지 않은 슬롯 → 점수 계산에서 뺀다
    unknown = "unknown"               # 판단할 근거가 없다 (예: 표 열의 종류를 알 수 없음)


class SlotTier(str, Enum):
    """슬롯의 중요도 등급 — 빠졌을 때 얼마나 치명적인가"""
    core = "core"     # 빠지면 '다른 숫자'를 답하게 됨 (지표·대상·지역·시점)
    minor = "minor"   # 빠지면 '범위가 넓은 숫자'를 답하게 됨 (성별·연령)
    shape = "shape"   # 값은 맞지만 모양이 다름 (의도: 추이를 물었는데 한 시점만)


class Verdict(str, Enum):
    """최종 판정 3단계 (eval/pipeline_review 의 PASS/PARTIAL/FAIL 과 같은 단계, 소문자)"""
    pass_ = "pass"        # 'pass' 는 파이썬 예약어라 이름 뒤에 _ 를 붙였다. JSON 값은 "pass" 그대로
    partial = "partial"
    fail = "fail"


class ReasonCode(str, Enum):
    """오케스트레이터가 '다음에 무엇을 할지' 고를 때 쓰는 사유 코드.
    평가 모듈은 사유만 알려 주고, 재검색·재작성 여부는 오케스트레이터가 정한다."""
    no_views = "no_views"                             # 단위에 View 가 하나도 없음            → 재검색
    empty_view = "empty_view"                         # View 는 있으나 값이 0개               → 재검색
    core_slot_missing = "core_slot_missing"           # 핵심 슬롯(지표·지역·시점 …) 없음      → 재검색 또는 "자료 없음"
    slot_substituted = "slot_substituted"             # 요청과 다른 값으로 대체됨             → 주의 문구 붙여 답변
    slot_dropped_upstream = "slot_dropped_upstream"   # 재작성·변환 단계에서 조건이 빠짐      → 재작성 재시도 또는 한계 안내
    intent_mismatch = "intent_mismatch"               # 추이를 물었는데 시점이 1개뿐 등       → 조건 조정 후 재검색


def _default_slot_tiers() -> dict[str, SlotTier]:
    return {
        "지표": SlotTier.core, "대상": SlotTier.core, "지역": SlotTier.core, "시점": SlotTier.core,
        "성별": SlotTier.minor, "연령": SlotTier.minor,
        "의도": SlotTier.shape,
    }


def _default_tier_weights() -> dict[SlotTier, float]:
    return {SlotTier.core: 1.0, SlotTier.minor: 0.5, SlotTier.shape: 0.5}


def _default_status_score() -> dict[SlotStatus, float]:
    return {SlotStatus.match: 1.0, SlotStatus.partial: 0.5, SlotStatus.missing: 0.0,
            SlotStatus.unsupported: 0.0, SlotStatus.unknown: 0.5}


class JudgeConfig(BaseModel):
    """통과 기준. 팀에서 아직 정하는 중이라 전부 설정값으로 뺐다 (기본값 = 임시값).
    나중에 eval/pipeline_review 평가셋으로 여러 설정을 돌려 비교한 뒤 확정한다."""
    slot_tiers: dict[str, SlotTier] = Field(
        default_factory=_default_slot_tiers,
        description="슬롯 이름 → 중요도 등급. 여기에 없는 슬롯은 판정만 하고 점수에는 넣지 않음")
    tier_weights: dict[SlotTier, float] = Field(
        default_factory=_default_tier_weights, description="등급 → 가중 치")
    status_score: dict[SlotStatus, float] = Field(
        default_factory=_default_status_score, description="슬롯 상태 → 점수 (0~1)")
    core_missing_is_fail: bool = Field(
        True, description="core 슬롯이 하나라도 missing 이면 점수와 관계없이 그 View 는 fail")
    substitution_as: SlotStatus = Field(
        SlotStatus.partial, description="대체값(최신 연도 사용 등)을 어떤 상태로 볼지. 엄격하게 하려면 missing")
    unit_aggregate: Literal["all", "any", "mean"] = Field(
        "all", description="단위(상위 질의·서브질문) 판정을 합치는 규칙. "
                           "all = 모든 단위 통과해야 통과 / any = 하나만 통과해도 / mean = 점수 평균")
    pass_threshold: float = Field(0.8, ge=0.0, le=1.0, description="이 점수 이상이면 pass")
    partial_threshold: float = Field(0.5, ge=0.0, le=1.0, description="이 점수 이상이면 partial, 미만이면 fail")
    upstream_tier: SlotTier | None = Field(
        SlotTier.minor, description="재작성·변환 단계에서 빠진 슬롯(국적·전출지 등, slot_tiers 에 없는 것)을 점수에 넣을 등급. "
                                    "None 이면 점수에는 넣지 않고 reason(slot_dropped_upstream)만 남김")

    # 필드 하나씩은 Field(ge=, le=) 로 검사하고, 두 필드의 관계는 여기서 검사한다.
    # mode="after" = 필드별 검사가 모두 끝난 '완성된 객체' 를 받아서 검사한다.
    @model_validator(mode="after")
    def _check_thresholds(self):
        if self.partial_threshold > self.pass_threshold:
            raise ValueError(f"partial_threshold({self.partial_threshold}) 는 "
                             f"pass_threshold({self.pass_threshold}) 이하여야 합니다")
        return self



# Swagger 예시: "작년 대구 남자 20대 인구 수" 에 연령 분류가 없는 View 가 온 경우 ([P1] 사례) + 국적 변환 메모
#   Try it out → Execute 만 누르면 → partial (연령 missing · 시점 대체 · 국적 unsupported, 점수 0.75)
_EX_FILTERS = {"시점": [2025], "지역": ["대구광역시"], "성별": ["남자"], "연령": {"from": 20, "to": 29},
               "지표": ["인구수"], "대상": ["인구"], "의도": "값 조회"}
EX_JUDGE_REQUEST = {
    "bundle": {"query_id": "1", "original": "작년 대구의 남자 20대 인구 수", "filters": _EX_FILTERS},
    "views": {
        "query_id": "1", "original": "작년 대구의 남자 20대 인구 수", "filters": _EX_FILTERS,
        "units": [{
            "unit_id": "main", "query": "2025년 대구광역시 남자 20~29세 인구수", "filters": _EX_FILTERS,
            "candidates": [], "notes": [],
            "views": [{
                "rank": 1, "tbl_id": "DT_1B04005N",
                "notes": ["요청 시점이 모두 없어 최신 2024 사용"],
                "record": {
                    "id": "view::101_DT_1B04005N::Y::1-1::value", "parent_id": "table::101_DT_1B04005N",
                    "lexical_text": "행정구역별 성별 인구 주민등록인구현황 대구광역시 남자 총인구 명",
                    "table": {"columns": ["시점", "행정구역(시도)별", "성별", "항목", "값"],
                              "rows": [["2024", "대구광역시", "남자", "총인구", 1170000]]},
                    "metadata": {"prd_se": "Y", "view_type": "value", "prd_from": "2024", "prd_to": "2024"},
                    "source": {"tbl_id": "DT_1B04005N", "prd_se": "Y"},
                },
            }],
        }],
    },
    "upstream_notes": ["[국적] ['한국'] — View 모듈에 아직 없는 슬롯 (검색 문장에는 들어 있음)"],
}


class JudgeRequest(BaseModel):
    # json_schema_extra 의 examples 가 Swagger 의 'Example Value' 로 그대로 채워진다 (schemas/query.py 와 같은 방식)
    model_config = ConfigDict(json_schema_extra={"examples": [EX_JUDGE_REQUEST]})
    bundle: QueryBundle = Field(..., description="view_bundle (query-rewrite 응답의 view_bundle 그대로)")
    views: ViewResult = Field(..., description="View 모듈 상세 결과 (/api/v1/rag/views/detail 응답 그대로). "
                                               "단위별 슬롯(units[].filters)과 Record 를 짝지어 판정한다")
    upstream_notes: list[str] = Field(
        default_factory=list,
        description="재작성 → View 입력 변환(adapter) 중 버리거나 바꾼 조건 메모 (query-rewrite 응답의 notes). "
                    "'[국적] … View 모듈에 아직 없는 슬롯' 처럼 [슬롯] 태그가 붙어 있어 unsupported 판정에 쓴다")
    config: JudgeConfig | None = Field(None, description="통과 기준. 비우면 JudgeConfig 기본값")



class SlotCheck(BaseModel):
    """슬롯 하나의 판정 + 근거. 오케스트레이터·답변 단계가 '무엇이 왜 틀렸는지' 를 그대로 보여줄 수 있게"""
    status: SlotStatus
    requested: Any = Field(None, description="요청값 (예: [2024], ['대구광역시'], {'from': 20, 'to': 29})")
    found: Any = Field(None, description="View 에 실제로 담긴 값 (예: ['2023'])")
    evidence: str = Field("", description="사람이 읽는 근거 (예: '요청 2024 → 표 최신 2023 사용')")
    reason: ReasonCode | None = Field(
        None, description="이 슬롯이 만든 사유 코드 (예: 대체 → slot_substituted, 의도 불일치 → intent_mismatch). "
                          "status 만으로는 '대체' 와 '일부만 있음' 이 둘 다 partial 이라 구별되지 않아서 따로 둔다")


class RecordJudge(BaseModel):
    """View(Record) 하나의 판정"""
    record_id: str
    tbl_id: str
    verdict: Verdict
    score: float = Field(..., ge=0.0, le=1.0, description="요청된 슬롯의 status_score × tier_weight 가중 평균")
    slots: dict[str, SlotCheck] = Field(default_factory=dict, description="슬롯 이름 → 판정")
    reasons: list[ReasonCode] = Field(default_factory=list)


class UnitJudge(BaseModel):
    """검색 단위 하나 (상위 질의 'main' 또는 서브질문) 의 판정"""
    unit_id: str = Field(..., description="ViewResult.units[].unit_id 와 같음")
    query: str
    verdict: Verdict
    score: float = Field(..., ge=0.0, le=1.0, description="이 단위에서 가장 잘 맞는 View 의 점수 (View 하나로도 답할 수 있으므로)")
    best_record_id: str | None = Field(None, description="가장 잘 맞는 View. View 가 없으면 None")
    records: list[RecordJudge] = Field(default_factory=list)
    reasons: list[ReasonCode] = Field(default_factory=list)


class JudgeResult(BaseModel):
    """판단 모듈 출력 → 오케스트레이터"""
    query_id: str
    verdict: Verdict
    score: float = Field(..., ge=0.0, le=1.0)
    reasons: list[ReasonCode] = Field(default_factory=list, description="모든 단위의 사유를 중복 없이 모은 것")
    units: list[UnitJudge] = Field(default_factory=list)
    config_used: JudgeConfig = Field(..., description="이 판정에 쓴 기준 (나중에 기준을 바꿔도 결과를 재현할 수 있게 기록)")
