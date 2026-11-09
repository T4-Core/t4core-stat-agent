"""[NEW v4] 쿼리 모듈 v4 — v3(재작성·슬롯) 위에 CSV 값 사전 기반 단계를 더함

  lexicon.py      1-2 동의어·유사어 조회 계층 (rule_dict > CSV 값 사전 > term_dict > 학습 사전)
  grounding.py    1-3 슬롯 값 → CSV 값·표 접지
  clarify.py      1-4 필수 슬롯(시점·지역·대상) 확인 · 시점 규칙 · 되묻기 후보 · 선택 반영
  decompose.py    1-5 표 단위 서브쿼리 분리
  search_text.py  1-1 검색용 문장 (v3 문장 + CSV 표준 이름 / LLM)
  pipeline.py     analyze() — 위 단계를 순서대로, StepTrace 기록

  from backend.rag.query_analyzer.v4 import analyze
  a = analyze("2025년 대전 출생아 수와 사망자 수 차이")
  a["status"], a["view_bundle"], a["clarifications"], a["trace"]
"""
from backend.rag.query_analyzer.v4.pipeline import analyze, canonical_slots, rewrite_v3

__all__ = ["analyze", "canonical_slots", "rewrite_v3"]
