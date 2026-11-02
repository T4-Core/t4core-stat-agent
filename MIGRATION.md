# 구조 개편 안내 (MIGRATION)

루트에 흩어져 있던 `kosis_*.py`, `view_model/`(FastAPI), `Rewritten_fastapi/`(재작성 모듈)를 `backend/` 한 패키지로 모으고,
**하나의 Swagger** 에서 ① 재작성 → ② 검색·View → ③ 답변 을 단계별 또는 한 번에 테스트할 수 있게 연결하였음
각 모듈의 로직은 최대한 유지한 채로 두고, 경로·import·모듈 사이 입출력만 맞췄습니다. => 만일 변경된 부분은 따로 주석처리하였음

---

## 1. 코드 변경 표시 규칙

| 표시 | 뜻 |
|---|---|
| `# [CHANGED] 이전: <예전 코드>` | 바뀐 줄 바로 옆/아래에 예전 코드를 그대로 남김 |
| `[NEW]` | 이번에 새로 만든 함수·파일·필드 |
| `[MOVED]` / 파일 머리말 `(구 xxx.py)` | 내용 그대로 옮긴 것. 머리말에 원래 파일·행 번호 |
| `[ADDED]` | requirements·.gitignore 에 추가한 항목 |

`grep -rn "\[CHANGED\]" backend eval tests` 로 모든 변경 위치를 볼 수 있습니다.

---

## 2. 파일 이동표

| 예전 | 새 위치 | 비고 |
|---|---|---|
| `kosis_rag_builder.py` | `backend/rag/ingestion/collector.py` | **업로드해 주신 최신본** 기준 (저장소 본보다 `--root/--append/also_in` 이 추가된 버전) |
| `kosis_views.py` | `backend/rag/ingestion/view_builder.py` | 기본 경로만 변경 |
| `kosis_rag_qa.py` (820행) | 역할별로 나눔 ↓ | 함수 본문은 그대로 |
| ├ `_host`·`_post`·`chat`·`EmbedCache`·`embed_*`·`normalize` | `backend/core/llm.py` | |
| ├ `tokenize` | `backend/rag/retrieval/lexical.py` | |
| ├ `load_records`·`embed_texts_of`·`stage_index` | `backend/rag/ingestion/indexer.py` | |
| ├ `class Index` (BM25+Dense→RRF) | `backend/rag/retrieval/fusion.py` | |
| ├ `REWRITE_*`·`ANSWER_*` | `backend/agent/prompts.py` | |
| └ `rewrite`·`answer`·`apply_conditions`·CLI | `backend/agent/light_agent.py` | + [NEW] 통합 파이프라인 `run_chat` |
| `Rewritten_fastapi/kosis_rag_qa.py` (복사본) | **삭제** | 원본과 주석 1줄 차이. 재작성 모듈은 `core/llm.py` 를 import |
| `Rewritten_fastapi/rewriter/*.py` | `backend/rag/query_analyzer/*.py` | 파일 이름 그대로. `config.py` 만 수정 |
| `Rewritten_fastapi/{scripts,dashboard,labeling,outputs}` | `eval/query_rewrite/…` | `data/` 는 git 에 없어서 옮기지 못함 (아래 7번) |
| `Rewritten_fastapi/tests/*` | `tests/query_analyzer/*` | import 만 변경 |
| `Rewritten_fastapi/notebook/` | `notebooks/query_rewrite/` | |
| `view_model/config.py` | `backend/core/config.py` (경로) + `core/utils.py` + `data_engine/duckdb_client.py` | |
| `view_model/schemas.py` | `backend/schemas/{query,record,search,view}.py` | 클래스 그대로 나눔 |
| `view_model/main.py` + `routers/*.py` | `backend/main.py` + `backend/api/v1_*.py` | 엔드포인트 경로 대응은 4번 |
| `view_model/services/{meta_profile,normalize,table_text,build_view,views}.py` | `backend/rag/ingestion/` | import 만 변경 |
| `view_model/services/search.py` | `backend/rag/retrieval/table_search.py` | |
| `view_model/services/embedding.py` | `backend/rag/retrieval/dense.py` | 캐시 위치만 변경 |
| `view_model/services/query_bundle.py`, `data/slot_queries.json` | `backend/rag/query_analyzer/` | |
| `view_model/docs`, 각 README | `docs/view_model/`, `docs/query_rewrite/` | 맨 위에 "이동됨" 안내 추가 |
| `golden_set_eval_pipeline/*`, `kosis_rag_eval_50.*` | `eval/golden_set/` | `kosis_pop_qa_case1.py` import 수정 |
| `review_app.py` | `eval/review_app.py` | 기본 경로 수정 |
| `why/` | `notebooks/why/` | |

### 구조안과 다르게 한 부분
- **`indexer.py (구 kosis_rag_builder.py)`** → `kosis_rag_builder.py` 는 KOSIS **수집기**라서 `ingestion/collector.py` 로 두고, 실제 BM25·Dense 인덱싱 코드(`kosis_rag_qa.py stage_index`)를 `indexer.py` 에 넣었습니다.
- **`rewriter.py / decomposer.py / filter_extractor.py`** → 재작성 모듈은 노트북 단계별 파일(terms·extract·slots·validate·sentence·bundle)로 이미 나뉘어 테스트까지 있어서, 파일은 그대로 두고 구조안 이름은 **진입점(re-export)** 으로만 만들었습니다.
- **`schemas/view.py`** 추가 → View 모듈 상세 결과(ViewResult 등)·관리 응답이 4개 파일 어디에도 맞지 않아서.
- **`reranker.py`** → 아직 Cross-encoder 가 없어 자리만(pass-through). 지금의 재정렬은 `table_search.search()` 2단계(bge-m3).
- **LangGraph** → 현재 코드에 없어 `light_agent.run_chat` 은 순차 3노드 함수입니다. 노드 경계(rewrite/views/answer)를 그대로 그래프 노드로 옮길 수 있게 나눠 두었습니다.
- **임베딩 클라이언트 2개** (`core/llm.py` = 하이브리드 인덱스용, `retrieval/dense.py` = View 모듈용) → 캐시 키·위치가 달라 합치면 캐시를 다시 만들어야 해서 이번엔 그대로 둠.

---

## 3. 데이터 경로 (동적 해석)

모든 경로는 `backend/core/config.py` 한 곳에서 정합니다. **폴더를 옮기지 않아도 동작**하고, 옮기면 자동으로 새 위치를 씁니다.
순서: ① 환경변수(.env) → ② `storage/…` → ③ 예전 위치 → ④ 없으면 `storage/…` 에 새로 생성

| 변수 | 내용 | ② 새 위치 | ③ 예전 위치 |
|---|---|---|---|
| `KOSIS_DATA_DIR` (`KOSIS_DATA` 도 인식) | catalog.csv, meta/, raw/, parts/ … (이미지의 폴더) | `storage/kosis_data` | `./kosis_data`, `../kosis_data`, 실행 폴더 `kosis_data` |
| `RAG_VIEWS_DIR` | kosis_views 결과 (processed/, records.jsonl) | `KOSIS_DATA_DIR/rag_views` | 같음 |
| `RAG_INDEX_DIR` | 하이브리드 인덱스·임베딩 캐시 | `storage/indices/rag_qa` | `kosis_data/index` |
| `VIEW_OUT_DIR` | View 모듈 parquet·프로필·meta_profiles | `storage/parquet` | `view_model/output` |
| `TABLE_INDEX_DIR` | 표 설명문 BM25 색인 | `storage/indices/table_index` | `view_model/output/table_index` |
| `VIEW_EMBED_CACHE` | View 모듈 임베딩 캐시 | `storage/indices/embed_cache_view.sqlite` | `view_model/output/embed_cache.sqlite` |
| `ANSWERS_DIR` | 답변 저장 | `KOSIS_DATA_DIR/answers` | 같음 |

확인: `python -m backend.core.config` 또는 Swagger `GET /api/v1/system/paths`

**권장 이동** (선택): `kosis_data/` → `storage/kosis_data/`, `kosis_data/index/` → `storage/indices/rag_qa/`, `view_model/output/` → `storage/parquet/` (+ `table_index/`, `embed_cache.sqlite` 는 `storage/indices/`).
인덱스 `meta.json` 에 저장된 예전 상대 경로(`kosis_data/rag_views/records.jsonl`)는 `config.resolve_data_path()` 가 새 위치로 다시 찾습니다.

---

## 4. 통합 Swagger (`uvicorn backend.main:app --reload` → `/docs`)

예전: View 모듈만 `view_model/main.py` (포트 8002), 재작성 모듈은 FastAPI 앱 없음 → 지금: 한 앱, 태그 순서 = 파이프라인 순서

| 단계 | 새 엔드포인트 | 예전 |
|---|---|---|
| system | `GET /health`, `GET /api/v1/system/paths` | `GET /health` |
| ⓪ 준비 | `POST /api/v1/rag/chunk-and-index` (+ `/status`) | [NEW] = 메타 프로필 → 표 색인 한 번에 |
| | `POST /api/v1/ingest/meta/profiles/build`, `GET …/meta/profiles`, `GET …/meta/profiles/{tbl_id}` | `/meta/...` |
| | `POST /api/v1/ingest/normalize/{tbl_id}`, `GET …/normalize/{tbl_id}/profile`, `GET …/dict/{name}` | `/normalize/...`, `/dict/{name}` |
| | `POST /api/v1/ingest/table-index/build`, `GET …/table-index/status` | `/search/index/build`, `/search/index/status` |
| ① 질의 | `POST /api/v1/rag/query-rewrite` → `bundle` + **`view_bundle`** | [NEW] (재작성 모듈 API 없었음) |
| | `POST /api/v1/rag/query-rewrite/trace`, `POST /api/v1/rag/query-adapt`, `GET /api/v1/rag/hcx-check` | [NEW] |
| | `POST /api/v1/rag/query-bundle`, `GET /api/v1/rag/query-examples` | `/query/bundle`, `/query/examples` |
| ② 검색·View | `POST /api/v1/rag/retrieve` | `POST /search` |
| | `POST /api/v1/rag/views` (입력 = ①의 `view_bundle`), `…/views/detail`, `…/pipeline/run` | `/views`, `/views/detail`, `/pipeline/run` |
| | `POST /api/v1/rag/hybrid-search` | [NEW] (= `python kosis_rag_qa.py search`) |
| ③ 답변 | `POST /api/v1/agent/answer` (입력 = ②의 Record 목록) | [NEW] |
| ★ 전체 | **`POST /api/v1/chat`** — ①→②→③ 한 번에, 단계별 결과·소요 시간 포함 | [NEW] |
| | `POST /api/v1/chat/legacy` | [NEW] (= `python kosis_rag_qa.py ask`) |
| ④ 데이터 | `POST /api/v1/data/source` — Record/source 좌표 → parquet 재조회 + 차트 | [NEW] |

**단계별 테스트**: query-rewrite 응답의 `view_bundle` 복사 → `/rag/views` 에 붙여넣기 → 응답 배열을 `/agent/answer` 의 `records` 에 붙여넣기

---

## 5. 모듈 사이 입출력 불일치와 보정

| # | 어디 | 문제 | 보정 (모듈 코드는 그대로) |
|---|---|---|---|
| 1 | ①→② QueryBundle | 재작성 모듈과 View 모듈의 QueryBundle 이 **이름만 같고 모양이 다름**. 시점 `'2025년'` vs `2025`, 연령 `['20~29세']` vs `{from,to}`, 비교축 목록 vs 문자열, 의도가 `intent` 에만 있음 → 그대로 넘기면 422 또는 View 종류가 항상 value | `query_analyzer/adapter.py` `to_view_bundle()` [NEW]. 월은 연도로, `전국` 은 빼서 기본값 사용, `증감→추이`·`구성비→비교`, View 모듈에 없는 슬롯(전출지·전입지·국적·조건·이동)은 notes 로 |
| 2 | ② 검색 문장 | View 모듈은 상위 질의를 `original`(구어체)로만 검색 → 재작성 결과('혼자 사는'→'1인가구')가 검색에 안 쓰임 | `QueryBundle.search_text` 필드 [NEW] + `views.units_of` 1줄 (`search_text` 없으면 예전과 동일) |
| 3 | ②→③ 답변 입력 | 기존 답변 `answer()` 는 records.jsonl 레코드(title·description·preview·chart)를 받는데, View 모듈 출력 Record 는 `{id, lexical_text, table, metadata, source}` | `light_agent.record_context()`·`answer_from_records()` [NEW] — 같은 프롬프트·숫자 검증(`verify_numbers`) 재사용 |
| 4 | Record → 차트 | Record 에 차트 스펙 없음 | `data_engine/chart_generator.chart_from_record()` [NEW] (view_type·변하는 분류로 line/bar/table) |
| 5 | Record.source → 재조회 | `source.period.in` 이 **연도**("2025")인데 `load_view` 는 `prd_de` 와 비교 → **월·분기표는 0행** (테스트에서 0행 → 24행 확인) | `data_engine/duckdb_client.load_record_data()` [NEW]: parquet 에 `year` 열이 있으면 연도로 거름. `load_view`·`build_view` 는 그대로 |
| 6 | 인덱스 meta.json | 레코드 경로를 실행 폴더 기준 상대 경로로 저장 → 폴더 이동 시 깨짐 | `indexer.load_records` 에서 `config.resolve_data_path()` [CHANGED 1줄] |
| 7 | API 서버 안정성 | `Index()` 가 인덱스 없을 때 `SystemExit` → 서버 요청에서 프로세스 종료 위험 | `fusion.Index` 는 `FileNotFoundError` 로 [CHANGED], 라우터는 `api/deps.guard()` 로 SystemExit·HCX 오류 → HTTP 409/502/503 |
| 8 | .env | 모듈마다 다른 위치에서 `load_dotenv` (cwd / 상위 폴더 override) | `core/config.py` 에서 한 번. 셸 환경변수 우선(override=False) |
| 9 | requirements | `rank-bm25` 를 import 하는데 루트 requirements 에 없음 | 추가 |

---

## 6. CLI 대응 (모두 저장소 루트에서)

| 예전 | 지금 |
|---|---|
| `python kosis_rag_builder.py catalog …` | `python -m backend.rag.ingestion.collector catalog …` |
| `python kosis_views.py prepare/views/enrich/render` | `python -m backend.rag.ingestion.view_builder prepare …` |
| `python kosis_rag_qa.py index/search/ask/compare/eval` | `python -m backend.agent.light_agent index …` |
| `cd view_model && python -m services.normalize --tables X` | `python -m backend.rag.ingestion.normalize --tables X` |
| `cd view_model && python -m services.meta_profile` / `table_text` / `views` / `search "…"` | `python -m backend.rag.ingestion.meta_profile` / `…ingestion.table_text` / `…ingestion.views` / `python -m backend.rag.retrieval.table_search "…"` |
| `cd Rewritten_fastapi && python scripts/run_eval.py` | `python eval/query_rewrite/scripts/run_eval.py` (또는 `python eval/run_eval.py rewrite`) |
| `uvicorn main:app --app-dir view_model --port 8002` | `uvicorn backend.main:app --reload --port 8000` |
| `streamlit run review_app.py` | `streamlit run eval/review_app.py` |
| 노트북의 `import kosis_rag_qa as kq` | `from backend.core import llm` (chat·embed) / `from backend.agent import light_agent` (answer 등) / `from backend.rag.retrieval.fusion import Index` — 노트북 파일은 기록용이라 수정하지 않음 |

---

## 7. 테스트

```bash
pytest -q        # 89 passed — 재작성 단위 테스트 86 + 통합 3 (HCX·네트워크 없음)
```
`tests/test_pipeline_e2e.py` 는 가짜 KOSIS 데이터(`tests/fake_kosis.py`: 연간·5년 주기·월간 표 3개)와 HCX 대역으로
경로 해석 → ⓪ → ① → ② → ③ → ★ `/chat` → 좌표 재조회 → legacy 하이브리드 까지 **Swagger 와 같은 HTTP 경로**로 확인합니다.
실제 데이터·HCX 로는 아직 돌려 보지 못했습니다 (키·데이터가 이 환경에 없음).
