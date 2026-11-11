"""2번 차트 유형 판단 서브그래프 State

- 입력·출력 키는 바깥 Generator State와 같은 이름을 쓴다 (서브그래프를 노드 하나로 넣을 수 있게).
- matches, charts는 서브그래프 안에서만 쓰는 중간 키다 (출력 스키마에 없어서 밖으로 나가지 않는다).
"""
import operator
from typing import Annotated, Optional, TypedDict


class ChartDecisionInput(TypedDict, total=False):
    scenario: str                               # 시나리오 이름 (예: "27077dec") → input_data/<이름>/ 에서 불러옴
    query_bundle: dict                          # 질의 변환 결과 (비우면 시나리오에서 불러옴)
    view_input: dict                            # 검색 결과 (unit별 View, 비우면 시나리오에서 불러옴)
    use_llm: bool                               # False면 LLM 노드에서도 LLM을 부르지 않음 (기본 True)


class ChartDecisionOutput(TypedDict, total=False):
    chart_plan: Optional[dict]                  # {"query_id", "charts": [...]}
    filtered_views: list                        # 하위질문별로 걸러진 View (3번 계산 모듈로)
    errors: Annotated[list, operator.add]       # 노드마다 이어 붙임


class ChartDecisionState(ChartDecisionInput, ChartDecisionOutput, total=False):
    matches: list                               # 하위질문별 작업 묶음 (match → filter → measure → profile)
    charts: list                                # 차트별 중간 결과 (chart_select → requirements → reason)
    input_source: str                           # load_input이 입력을 어디서 가져왔는지
