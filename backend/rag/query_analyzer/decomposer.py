"""[NEW] 구조안의 decomposer.py — 복합 질문 → sub_questions 분해 진입점

현재 분해는 HCX 슬롯 추출 1회 안에서 함께 한다 (slots.py SLOT_SYS 의 [하위 질문 규칙], 출력 sub_questions).
검증은 validate.py, 문장화는 sentence.build_sentences 의 sub_questions.
"""
from .slots import SLOT_SCHEMA, SLOT_SYS, call_slots  # noqa: F401
from .validate import validate_slots  # noqa: F401


def decompose(question, today=None):
    """질문 → (하위 질문 문장 목록, 하위 슬롯 목록). rewrite_query 와 같은 HCX 1회 호출 결과에서 하위 부분만"""
    from .bundle import rewrite_query
    b = rewrite_query(question, today)
    return b.sub_questions, b.sub_filters or []
