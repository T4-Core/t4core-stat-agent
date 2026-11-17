"""재작성 — 질문 → (HCX 슬롯 추출 → 검증 → 문장) → RewriteBundle. HCX 1회

  run_pipeline(question, today) → {"slot": HCX 결과, "valid": 검증 결과, "sentences": 문장, "bundle": RewriteBundle}
"""
from dataclasses import dataclass, field

from .sentence import build_sentences, slots_to_sentence
from .slots import call_slots
from .validate import validate_slots


@dataclass
class RewriteBundle:
    original: str  # 사용자 원 질문
    rewritten: str  # 재작성된 질문 (슬롯 → 문장)
    sub_questions: list[str] = field(default_factory=list)  # 복합 질문을 나눈 하위 질문
    intent: str | None = None  # 원 질문의 의도 하나 (9종 중)
    filters: dict[str, list[str]] | None = None  # 값 있는 슬롯만, 의도 제외
    sub_filters: list[dict] | None = None  # 하위 질문 슬롯 (sub_questions 와 순서 같음)


def _intent_one(v):
    """의도 → 문자열 하나 (검증 슬롯의 의도는 목록이라 첫 번째 값)"""
    if isinstance(v, str):
        return v or None
    return next(iter(v or []), None)


def to_filters(slots):
    """검증된 슬롯 → filters (값 있는 슬롯만, 의도 제외). 모두 비면 None"""
    f = {k: list(v) for k, v in (slots or {}).items() if k != "의도" and v}
    return f or None


def make_bundle(question, valid, sentences):
    """검증 결과 + 문장 → RewriteBundle. rewritten 이 비면 원 질문.
    하위 질문 문장과 하위 슬롯은 같은 순서 (문장이 빈 하위 슬롯은 함께 뺌)"""
    pairs = [(slots_to_sentence(s), s) for s in valid.get("sub_slots", [])]
    pairs = [(txt, s) for txt, s in pairs if txt]
    return RewriteBundle(
        original=question,
        rewritten=sentences["rewritten"] or question,
        sub_questions=[txt for txt, _ in pairs],
        intent=_intent_one(valid["slots"].get("의도")),
        filters=to_filters(valid["slots"]),
        sub_filters=[to_filters(s) or {} for _, s in pairs] or None,
    )


def run_pipeline(question, today=None):
    r = call_slots(question, today)
    v = validate_slots(r)
    sres = build_sentences(v)
    return {"slot": r, "valid": v, "sentences": sres, "bundle": make_bundle(question, v, sres)}
