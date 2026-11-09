"""
[NEW v4] 쿼리 모듈 v4 API — 단계별 확인 + 한 번에

  POST /api/v1/rag/v4/analyze          ★ 질문 → QueryAnalysis (재작성 → 동의어·접지 → 필수 슬롯·되묻기 → 서브쿼리 → 검색 문장·view_bundle)
  POST /api/v1/rag/v4/clarify          되묻기 응답 (selections + previous) → QueryAnalysis  (HCX 다시 안 부름)
  POST /api/v1/rag/v4/lexicon/lookup   1-2 표현 → 표준 값 (어느 사전에서, CSV 근거 표)
  POST /api/v1/rag/v4/lexicon/learn    1-2 학습 사전에 표현 추가 (승인 대기 / 바로 사용)
  GET  /api/v1/rag/v4/lexicon/pending  1-2 승인 대기 목록
  POST /api/v1/rag/v4/decompose        1-5 슬롯 → 서브쿼리 (HCX 없음, 단독 확인)
  GET  /api/v1/rag/v4/settings         지금 설정 (configs/query_v4.yaml)

status=ok 응답의 view_bundle 은 기존 POST /api/v1/rag/views 에 그대로 넣으면 다음 단계(검색·View)가 이어짐
"""
from fastapi import APIRouter

from backend.api.deps import guard
from backend.schemas.query_v4 import (AnalyzeRequest, ClarifyRequest, DecomposeRequest, DecomposeResponse, LearnRequest,
                                      LexiconLookupRequest, LexiconLookupResponse, QueryAnalysis)

router = APIRouter(prefix="/api/v1/rag/v4", tags=["① Query 질의 분석 v4"])


def _lex(overrides=None):
    from backend.core.settings_v4 import with_overrides
    from backend.rag.query_analyzer.v4.lexicon import get_lexicon
    return get_lexicon(settings=with_overrides(overrides))


@router.post("/analyze", response_model=QueryAnalysis, summary="★ 질문 → QueryAnalysis (HCX 1회)")
def analyze(body: AnalyzeRequest):
    """- **ok**: `view_bundle` → `POST /api/v1/rag/views`
    - **needs_clarification**: `clarifications[].options[].value` 중 고른 값을 `POST /api/v1/rag/v4/clarify` 의
      `selections` 에, 이 응답 전체를 `previous` 에 넣어 다시 보냄
    - **out_of_scope**: 통계 수치를 묻지 않는 질문 (검색하지 않음)
    - `trace`: 단계별 params·출력·초"""
    from backend.rag.query_analyzer.v4 import analyze as run
    with guard("v4 분석: "):
        return run(body.question, body.today, query_id=body.query_id, overrides=body.overrides)


@router.post("/clarify", response_model=QueryAnalysis, summary="되묻기 응답 → QueryAnalysis (previous 가 있으면 HCX 없음)")
def clarify(body: ClarifyRequest):
    from backend.rag.query_analyzer.v4 import analyze as run
    prev = body.previous.model_dump() if body.previous else None
    with guard("v4 되묻기: "):
        return run(body.question, body.today, query_id=body.query_id, overrides=body.overrides, previous=prev,
                   selections=body.selections)


@router.post("/lexicon/lookup", response_model=LexiconLookupResponse, summary="1-2 표현 → 표준 값 (사전·CSV 근거)")
def lexicon_lookup(body: LexiconLookupRequest):
    with guard("동의어: "):
        lex = _lex(body.overrides)
        hits = lex.resolve(body.text, body.slot)
        sug = [] if any(h.grounded for h in hits) else lex.suggest(body.text, body.slot)
        return {"hits": [h.as_dict() for h in hits], "suggestions": sug}


@router.post("/lexicon/learn", summary="1-2 학습 사전에 표현 추가")
def lexicon_learn(body: LearnRequest):
    lex = _lex()
    e = lex.learn(body.surface, body.value, body.slot, source="user", status="active" if body.approve else "pending")
    lex.save()
    return e or {"skipped": "너무 짧거나 값과 같은 표현"}


@router.get("/lexicon/pending", summary="1-2 승인 대기 표현")
def lexicon_pending():
    return {k: v for k, v in _lex().learned.items() if v.get("status") != "active"}


@router.post("/decompose", response_model=DecomposeResponse, summary="1-5 슬롯 → 서브쿼리 (HCX 없음)")
def decompose(body: DecomposeRequest):
    from backend.core.settings_v4 import with_overrides
    from backend.rag.query_analyzer.v4.decompose import decompose as run
    from backend.rag.query_analyzer.v4.grounding import ground_slots
    s = with_overrides(body.overrides)
    lex = _lex(body.overrides)
    with guard("서브쿼리: "):
        g, _ = ground_slots(body.slots, lex)
        subs, reason = run(g, body.slots, [], body.intents, [], lex, s)
    return {"reason": reason, "sub_queries": subs, "slots": g}


@router.get("/settings", summary="지금 설정 (configs/query_v4.yaml)")
def settings():
    from backend.core.settings_v4 import config_path, get_settings
    return {"path": str(config_path()), "settings": get_settings().model_dump()}
