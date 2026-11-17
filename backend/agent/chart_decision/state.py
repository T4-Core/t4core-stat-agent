"""Generator State (노드 간 공유 데이터)"""
import operator
from typing import Annotated, Optional, TypedDict


class GeneratorState(TypedDict, total=False):
    scenario: str                               # 입력: 시나리오 이름 (비우면 기본 시나리오)
    query_bundle: dict                          # 입력: 질의 변환 결과
    view_input: dict                            # 입력: 검색 결과
    use_llm: bool                               # 2번 모듈에서 LLM을 쓸지 (기본 True)
    chart_plan: Optional[dict]                  # 2번 출력: {"query_id", "charts": [...]}
    filtered_views: list                        # 2번 출력: 하위질문별로 걸러진 View
    errors: Annotated[list, operator.add]       # 노드마다 이어 붙임
