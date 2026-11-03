"""
FastAPI 엔트리포인트 — 모든 모듈을 하나의 Swagger 로 통합  (구 view_model/main.py 를 확장)

실행  저장소 루트에서
      uvicorn backend.main:app --reload --port 8000
      [CHANGED] 이전: .venv/Scripts/python.exe -m uvicorn main:app --reload --reload-dir view_model --app-dir view_model --port 8002
                     (재작성 모듈은 FastAPI 앱이 없었음 → 이번에 같은 앱에 등록)
Swagger  http://localhost:8000/docs      (ReDoc: /redoc, 스키마 원본: /openapi.json)

Swagger 화면 순서 = 파이프라인 순서
  ⓪ Ingest  처음 한 번: POST /api/v1/rag/chunk-and-index  (메타 프로필 → 표 색인)
  ① Query   POST /api/v1/rag/query-rewrite   질문 → bundle + view_bundle
  ② View    POST /api/v1/rag/views           view_bundle → Record 목록
  ③ Agent   POST /api/v1/agent/answer        질문 + Record 목록 → 답변
  ★         POST /api/v1/chat                ①→②→③ 한 번에
"""
from fastapi import FastAPI

from backend.api import v1_chat, v1_ingest, v1_judge, v1_query, v1_search
# [CHANGED] 이전: from backend.api import v1_chat, v1_ingest, v1_query, v1_search   (v1_judge = 판단 모듈 API 추가)
from backend.core.config import OUT, TABLE_INDEX_DIR, paths

TAGS = [
    {"name": "system", "description": "상태·경로 확인 (데이터 폴더가 어디로 해석됐는지)"},
    {"name": "⓪ Ingest 준비 (메타·정규화·색인)", "description": "수집 결과(kosis_data) → 메타 프로필·표 색인·정규화 parquet"},
    {"name": "① Query 질의 분석", "description": "질문 → 재작성 QueryBundle → View 모듈 입력 (backend/rag/query_analyzer)"},
    {"name": "② Retrieval 검색·View 생성", "description": "QueryBundle → 표 검색 → View 카드(Record) (backend/rag/retrieval, ingestion)"},
    {"name": v1_judge.TAG, "description": "View 가 질문 조건(슬롯)을 실제로 담았는가 → pass/partial/fail + 사유 코드 (backend/rag/judge)"},  # [NEW]
    {"name": "③ Agent 통합 (전체 파이프라인)", "description": "Record → HCX 답변 + 차트 + 출처 (backend/agent)"},
    {"name": "④ Data 좌표 조회·차트", "description": "Record.source → DuckDB 재조회 (backend/data_engine)"},
]

app = FastAPI(
    title="KOSIS 통계 Agent API (통합)",
    description=(
        "질문 → **① 재작성** → **② 검색·View 생성** → **③ 답변** 을 한 Swagger 에서 단계별·한 번에 테스트\n\n"
        "- 한 번에: **POST /api/v1/chat**\n"
        "- 단계별: query-rewrite 응답의 `view_bundle` → /rag/views 응답(Record 목록) → /agent/answer 의 `records`\n"
        "- 처음 한 번: POST /api/v1/rag/chunk-and-index  (경로 확인: GET /api/v1/system/paths)\n\n"
        "설명 문서: `MIGRATION.md`, `docs/`"
    ),
    version="0.3.0",
    openapi_tags=TAGS,
)
# [CHANGED] 이전: for r in (meta, normalize, query, search, views): app.include_router(r.router)   (View 모듈만)
for r in (v1_ingest.prep, v1_ingest.router, v1_query.router, v1_search.router, v1_judge.router, v1_chat.router,
          v1_search.data):
    app.include_router(r)
# [CHANGED] 이전: for r in (v1_ingest.prep, v1_ingest.router, v1_query.router, v1_search.router, v1_chat.router, v1_search.data):
#   (v1_judge.router 를 ② 검색과 ③ 답변 사이에 등록 — 파이프라인 순서 = Swagger 순서)


@app.get("/health", tags=["system"], summary="상태 확인")
def health():
    # 구 view_model/main.py health 와 같은 항목 + 경로 (표 색인 위치만 TABLE_INDEX_DIR 로 바뀜)
    return {"status": "ok", "meta_profiles": (OUT / "meta_profiles.jsonl").exists(),
            "table_index": (TABLE_INDEX_DIR / "tokens.json").exists(),
            "n_normalized": len(list((OUT / "processed").glob("*.parquet"))) if (OUT / "processed").exists() else 0}


@app.get("/api/v1/system/paths", tags=["system"], summary="데이터 경로 해석 결과 (환경변수 → storage → 예전 위치)")
def system_paths():
    return paths()
