# storage/ — 로컬 데이터 저장소 (git 에 올리지 않음, 폴더 뼈대만)

| 폴더 | 내용 | 만드는 코드 | 예전 위치 |
|---|---|---|---|
| `kosis_data/` | 수집 원본: `catalog.csv`, `meta/`, `raw/<조사>/`, `parts/`, `table_schema.csv`, `rag_views/`, `answers/` … | `backend/rag/ingestion/collector.py` | `./kosis_data` (저장소 루트) |
| `parquet/` | View 모듈 산출물: `meta_profiles.jsonl`, `processed/*.parquet`, `profiles/`, `dict/`, `views/` | `ingestion/meta_profile.py`, `normalize.py`, `build_view.py` | `view_model/output/` |
| `indices/table_index/` | 표 설명문 BM25 색인 | `ingestion/table_text.py` | `view_model/output/table_index/` |
| `indices/embed_cache_view.sqlite` | View 모듈 임베딩 캐시 | `retrieval/dense.py` | `view_model/output/embed_cache.sqlite` |
| `indices/rag_qa/` | 하이브리드 인덱스(`<variant>/bm25.pkl, dense.npy …`) + 임베딩 캐시 | `ingestion/indexer.py`, `core/llm.py` | `kosis_data/index/` |

**옮기지 않아도 동작합니다.** `backend/core/config.py` 가 환경변수 → `storage/…` → 예전 위치 순서로 찾습니다.
옮기려면 이미지의 `kosis_data` 폴더를 통째로 `storage/kosis_data` 로, `kosis_data/index` 는 `storage/indices/rag_qa` 로 옮기면 됩니다.
확인: `python -m backend.core.config` 또는 Swagger `GET /api/v1/system/paths`
