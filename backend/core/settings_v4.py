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
    max_sub_queries: int = 4
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
        return QueryV4Settings(**data)
    return QueryV4Settings()


def with_overrides(overrides=None) -> QueryV4Settings:
    """요청마다 일부 값만 바꾼 설정 (API overrides, 노트북 실험)"""
    s = get_settings()
    return s.model_copy(update=dict(overrides)) if overrides else s
