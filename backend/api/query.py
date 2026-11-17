"""
① 질의 분석 API

  POST /api/v1/rag/analyze          질문 → QueryAnalysis (재작성 → 동의어·접지 → 필수 슬롯·되묻기 → 서브쿼리 → view_bundle)
  POST /api/v1/rag/clarify          되묻기 응답 (selections + previous) → QueryAnalysis (HCX 다시 안 부름)
  POST /api/v1/rag/lexicon/lookup   표현 → 표준 값 (어느 사전에서, CSV 근거 표)
  POST /api/v1/rag/lexicon/learn    학습 사전에 표현 추가 (승인 대기 / 바로 사용)
  GET  /api/v1/rag/lexicon/pending  승인 대기 목록
  POST /api/v1/rag/decompose        슬롯 → 서브쿼리 (HCX 없음)
  GET  /api/v1/rag/settings         지금 설정 (configs/pipeline.yaml)
  GET  /api/v1/rag/hcx-check        HCX 설정·호출 확인
"""
from fastapi import APIRouter

from backend.api.deps import guard
from backend.schemas.query import (
    AnalyzeRequest,
    ClarifyRequest,
    DecomposeRequest,
    DecomposeResponse,
    HcxCheckResponse,
    LearnRequest,
    LexiconLookupRequest,
    LexiconLookupResponse,
    QueryAnalysis,
)

TAG = "① 질의 분석"
router = APIRouter(prefix="/api/v1/rag", tags=[TAG])


def _lex(overrides=None):
    from backend.core.settings import with_overrides
    from backend.rag.query_analyzer.lexicon import get_lexicon
    return get_lexicon(settings=with_overrides(overrides))


@router.post("/analyze", response_model=QueryAnalysis, summary="질문 → QueryAnalysis (HCX 1회)")
def analyze(body: AnalyzeRequest):
    """- **ok**: `view_bundle` → `POST /api/v1/rag/views`
    - **needs_clarification**: `clarifications[].options[].value` 중 고른 값을 `POST /api/v1/rag/clarify` 의
      `selections` 에, 이 응답 전체를 `previous` 에 넣어 다시 보냄
    - **out_of_scope**: 통계 수치를 묻지 않는 질문 (검색하지 않음)
    - `trace`: 단계별 params·출력·초"""
    from backend.rag.query_analyzer.analyze import analyze as run
    with guard("분석: "):
        return run(body.question, body.today, query_id=body.query_id, overrides=body.overrides)


@router.post("/clarify", response_model=QueryAnalysis, summary="되묻기 응답 → QueryAnalysis (previous 가 있으면 HCX 없음)")
def clarify(body: ClarifyRequest):
    from backend.rag.query_analyzer.analyze import analyze as run
    prev = body.previous.model_dump() if body.previous else None
    with guard("되묻기: "):
        return run(body.question, body.today, query_id=body.query_id, overrides=body.overrides, previous=prev,
                   selections=body.selections)


@router.post("/lexicon/lookup", response_model=LexiconLookupResponse, summary="표현 → 표준 값 (사전·CSV 근거)")
def lexicon_lookup(body: LexiconLookupRequest):
    with guard("동의어: "):
        lex = _lex(body.overrides)
        hits = lex.resolve(body.text, body.slot)
        sug = [] if any(h.grounded for h in hits) else lex.suggest(body.text, body.slot)
        return {"hits": [h.as_dict() for h in hits], "suggestions": sug}


@router.post("/lexicon/learn", summary="학습 사전에 표현 추가")
def lexicon_learn(body: LearnRequest):
    lex = _lex()
    e = lex.learn(body.surface, body.value, body.slot, source="user", status="active" if body.approve else "pending")
    lex.save()
    return e or {"skipped": "너무 짧거나 값과 같은 표현"}


@router.get("/lexicon/pending", summary="승인 대기 표현")
def lexicon_pending():
    return {k: v for k, v in _lex().learned.items() if v.get("status") != "active"}


@router.post("/decompose", response_model=DecomposeResponse, summary="슬롯 → 서브쿼리 (HCX 없음)")
def decompose(body: DecomposeRequest):
    from backend.core.settings import with_overrides
    from backend.rag.query_analyzer.decompose import decompose as run
    from backend.rag.query_analyzer.grounding import ground_slots
    s = with_overrides(body.overrides)
    lex = _lex(body.overrides)
    with guard("서브쿼리: "):
        g, _ = ground_slots(body.slots, lex)
        subs, reason = run(g, body.slots, [], body.intents, [], lex, s)
    return {"reason": reason, "sub_queries": subs, "slots": g}


@router.get("/settings", summary="지금 설정 (configs/pipeline.yaml)")
def settings():
    from backend.core.settings import config_path, get_settings
    return {"path": str(config_path()), "settings": get_settings().model_dump()}


@router.get("/hcx-check", response_model=HcxCheckResponse, summary="HCX 설정·호출 확인 (1회 호출)")
def hcx_check():
    from backend.rag.query_analyzer.config import check_hcx
    from backend.rag.query_analyzer.config import settings as hcx_settings
    return {"settings": hcx_settings(), "check": check_hcx()}
