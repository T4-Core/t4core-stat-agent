"""
[모듈 1] 질의 분석 API — 재작성(구 Rewritten_fastapi, 엔드포인트 없었음 → [NEW]) + 슬롯 보조(구 view_model/routers/query.py)

  POST /api/v1/rag/query-rewrite        [NEW] 질문 → 재작성 QueryBundle + View 모듈 입력(view_bundle)   ← 파이프라인 ①
  POST /api/v1/rag/query-rewrite/trace  [NEW] 단계별 중간 결과 (2-1 용어 ~ 4 QueryBundle, 대시보드와 같은 내용)
  POST /api/v1/rag/query-adapt          [NEW] 저장된 재작성 결과 → View 모듈 입력만 변환 (HCX 호출 없음)
  GET  /api/v1/rag/query-slots          [NEW v3] 슬롯 12개 · 의도 9종 · 의도 → View 종류 대응 (HCX 없음)
  GET  /api/v1/rag/hcx-check            [NEW] HCX 연결 확인 (rewriter.check_hcx)
  POST /api/v1/rag/query-bundle         (구 POST /query/bundle)   슬롯 문자열 → 슬롯 dict
  GET  /api/v1/rag/query-examples       (구 GET  /query/examples) 쿼리 모듈 예시 12개

[CHANGED v3] 재작성 모듈 v3 (의도 9종, 하위 질문마다 의도 하나, '범위 밖') 에 맞춤
  - view_bundle 의 sub_filters[i].의도 = 그 하위 질문의 의도 (이전: 원 질문 의도를 모든 하위 질문에)
  - 응답에 out_of_scope (의도 '범위 밖') · intents (원 질문 의도 전체) · sub_intents 추가
"""
import time
from dataclasses import asdict
from datetime import date

from fastapi import APIRouter

from backend.api.deps import guard
from backend.rag.query_analyzer.adapter import (AGE_TARGETS, VIEW_INTENT, VIEW_INTENTS, is_out_of_scope,
                                                resolve_sub_intents, sub_intents_of, to_view_bundle)
from backend.rag.query_analyzer.query_bundle import build_bundle, example_queries
from backend.rag.query_analyzer.slots import INTENTS, SLOT_KEYS
from backend.schemas.query import (AdaptRequest, ExampleBundle, HcxCheckResponse, QueryBundleResult, RewriteRequest,
                                   RewriteResponse, RewriteTrace, SlotQuery, SlotSpec)

router = APIRouter(prefix="/api/v1/rag", tags=["① Query 질의 분석"])


def _today(s):
    return date.fromisoformat(s) if s else None


@router.post("/query-rewrite", response_model=RewriteResponse, summary="① 질문 → QueryBundle (HCX 1회) + View 모듈 입력")
def query_rewrite(body: RewriteRequest):
    """재작성 모듈 v3 (2-2 코드 추출 → 2-1 용어 → 2-3 HCX 슬롯 → 2-4 검증 → 3 문장 → 4 QueryBundle).

    응답의 **view_bundle** 을 그대로 `POST /api/v1/rag/views` 에 넣으면 다음 단계(②)가 이어진다.

    - `intents`: 원 질문 의도 전체 (v3 는 여러 개 가능, `bundle.intent` 는 그중 첫 번째)
    - `sub_intents`: 하위 질문마다 의도 하나 → `view_bundle.sub_filters[i].의도` 에 View 종류로 들어감
    - `out_of_scope`: 의도가 **범위 밖**(용어 뜻·의견 등 통계 수치를 묻지 않는 질문)이면 true. 이때 `POST /api/v1/chat` 은 표를 검색하지 않는다
    """
    from backend.rag.query_analyzer import run_pipeline
    t0 = time.time()
    with guard("재작성: "):
        res = run_pipeline(body.question, _today(body.today))
        notes = [] if res["slot"].get("parsed") else [f"HCX 슬롯 추출 실패 → 코드 추출 값만 사용: {res['slot'].get('error')}"]
        subs = sub_intents_of(res["valid"])
        vb, n2 = to_view_bundle(res["bundle"], body.query_id, body.search_with, subs)
    return {"bundle": asdict(res["bundle"]), "view_bundle": vb, "intents": list(res["valid"]["slots"].get("의도") or []),
            "sub_intents": subs, "out_of_scope": is_out_of_scope(res["bundle"]), "notes": notes + n2,
            "elapsed_s": round(time.time() - t0, 2)}


@router.post("/query-rewrite/trace", response_model=RewriteTrace,
             summary="① 단계별 중간 결과 (프롬프트·HCX 원 응답·검증 로그)")
def query_rewrite_trace(body: RewriteRequest):
    """eval/query_rewrite/dashboard 의 rewrite_trace.json 한 항목과 같은 모양 (HCX 1회)"""
    from backend.rag.query_analyzer import build_trace, run_pipeline
    with guard("재작성: "):
        res = run_pipeline(body.question, _today(body.today))
        return build_trace([res], today=_today(body.today), source="api")["items"][0]


@router.post("/query-adapt", response_model=RewriteResponse, summary="재작성 결과 → View 모듈 입력 변환만 (HCX 없음)")
def query_adapt(body: AdaptRequest):
    """`eval/query_rewrite/outputs/query_bundles_*.json` 같은 저장 결과 한 항목을 ② 입력으로 바꿔 볼 때.

    저장 파일에는 하위 질문 의도가 없으므로 `sub_intents` 를 비우면 하위 질문 문장 끝의 의도어('… 순위')로 되살리고,
    그것도 없으면 원 질문 의도를 쓴다."""
    vb, notes = to_view_bundle(body.bundle, body.query_id, body.search_with, body.sub_intents)
    return {"bundle": body.bundle, "view_bundle": vb, "intents": [body.bundle.intent] if body.bundle.intent else [],
            "sub_intents": resolve_sub_intents(body.bundle, body.sub_intents),
            "out_of_scope": is_out_of_scope(body.bundle), "notes": notes}


@router.get("/query-slots", response_model=SlotSpec, summary="[v3] 슬롯 12개 · 의도 9종 · 의도 → View 종류 (HCX 없음)")
def query_slots():
    """재작성 모듈이 내보내는 슬롯·의도와, View 모듈 입력으로 바꿀 때의 대응표 (adapter.py)"""
    return {"slot_keys": SLOT_KEYS, "intents": INTENTS, "view_intents": list(VIEW_INTENTS), "view_intent_map": VIEW_INTENT,
            "age_targets": AGE_TARGETS}


@router.get("/hcx-check", response_model=HcxCheckResponse, summary="HCX 설정·호출 확인 (1회 호출)")
def hcx_check():
    from backend.rag.query_analyzer import check_hcx, settings
    return {"settings": settings(), "check": check_hcx()}


# ── 구 view_model/routers/query.py (로직 그대로, 경로만 /api/v1/rag 아래로) ──
@router.post("/query-bundle", response_model=QueryBundleResult, summary="슬롯 문자열 → 슬롯 dict (보조) — 구 POST /query/bundle")
def bundle(body: SlotQuery):
    """쿼리 모듈은 자연어 + 슬롯 dict 를 함께 보낸다. 슬롯이 `[시점] 2025년 [지역] 대구광역시 …` 문자열로만 올 때 dict 로 바꾸는 보조 기능.

    - 빈 슬롯은 null (기본값은 View 생성 때 적용)
    - 지역은 표준명으로 (대구 → 대구광역시), 연령은 {from, to} 로
    - 슬롯이 하나도 없으면 재작성 실패로 보고 filters = null
    """
    b, notes = build_bundle(body.original, body.rewritten, body.sub_questions)
    return {"bundle": b, "notes": notes}


@router.get("/query-examples", response_model=list[ExampleBundle], summary="쿼리 모듈 예시 12개 (View 모듈 입력 형식) — 구 GET /query/examples")
def examples():
    """`backend/rag/query_analyzer/data/slot_queries.json` → 자연어 + 슬롯 dict.
    여기 나온 bundle 을 그대로 POST /api/v1/rag/views 에 보낼 수 있다."""
    return [{"query_id": e["bundle"]["query_id"], **e} for e in example_queries()]
