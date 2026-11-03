"""
[NEW] 판단(Judge) API — View 가 질문 조건(슬롯)을 실제로 담았는가

  POST /api/v1/rag/judge            JudgeRequest(bundle + ViewResult + adapter notes) → JudgeResult   ← 본 기능
  GET  /api/v1/rag/judge/config     기본 판정 기준(JudgeConfig) — 복사해서 config 에 고쳐 넣을 때
  POST /api/v1/rag/judge/from-chat  POST /api/v1/chat 응답 통째 → JudgeResult  (실제 파이프라인 결과로 시험할 때)

판정 로직은 backend/rag/judge 에 있고, 여기는 HTTP ↔ 함수 연결만 한다.
"""
# APIRouter: 엔드포인트 묶음. main.py 에서 app.include_router(router) 로 앱에 붙인다
#   (자바 Spring 으로 치면 @RestController + @RequestMapping("/api/v1/rag") 클래스 하나)
from fastapi import APIRouter

from backend.api.deps import guard            # 예상 못 한 예외 → HTTP 오류 응답 (서버가 죽지 않게)
from backend.rag.judge import judge
from backend.schemas.chat import ChatResponse
from backend.schemas.judge import JudgeConfig, JudgeRequest, JudgeResult


class ChatJudgeRequest(ChatResponse):
    """/chat 응답(ChatResponse) + 선택 필드 judge_config.
    ChatResponse 를 상속했으므로 /chat 응답을 그대로 붙여 넣어도 맞는 모양이다 (자바의 extends 와 같음).
    config 를 함수 인자로 따로 받으면 FastAPI 가 요청을 {"body": …, "config": …} 로 감싸야 해서,
    '응답을 통째로 붙여 넣기' 가 안 된다 → 필드 하나를 덧붙이는 방식으로 했다.
    이 API 에서만 쓰는 입력 모양이라 schemas/ 가 아니라 여기에 둔다."""
    judge_config: JudgeConfig | None = None

TAG = "②-1 Judge 판단 (View ↔ 질문 조건)"      # main.py TAGS 의 이름과 같아야 Swagger 에서 순서·설명이 붙는다
router = APIRouter(prefix="/api/v1/rag", tags=[TAG])


# response_model: 응답을 이 모양으로 검사·정리해서 내보내고, Swagger 에 응답 예시로도 보여 준다
# body: JudgeRequest  → FastAPI 가 요청 JSON 을 JudgeRequest 로 검증해 넣어 준다. 형식이 틀리면 함수 실행 전에 422
@router.post("/judge", response_model=JudgeResult, summary="View ↔ 질문 조건 판정 (슬롯별 · View별 · 단위별 · 전체)")
def judge_views(body: JudgeRequest):
    """`/api/v1/rag/views/detail` 응답을 **views** 에, query-rewrite 응답의 **view_bundle** 을 **bundle** 에,
    **notes** 를 **upstream_notes** 에 넣는다. HCX 호출 없음 (규칙 기반이라 빠르다).

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
    """`/api/v1/chat` 응답을 그대로 붙여 넣는다. 서버가 JudgeRequest 로 조립한다:
    bundle = view_bundle, views = views, upstream_notes = notes.  기준을 바꾸려면 `judge_config` 를 덧붙인다.

    notes 에는 '[main] … View 생성 실패' 같은 단위 메모도 섞여 있지만, 정보 손실이 없는 메모는 판단 모듈이 무시한다."""
    with guard("judge: "):
        return judge(JudgeRequest(bundle=body.view_bundle, views=body.views, upstream_notes=body.notes,
                                  config=body.judge_config))
