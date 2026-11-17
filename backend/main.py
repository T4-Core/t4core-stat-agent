"""
FastAPI 앱 — uvicorn backend.main:app --reload --port 8000  →  http://localhost:8000/docs

Swagger 순서 = 파이프라인 순서
  ⓪ 준비      POST /api/v1/ingest/prepare     메타 프로필 → 표 색인 → CSV 값 사전 (처음 한 번)
  ① 질의 분석  POST /api/v1/rag/analyze        질문 → QueryAnalysis (view_bundle)
  ② 검색·View  POST /api/v1/rag/views          → 단위별 View + 충돌 판정 → records
  ③ 답변       POST /api/v1/agent/answer       질문 + records → 답변
  ★            POST /api/v1/chat               ①→②→③ 한 번에
"""
from fastapi import FastAPI

from backend.api import chat, csv_index, ingest, judge, query, views
from backend.core.config import TABLE_INDEX_DIR, VIEW_OUT_DIR, paths

TAGS = [
    {"name": "system", "description": "상태·경로 확인"},
    {"name": ingest.TAG, "description": "수집 결과(kosis_data) → 메타 프로필·표 색인·CSV 값 사전·정규화 (backend/rag/ingestion)"},
    {"name": csv_index.TAG, "description": "원본 CSV 의 분류 값·항목·단위·기간·주석 → 값 → 표 역색인 (backend/rag/csv_index)"},
    {"name": query.TAG, "description": "질문 → 재작성(HCX) → CSV 값 사전 접지 → 되묻기 → 서브쿼리 → view_bundle "
                                       "(backend/rag/query_analyzer)"},
    {"name": views.TAG, "description": "검색 단위별 표 검색(backend/rag/search) → View 카드 → Point 충돌 판정·선택 "
                                       "(backend/rag/view)"},
    {"name": judge.TAG, "description": "View 가 질문 조건(슬롯)을 실제로 담았는가 → pass/partial/fail + 사유 (backend/rag/judge)"},
    {"name": chat.TAG, "description": "Record → HCX 답변 + 차트 + 출처 (backend/agent)"},
    {"name": views.DATA_TAG, "description": "Record.source → parquet 재조회 (backend/data_engine)"},
]

app = FastAPI(
    separate_input_output_schemas=False,   # 요청·응답 스키마 이름을 하나로 (Record-Input/-Output 으로 갈라지지 않게)
    title="KOSIS 통계 Agent API",
    description=("질문 → **① 질의 분석** → **② 검색·View** → **③ 답변** 을 단계별 또는 한 번에\n\n"
                 "- 한 번에: **POST /api/v1/chat**\n"
                 "- 단계별: /rag/analyze → /rag/views → /agent/answer\n"
                 "- 처음 한 번: POST /api/v1/ingest/prepare (경로 확인: GET /api/v1/system/paths)"),
    version="1.0.0",
    openapi_tags=TAGS,
)
for r in (ingest.router, csv_index.router, query.router, views.router, judge.router, chat.router, views.data):
    app.include_router(r)


@app.get("/health", tags=["system"], summary="상태 확인")
def health():
    from backend.core.config import CSV_INDEX_DIR
    return {"status": "ok", "meta_profiles": (VIEW_OUT_DIR / "meta_profiles.jsonl").exists(),
            "table_index": (TABLE_INDEX_DIR / "tokens.json").exists(),
            "csv_index": (CSV_INDEX_DIR / "values.parquet").exists(),
            "n_normalized": len(list((VIEW_OUT_DIR / "processed").glob("*.parquet")))
            if (VIEW_OUT_DIR / "processed").exists() else 0}


@app.get("/api/v1/system/paths", tags=["system"], summary="데이터 경로 해석 결과")
def system_paths():
    return paths()


@app.get("/api/v1/system/pipelines", tags=["system"], summary="사용 가능한 파이프라인 (기본 + 개인 폴더 플러그인)")
def system_pipelines():
    from backend.core import plugins
    from backend.core.config import PRIVATE_DIR
    return {"private_dir": str(PRIVATE_DIR) if PRIVATE_DIR else None, "pipelines": plugins.available()}
