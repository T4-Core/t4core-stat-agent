"""② 질의 API — 슬롯 문자열 → dict 변환(보조), 쿼리 모듈 예시 질의 (로직: services/query_bundle.py)"""
from fastapi import APIRouter

from schemas import ExampleBundle, QueryBundleResult, SlotQuery
from services.query_bundle import build_bundle, example_queries

router = APIRouter(prefix="/query", tags=["② query 질의"])


@router.post("/bundle", response_model=QueryBundleResult, summary="슬롯 문자열 → 슬롯 dict (보조)")
def bundle(body: SlotQuery):
    """쿼리 모듈은 자연어 + 슬롯 dict 를 함께 보낸다. 슬롯이 `[시점] 2025년 [지역] 대구광역시 …` 문자열로만 올 때 dict 로 바꾸는 보조 기능.

    - 빈 슬롯은 null (기본값은 View 생성 때 적용)
    - 지역은 표준명으로 (대구 → 대구광역시), 연령은 {from, to} 로
    - 슬롯이 하나도 없으면 재작성 실패로 보고 filters = null
    """
    b, notes = build_bundle(body.original, body.rewritten, body.sub_questions)
    return {"bundle": b, "notes": notes}


@router.get("/examples", response_model=list[ExampleBundle], summary="쿼리 모듈 예시 12개 (View 모듈 입력 형식)")
def examples():
    """`data/slot_queries.json` → 자연어(original, 서브쿼리 자연어) + 슬롯 dict(filters, sub_filters).
    여기 나온 bundle 을 그대로 POST /views 에 보낼 수 있다."""
    return [{"query_id": e["bundle"]["query_id"], **e} for e in example_queries()]
