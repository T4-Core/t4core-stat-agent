"""
[NEW v4] 쿼리 모듈 v4 설정 — configs/query_v4.yaml (또는 QUERY_V4_CONFIG) → QueryV4Settings

  from backend.core.settings_v4 import get_settings
  s = get_settings()                       # 파일에서 읽음 (한 번만, 캐시)
  s2 = s.model_copy(update={"base_year": 2025})   # 실험: 값 하나만 바꾼 설정 (API 요청의 overrides 와 같은 방법)
"""
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class QueryV4Settings(BaseModel):
    required_slots: list[str] = Field(default_factory=lambda: ["시점", "지역", "대상"])
    base_year: int = 2026
    # [NEW 11-16] '최근·요즘' 의 기준 해. fixed = base_year 그대로 / data = CSV 값 사전의 최신 연도 (csv_index.latest_year)
    #   이전: 2026 고정 → 자료가 2025 까지인 표가 '시점 없음' 으로 깎이고 View 가 대체 연도로 잘림
    base_year_mode: str = "fixed"
    trend_years: int = 5
    recent_words: list[str] = Field(default_factory=lambda: ["최근", "요즘", "현재", "지금", "근래", "요새"])
    trend_words: list[str] = Field(default_factory=lambda: ["추이", "변화", "흐름", "추세", "동향", "변동"])
    trend_intents: list[str] = Field(default_factory=lambda: ["추이"])
    n_options: int = 20
    csv_scope: str = "selected"
    min_alias_len: int = 2
    fuzzy_cutoff: float = 0.72
    contain_min_len: int = 2
    search_text_mode: str = "v3"
    split_when_no_common_table: bool = True
    # [NEW 11-12] 1-5 분리 정책: no_common_table = 지표들을 함께 가진 표가 없을 때만 나눔 (예전 동작)
    #                           always          = 함께 가진 표가 있어도 지표(개념)마다 나눔 → 같은 표에서도 지표별 View
    split_policy: str = "no_common_table"
    max_sub_queries: int = 4
    # [NEW 11-13] 질문 원문의 CSV 표현 보충 (lexicon.question_terms): 슬롯에 없는 '표를 가르는 말'을 검색 문장·View 보조 단어로
    # [NEW 11-13] 되묻기·범위 밖·분석 실패 처리
    #   strict = 필수 슬롯이 없으면 needs_clarification 으로 멈춤 (예전 동작)
    #   soft   = 멈추지 않음: 없는 시점은 최신, 없는 지역은 전국으로 두고 검색·View 를 진행. 되묻기 후보는 clarifications 에 그대로 남김
    #            HCX 실패·오류는 코드 추출 값으로, '범위 밖' 판정도 질문에 통계 용어가 있으면 뒤집음
    clarify_mode: str = "strict"
    question_terms: bool = True
    # [NEW 11-16] (P2) 역할 분해: 원문의 '…중 비율'·'…로 나눈'·'천 명당'(분모), '…가 N명 이상'(조건) 을 검색 단위로 더함
    role_units: bool = True
    question_terms_max_share: float = 0.15       # 전체 표 중 이 비율 이하에만 나오는 표현만 (흔한 말 제외)
    question_terms_max: int = 6
    save_runs: bool = False
    # [Step 4] View 묶음 · Point 충돌 · 선택
    view_top_k: int = 10
    view_n_views: int = 3
    view_retrieval_config: str | None = None
    view_keep_unusable: bool = True
    view_main_with_subs: bool = False
    conflict_rel_tol: float = 0.0
    conflict_abs_tol: float = 1e-9
    conflict_allow_partial: list[str] = Field(default_factory=lambda: ["시점"])
    conflict_preview_points: int = 6
    conflict_max_footnotes: int = 8
    selection_ttl_hours: int = 168

    def trend_range(self):
        return list(range(self.base_year - self.trend_years + 1, self.base_year + 1))


def config_path():
    from backend.core.config import CONFIGS_DIR
    return Path(os.getenv("QUERY_V4_CONFIG") or CONFIGS_DIR / "query_v4.yaml")


@lru_cache(maxsize=1)
def get_settings() -> QueryV4Settings:
    p = config_path()
    if p.exists():
        import yaml
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    else:
        data = {}
    if os.getenv("QUERY_V4_CLARIFY_MODE"):                  # [NEW 11-13] 실행 환경에서 한 값만 바꾸기 (테스트는 strict)
        data["clarify_mode"] = os.environ["QUERY_V4_CLARIFY_MODE"]
    if os.getenv("QUERY_V4_BASE_YEAR_MODE"):                # [NEW 11-16] 테스트는 fixed (시나리오가 2026 기준으로 쓰였음)
        data["base_year_mode"] = os.environ["QUERY_V4_BASE_YEAR_MODE"]
    return QueryV4Settings(**data)


def with_overrides(overrides=None) -> QueryV4Settings:
    """요청마다 일부 값만 바꾼 설정 (API overrides, 노트북 실험)"""
    s = get_settings()
    return s.model_copy(update=dict(overrides)) if overrides else s
