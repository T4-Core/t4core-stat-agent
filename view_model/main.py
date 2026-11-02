"""
View 모듈 API 서버 (FastAPI)

실행  저장소 루트에서
      .venv/Scripts/python.exe -m uvicorn main:app --reload --reload-dir view_model --app-dir view_model --port 8002
Swagger  http://localhost:8002/docs      (ReDoc: /redoc, 스키마 원본: /openapi.json)
"""
from fastapi import FastAPI

from config import OUT
from routers import meta, normalize, query, search, views

app = FastAPI(
    title="View 모듈 API",
    description=(
        "쿼리 모듈의 **자연어 + 슬롯 dict** → 자연어로 메타데이터 검색(bge-m3 + BM25) → 슬롯 조건으로 raw CSV 에서 **View 여러 개** 생성 "
        "→ 질의와 View(**Record, doc_type=view**)를 엮어 판단 모듈로\n\n"
        "- 대표 엔드포인트: **POST /views** (질의 하나), **POST /pipeline/run** (예시 12개)\n"
        "- 처음 한 번: POST /meta/profiles/build → POST /search/index/build\n\n"
        "설명 문서: `view_model/docs/*.md`"
    ),
    version="0.2.0",
)
for r in (meta, normalize, query, search, views):
    app.include_router(r.router)


@app.get("/health", tags=["system"], summary="상태 확인")
def health():
    return {"status": "ok", "meta_profiles": (OUT / "meta_profiles.jsonl").exists(),
            "table_index": (OUT / "table_index" / "tokens.json").exists(),
            "n_normalized": len(list((OUT / "processed").glob("*.parquet"))) if (OUT / "processed").exists() else 0}
