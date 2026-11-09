"""[NEW v4] Part 2-2·2-3 — 서브쿼리별 View 묶음 · Point 충돌 판정 · 선택 (docs/query_retrieval_v4/VIEW_CONFLICT.md)

  points.py     Record → Point (교차점 key + 기본 단위 값)
  conflict.py   필수 메타 사용 확인(judge 슬롯 판정) + 같은 key 값 비교 → ok / ambiguous / partial / empty
  selection.py  선택지 서명 토큰 발급·검증 + 선택 반영 (서버 세션 없음)
  viewset.py    build_viewset(질문 | QueryAnalysis | view_bundle) → 단위별 View + 충돌 + records / pending
  __main__.py   CLI: python -m backend.rag.view "질문"  (되묻기·선택을 터미널에서)
"""
from backend.rag.view.conflict import detect, view_usage
from backend.rag.view.points import record_points
from backend.rag.view.selection import resolve, verify
from backend.rag.view.viewset import apply_selections, build_viewset

__all__ = ["build_viewset", "apply_selections", "detect", "view_usage", "record_points", "resolve", "verify"]
