"""[NEW] 판단(Judge) 모듈 — 받은 View 가 질문 조건(슬롯)을 실제로 담았는가를 실시간으로 판정

  extract.py    Record → ViewContents   (View 에 '실제로 담긴 조건' 정리)          ← 2단계
  slots.py      요청 슬롯 vs ViewContents → 슬롯별 SlotCheck                        ← 3단계
  adapters.py   ViewResult(나중에 SearchResult) → 단위별 입력, adapter notes 해석   ← 4단계
  aggregate.py  SlotCheck → View → 단위 → 질문 전체 점수·판정·사유 코드             ← 4단계

  사용  from backend.rag.judge import judge
        result = judge({"bundle": view_bundle, "views": view_result, "upstream_notes": notes})

입출력 계약: backend/schemas/judge.py
"""
from backend.rag.judge.adapters import units_from_view_result, upstream_checks
from backend.rag.judge.aggregate import judge_question, judge_unit
from backend.schemas.judge import JudgeConfig, JudgeRequest, JudgeResult


def judge(request) -> JudgeResult:
    """판단 모듈 진입점. 오케스트레이터(run_chat)와 API 는 이 함수만 부른다.
    request = JudgeRequest 또는 같은 모양의 dict (dict 면 pydantic 이 검증하면서 JudgeRequest 로 바꾼다)"""
    req = request if isinstance(request, JudgeRequest) else JudgeRequest.model_validate(request)
    config = req.config or JudgeConfig()                              # 설정이 없으면 기본 기준
    units = units_from_view_result(req.views, req.bundle)             # ① 단위별 (슬롯, Record 목록)
    upstream, question_reasons = upstream_checks(req.upstream_notes)  # ② 변환 단계에서 빠진 슬롯
    judged = [judge_unit(u, config, upstream.get(u.index)) for u in units]   # ③④ View → 단위
    return judge_question(req.views.query_id, judged, config, question_reasons)   # ⑤ 질문 전체
