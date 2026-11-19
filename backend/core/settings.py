"""
파이프라인 설정 — configs/pipeline.yaml (또는 환경변수 PIPELINE_CONFIG) → Settings

  from backend.core.settings import get_settings, with_overrides
  s = get_settings()                          # 파일에서 한 번 읽어 캐시
  s2 = with_overrides({"base_year": 2025})    # 일부만 바꾼 설정 (API 요청의 overrides 와 같은 방법)

검색 채널 가중치·계수는 configs/search.yaml (backend/rag/search/engine.py)
"""
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    # 필수 슬롯·시점 규칙
    required_slots: list[str] = Field(default_factory=lambda: ["시점", "지역", "대상"])
    base_year: int = 2026
    base_year_mode: str = "data"                 # data = CSV 값 사전의 최신 연도 / fixed = base_year
    trend_years: int = 5
    recent_words: list[str] = Field(default_factory=lambda: ["최근", "요즘", "현재", "지금", "근래", "요새"])
    trend_words: list[str] = Field(default_factory=lambda: ["추이", "변화", "흐름", "추세", "동향", "변동"])
    trend_intents: list[str] = Field(default_factory=lambda: ["추이"])
    n_options: int = 20
    clarify_mode: str = "soft"                   # soft = 없는 시점=최신·지역=전국으로 진행 / strict = needs_clarification
    # 동의어·CSV 값 사전
    csv_scope: str = "selected"
    min_alias_len: int = 2
    fuzzy_cutoff: float = 0.72
    contain_min_len: int = 2
    # 검색 문장
    search_text_mode: str = "rule"               # rule = 재작성 문장 + CSV 표준 이름 / llm = HCX 로 한 번 더
    question_terms: bool = True
    question_terms_max_share: float = 0.15
    question_terms_max: int = 6
    role_units: bool = True
    # 서브쿼리
    split_when_no_common_table: bool = True
    split_policy: str = "always"                 # always / no_common_table
    max_sub_queries: int = 4
    # View 묶음 · Point 충돌 · 선택
    view_top_k: int = 10
    view_n_views: int = 3
    view_keep_unusable: bool = True
    view_main_with_subs: bool = False
    view_first_only_when_same: bool = False      # View 2개의 겹치는 교차점 값이 모두 같고 2순위에만 있는 교차점이 없으면 1순위만
    view_stitch: bool = False                    # 검색 결과의 stitch(같은 통계의 다른 연도 표)로 View 를 더 만들어 함께 넘김
    conflict_indicator_core: bool = True         # 지표가 '표 이름에만 있음' 이면 핵심어('혼인건수' → '혼인')로 항목을 다시 확인
    conflict_rel_tol: float = 0.0
    conflict_abs_tol: float = 1e-9
    conflict_allow_partial: list[str] = Field(default_factory=lambda: ["시점"])
    conflict_preview_points: int = 6
    conflict_max_footnotes: int = 8
    selection_ttl_hours: int = 168
    # 기록
    save_runs: bool = False

    def trend_range(self):
        return list(range(self.base_year - self.trend_years + 1, self.base_year + 1))


ENV_OVERRIDES = {"PIPELINE_CLARIFY_MODE": "clarify_mode", "PIPELINE_BASE_YEAR_MODE": "base_year_mode"}


def config_path():
    from backend.core.config import CONFIGS_DIR
    return Path(os.getenv("PIPELINE_CONFIG") or CONFIGS_DIR / "pipeline.yaml")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    p = config_path()
    data = {}
    if p.exists():
        import yaml
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    for env, key in ENV_OVERRIDES.items():
        if os.getenv(env):
            data[key] = os.environ[env]
    return Settings(**data)


def with_overrides(overrides=None) -> Settings:
    s = get_settings()
    return s.model_copy(update=dict(overrides)) if overrides else s
