"""
[NEW v4] View 묶음 · Point 충돌 · 선택 API (Part 2-2·2-3)

  POST /api/v1/rag/v4/views          ★ 질문 | analyze 응답 | view_bundle → 단위별 View + 충돌 판정 + records / pending
  POST /api/v1/rag/v4/views/select   선택 토큰 + option_id → 고른 View 반영 (서버 세션 없음)
  POST /api/v1/rag/v4/views/points   Record 목록 + 슬롯 → Point 펼치기 + 충돌 판정만 (검색 없음, 단독 확인)

흐름: /rag/v4/analyze → (needs_clarification 이면 /clarify) → /rag/v4/views → (needs_selection 이면 /views/select)
     → 응답 records → POST /api/v1/agent/answer
"""
from fastapi import APIRouter

from backend.api.deps import guard
from backend.schemas.view_v4 import (PointsRequest, PointsResponse, SelectRequest, SelectResponse, ViewSetResponse,
                                     ViewsV4Request)

router = APIRouter(prefix="/api/v1/rag/v4", tags=["② View 묶음·충돌·선택 v4"])


def _first(conf):
    return conf["options"][0]["option_id"] if conf.get("options") else None


@router.post("/views", response_model=ViewSetResponse, summary="★ 단위별 View 묶음 + Point 충돌 판정")
def views(body: ViewsV4Request):
    """- 입력: `question` · `analysis` · `view_bundle` 중 하나
    - **ok**: `records` → `POST /api/v1/agent/answer`
    - **needs_selection**: 같은 교차점(시점·지역·성별·연령·지표·단위) 값이 표마다 다름 → `pending[].options` 에서 하나를 골라
      `POST /api/v1/rag/v4/views/select` 에 `{selection_token, option_id}` (+ 이 응답을 `previous` 로)
    - **needs_clarification / out_of_scope**: 쿼리 분석 단계 결과 (검색 안 함)
    - `units[].conflict.views[]`: View 마다 필수 메타를 썼는지(`used`) · 비교에 넣었는지(`usable`)"""
    from backend.rag.view import build_viewset
    src = body.view_bundle.model_dump(by_alias=True) if body.view_bundle else (body.analysis or body.question)
    if not src:
        from fastapi import HTTPException
        raise HTTPException(422, "question · analysis · view_bundle 중 하나가 필요합니다")
    with guard("View 묶음: "):
        return build_viewset(src, today=body.today, retrieval_config=body.retrieval_config, top_k=body.top_k,
                             n_views=body.n_views, overrides=body.overrides or None,
                             on_ambiguous=_first if body.auto_select == "first" else None)


@router.post("/views/select", response_model=SelectResponse, summary="선택 반영 (토큰 + option_id)")
def select(body: SelectRequest):
    """`previous` 를 주면 그 응답의 Record 를 그대로 쓰고 전체 `records` 를 다시 묶어 `viewset` 으로 돌려줌.
    없으면 토큰 안의 좌표(표·슬롯)로 View 를 다시 만들어 고른 Record 만 돌려줌 (CLI·다른 서버에서도 같은 결과)"""
    from backend.rag.view import apply_selections, resolve
    sels = [s.model_dump() for s in body.selections]
    with guard("선택: "):
        if body.previous:
            vs, applied = apply_selections(body.previous, sels)
            return {"viewset": vs, "records": vs["records"], "applied": _slim(applied)}
        applied = [resolve(s["selection_token"], s["option_id"]) for s in sels]
        return {"viewset": None, "records": [r for a in applied for r in a["records"]], "applied": _slim(applied)}


def _slim(applied):
    return [{k: v for k, v in a.items() if k != "records"} | {"record_ids": [r["id"] for r in a["records"]]}
            for a in applied]


@router.post("/views/points", response_model=PointsResponse, summary="Record → Point + 충돌 판정 (검색 없음)")
def points(body: PointsRequest):
    """이미 가진 View 카드끼리 비교만 해 볼 때. 순서 = 우선순위 (선택지 순서)"""
    from backend.core.settings_v4 import with_overrides
    from backend.rag.view import detect, record_points
    s = with_overrides(body.overrides or None)
    recs = [r.model_dump(mode="json") for r in body.records]
    with guard("Point 비교: "):
        pts, pn = {}, {}
        for r in recs:
            ps, notes = record_points(r, body.filters)
            pts[r["id"]], pn[r["id"]] = [p.as_dict() for p in ps], notes
        views = [{"record": r, "rank": i, "tbl_id": (r.get("source") or {}).get("tbl_id", "")} for i, r in enumerate(recs, 1)]
        conf = detect(views, body.filters or {}, s, "points")
        if conf["status"] == "ambiguous":
            from backend.rag.view.viewset import build_options
            conf["options"] = build_options(conf, {v["record"]["id"]: v for v in views}, s)
        return {"points": pts, "point_notes": pn, "conflict": conf}
