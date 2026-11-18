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
    save_runs: bool = False
    # [Step 4] View 묶음 · Point 충돌 · 선택
    view_top_k: int = 10
    view_n_views: int = 2               # [CHANGED 11-18] 3 → 2: 검색 1·2순위로 View
    # [CHANGED 11-18] None(예전 순차 table_search) → hybrid_all (table_card_search 하이브리드: 조건표 거르기 → BM25·dense RRF)
    view_retrieval_config: str | None = "hybrid_all"
    # [NEW 11-18] 두 View 가 겹치는 교차점 값이 모두 같고 2순위에만 있는 교차점이 없으면 1순위만 넘김
    #   값이 다르면 둘 다 + 사용자 선택(기존), 겹치는 교차점이 없으면(비교 불가) 둘 다
    view_first_only_when_same: bool = True
    # [NEW 11-18] 기간 이어붙이기: 검색 결과의 stitch(같은 통계의 다른 연도 표)를 읽어 그 표가 맡은 연도로 View 를 더 만듦
    #   이어붙인 View 는 비교(선택) 대상이 아님. 끝내 없는 연도는 메모로
    view_stitch: bool = True
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
        return QueryV4Settings(**data)
    return QueryV4Settings()


def with_overrides(overrides=None) -> QueryV4Settings:
    """요청마다 일부 값만 바꾼 설정 (API overrides, 노트북 실험)"""
    s = get_settings()
    return s.model_copy(update=dict(overrides)) if overrides else s
