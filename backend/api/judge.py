"""
②-1 판단(Judge) API — View 가 질문 조건(슬롯)을 실제로 담았는가 (규칙 기반, HCX 없음)

  POST /api/v1/rag/judge            JudgeRequest(bundle + ViewResult + notes) → JudgeResult
  GET  /api/v1/rag/judge/config     기본 판정 기준(JudgeConfig)
  POST /api/v1/rag/judge/from-chat  POST /api/v1/chat 응답 통째 → JudgeResult
"""
from fastapi import APIRouter, HTTPException

from backend.api.deps import guard
from backend.rag.judge import judge
from backend.schemas.chat import ChatResponse
from backend.schemas.judge import JudgeConfig, JudgeRequest, JudgeResult


class ChatJudgeRequest(ChatResponse):
    """/chat 응답을 그대로 붙여 넣고, 기준을 바꾸려면 judge_config 를 덧붙인다"""
    judge_config: JudgeConfig | None = None


TAG = "②-1 판단 (View ↔ 질문 조건)"
router = APIRouter(prefix="/api/v1/rag", tags=[TAG])


@router.post("/judge", response_model=JudgeResult, summary="View ↔ 질문 조건 판정 (슬롯별 · View별 · 단위별 · 전체)")
def judge_views(body: JudgeRequest):
    """`POST /api/v1/rag/views` 응답을 **views** 에, analyze 응답의 **view_bundle** 을 **bundle** 에,
    **notes** 를 **upstream_notes** 에 넣는다.

    결과의 `reasons` 로 오케스트레이터가 다음 행동을 고른다 (no_views · empty_view → 재검색,
    slot_dropped_upstream → 재작성 재시도, slot_substituted → 주의 문구 등)."""
    with guard("judge: "):
        return judge(body)


@router.get("/judge/config", response_model=JudgeConfig, summary="기본 판정 기준 (JudgeConfig 기본값)")
def judge_config():
    """이 값을 복사해서 POST /judge 의 `config` 에 고쳐 넣으면 기준을 바꿔 시험할 수 있다
    (예: pass_threshold 0.85, upstream_tier null)."""
    return JudgeConfig()


@router.post("/judge/from-chat", response_model=JudgeResult, summary="POST /api/v1/chat 응답 통째 → 판정")
def judge_from_chat(body: ChatJudgeRequest):
    """bundle = analysis.view_bundle, views = views, upstream_notes = notes 로 조립한다.
    notes 중 정보 손실이 없는 메모는 판단 모듈이 무시한다."""
    vb = (body.analysis.view_bundle if body.analysis else None) or (body.views.view_bundle if body.views else None)
    if not vb or not body.views or not body.views.units:
        raise HTTPException(422, f"검색·View 까지 진행된 /chat 응답이 필요합니다 (status={body.status})")
    with guard("judge: "):
        return judge(JudgeRequest(bundle=vb, views=body.views.model_dump(by_alias=True), upstream_notes=body.notes,
                                  config=body.judge_config))
