"""
모듈 5 공통 정의 — 상태 코드 · 차트 유형 15종 · 유형별 약속(입력 계약) · DrawJob · DrawResult · 경로

  입력 스키마는 15종 모두 ChartContent(backend/schemas/chart.py) 하나다.
  유형마다 다른 것은 encoding 역할 · 행 모양 · options뿐이고, 이를 '유형별 약속'으로 둔다.
    - 필수/선택 역할, 행 모양(long/joined), 음수 불가 역할, y 기준선(y_floor) → 모듈 3 SPECS 그대로
    - 숫자여야 하는 역할 → 모듈 5의 NUMERIC_ROLES
    - 그 밖의 유형별 약속 → EXTRA_RULES
  draw_chart_tool.precheck가 이 약속을 확인한다.
"""
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from backend.agent.chart_calculate.specs import SPECS
from backend.schemas.chart import ChartContent

# ── 경로 ─────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent      # backend/agent/draw_chart (이 패키지의 한 단계 위)
# [시나리오] 시나리오 데이터 경로 — 모듈 2·3 연결에서는 쓰지 않아 주석 처리
# DATA_DIR = BASE_DIR / "data"                         # 시나리오 데이터: data/{query_id}/*.json
OUTPUT_ROOT = BASE_DIR / "output"                      # 기본 저장 위치: backend/agent/draw_chart/output/{query_id}/ (run_module5의 out_dir로 바꿀 수 있다)

# ── 상태 코드 ─────────────────────────────────────
DRAWN, NOT_IMPLEMENTED, SKIPPED, FAILED = "drawn", "not_implemented", "skipped", "failed"
READY = "ready"   # 준비 단계에서만 쓰는 값: 그리기로 넘길 job (draw_chart에서 drawn / not_implemented / failed로 정해진다)

# ── 차트 유형 15종 ─────────────────────────────────
# 모듈 3이 구성·검증에 쓰는 표(backend/agent/chart_calculate/specs.py)를 그대로 쓴다 → 필수 역할 기준이 모듈 3과 같다
CHART_TYPES = list(SPECS)

# ── 유형별 약속 (입력 계약) ─────────────────────────
NUMERIC_ROLES = {  # 숫자여야 하는 역할
    "line": ("y",), "area": ("y",), "bar": ("y",), "stacked_bar": ("y",), "combo": ("y", "y2"),
    "pyramid": ("value",), "pie": ("value",), "donut": ("value",), "treemap": ("value",),
    "radar": ("value",), "map": ("value",), "heatmap": ("value",),
    "scatter": ("x", "y"), "bubble": ("x", "y", "size"), "dumbbell": ("start", "end"),
}
EXTRA_RULES = {  # SPECS·NUMERIC_ROLES 밖의 유형별 약속 (precheck에서 확인)
    "pyramid": "group 값 2개",
}
assert set(NUMERIC_ROLES) == set(CHART_TYPES), "NUMERIC_ROLES가 15종과 맞지 않음"
ROWS_NAME = {"long": "long [분류…, 항목, 값]", "joined": "joined [키…, 지표…]"}


def contract_table() -> pd.DataFrame:
    """유형별 약속 표 (README · 렌더러 docstring과 같은 내용)"""
    return pd.DataFrame([{
        "chart_type": t, "이름": s.name,
        "필수 역할": ", ".join(s.required), "선택 역할": ", ".join(s.optional),
        "행 모양": ROWS_NAME[s.rows], "숫자 역할": ", ".join(NUMERIC_ROLES[t]),
        "음수 불가": ", ".join(s.non_negative), "y 기준선": s.y_floor or "", "추가": EXTRA_RULES.get(t, ""),
    } for t, s in SPECS.items()])


# ── DrawJob · DrawResult ──────────────────────────
@dataclass
class DrawJob:
    """차트 하나를 그리는 데 필요한 것만 모은 묶음 (draw_chart의 입력)"""
    chart_id: str
    sub_question_ids: list = field(default_factory=list)
    planned_type: str | None = None     # 모듈 2 계획 유형
    chart_type: str | None = None       # 최종 유형 (ChartContent 기준)
    content: ChartContent | None = None
    displays: dict = field(default_factory=dict)       # 이 차트가 쓰는 display_ref만 {ref: Display}
    display_refs: list = field(default_factory=list)   # 이 차트가 가리키는 display_ref 전부 (없는 ref 확인용)
    source_links: list = field(default_factory=list)   # [{label, url}]
    status: str = READY                 # READY / SKIPPED / FAILED
    reason: str | None = None           # SKIPPED / FAILED 이유
    warnings: list = field(default_factory=list)


@dataclass
class DrawResult:
    """draw_chart의 출력. figure는 메모리에만 두고, 파일 저장은 save 노드(fan-in)에서 한다"""
    chart_id: str
    chart_type: str | None
    status: str
    planned_type: str | None = None
    sub_question_ids: list = field(default_factory=list)
    title: str | None = None
    reason: str | None = None           # NOT_IMPLEMENTED / SKIPPED / FAILED 이유
    figure: go.Figure | None = None
    files: dict = field(default_factory=dict)    # save 노드에서 채운다 {json, png, html}
    warnings: list = field(default_factory=list)
