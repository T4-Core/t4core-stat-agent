# storage/ — 로컬 데이터 저장소 (git 에 올리지 않음, 폴더 뼈대만)

| 폴더 | 내용 | 만드는 코드 | 예전 위치 |
|---|---|---|---|
| `kosis_data/` | 수집 원본: `catalog.csv`, `meta/`, `raw/<조사>/`, `parts/`, `table_schema.csv`, `rag_views/`, `answers/` … | `backend/rag/ingestion/collector.py` | `./kosis_data` (저장소 루트) |
| `parquet/` | View 모듈 산출물: `meta_profiles.jsonl`, `processed/*.parquet`, `profiles/`, `dict/`, `views/` | `ingestion/meta_profile.py`, `normalize.py`, `build_view.py` | `view_model/output/` |
| `indices/table_index/` | 표 설명문 BM25 색인 | `ingestion/table_text.py` | `view_model/output/table_index/` |
| `indices/embed_cache_view.sqlite` | View 모듈 임베딩 캐시 | `retrieval/dense.py` | `view_model/output/embed_cache.sqlite` |
| `csv_index/` | [v4] 원본 CSV 값 사전: `tables.jsonl`(표별 열·분류 값·항목·단위·기간·주석) · `values.parquet`(값 → 표 역색인) · `learned_lexicon.json`(학습 사전) | `python -m backend.rag.csv_index build` | — |
| `runs/` | [v4] 단계별 실행 기록 `<run_id>/params.json · steps.jsonl · result.json` (`save_runs: true` 일 때) · 검색 비교 `<run_id>/report.html · review.csv · results.jsonl` | `backend/core/tracking.py`, `backend/rag/retrieval/lab.py` | — |
| `.view_selection_secret` | [v4] View 충돌 선택 토큰 서명 키 (없으면 자동 생성. 환경변수 `VIEW_SELECTION_SECRET` 이 우선) | `backend/rag/view/selection.py` | — |
| `indices/retrieval_lab/` | [v4] 검색 실험 캐시: 로컬 모델 벡터(`embed_cache.sqlite`) · BM25 문서 토큰 · 코퍼스 벡터 | `backend/rag/retrieval/` | — |
| `indices/rag_qa/` | 하이브리드 인덱스(`<variant>/bm25.pkl, dense.npy …`) + 임베딩 캐시 | `ingestion/indexer.py`, `core/llm.py` | `kosis_data/index/` |

**옮기지 않아도 동작합니다.** `backend/core/config.py` 가 환경변수 → `storage/…` → 예전 위치 순서로 찾습니다.
옮기려면 이미지의 `kosis_data` 폴더를 통째로 `storage/kosis_data` 로, `kosis_data/index` 는 `storage/indices/rag_qa` 로 옮기면 됩니다.
확인: `python -m backend.core.config` 또는 Swagger `GET /api/v1/system/paths`
