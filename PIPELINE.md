# 파이프라인 실행 가이드

수집 → 사전 준비(색인) → 서비스(Swagger) 까지 **무엇을 어떤 순서로 실행하는지** 정리한 문서입니다.
모든 명령은 **저장소 루트에서, 가상환경을 켠 상태로** 실행합니다.

```powershell
python -m venv .venv
.venv\Scripts\activate              # mac/linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                # KOSIS_API_KEY, HCX_API_KEY … 입력
python -m backend.core.config       # 데이터 경로 해석 결과 확인 (KOSIS_DATA_DIR 에 ✓)
```

---

## 전체 그림

```
[0] 수집 (collector) ─────────▶ storage/kosis_data/  (catalog.csv · meta/ · raw/)
        │
        ├─▶ [A] 메인 파이프라인 ─ POST /api/v1/chat
        │     A1 메타 프로필 → A2 표 BM25 색인                 (사전 실행 필요)
        │     A3 표 정규화(parquet) · 임베딩                   (질문할 때 자동 / 선택적으로 미리)
        │
        └─▶ [B] legacy 하이브리드 ─ POST /api/v1/chat/legacy, /api/v1/rag/hybrid-search
              B1 prepare → B2 views → (B3 enrich) → B4 BM25+Dense 인덱스
```

- **[A]** 가 현재 메인 경로입니다: 질의 재작성 → 표 검색(BM25 → bge-m3) → View 카드 → 답변
- **[B]** 는 예전 `kosis_views.py` + `kosis_rag_qa.py` 경로로, 비교·평가용으로 남겨 둔 것입니다
- 데이터 위치는 `backend/core/config.py` 가 자동으로 찾습니다 (환경변수 → `storage/` → 예전 위치). 자세한 표는 [MIGRATION.md](../MIGRATION.md) 3번

---

## [0] 수집 — 데이터를 새로 받거나 갱신할 때만

```powershell
python -m backend.rag.ingestion.collector catalog     # 목록 트리 → catalog.csv (전수/표본 판별)
python -m backend.rag.ingestion.collector schema      # 메타 → meta/*.json, table_schema.csv
python -m backend.rag.ingestion.collector download    # 수치 → raw/<조사>/*.csv (오래 걸림, 중단 후 이어받기)
python -m backend.rag.ingestion.collector status      # 조사별 진행 현황 → status.csv
```

| 옵션 | 내용 |
|---|---|
| `--surveys 인구총조사 …` | 특정 조사만 |
| `--root 인구 주거:주택총조사` | 여러 주제 폴더를 한 catalog 로 (`--append` 로 기존 catalog 에 추가만) |
| `--max-tables 20` | 테스트용 표 수 제한 |
| `--recent 5` | 표마다 최근 N 개 시점만 |
| `--max-cells N` | 예상 셀 수가 큰 표는 건너뛰고 `skipped_large.csv` 에 기록 |

- `build`, `store` 단계는 현재 A·B 파이프라인 모두 **사용하지 않습니다**
- catalog 나 meta 를 다시 만들었다면 아래 **A1·A2 를 다시** 실행합니다

---

## [A] 메인 파이프라인 (`POST /api/v1/chat`)

### 사전 실행 (처음 한 번 + catalog/meta/raw 가 바뀌었을 때)

| 단계 | 명령 | 입력 → 출력 | 시간 |
|---|---|---|---|
| **A1 메타 프로필** | `python -m backend.rag.ingestion.meta_profile` | catalog.csv(selected) + meta/*.json → `storage/parquet/meta_profiles.jsonl` | 약 10초 |
| **A2 표 BM25 색인** | `python -m backend.rag.ingestion.table_text` | meta_profiles → `storage/indices/table_index/` (ids · texts · tokens · meta) | 몇 초 |

- A1 + A2 = Swagger **`POST /api/v1/rag/chunk-and-index`** (진행: `GET /api/v1/rag/chunk-and-index/status`). 둘 중 하나만 하면 됩니다
- A2 는 **raw CSV 가 없는 표를 제외**합니다 → download 를 더 받았으면 A2 다시
- 확인: `GET /health` → `meta_profiles: true`, `table_index: true`

### 질문할 때 자동으로 되는 것

| 단계 | 언제 | 결과 위치 |
|---|---|---|
| ① 질의 재작성 | 질문마다 HCX 1회 | — |
| ② BM25 1단계 | 매번 (A2 색인) | — |
| ② Dense 재정렬 (bge-m3) | 검색 단위마다 후보 top_k 개만 HCX 임베딩, 한 번 계산한 건 재사용 | `storage/indices/embed_cache_view.sqlite` |
| ② 표 정규화 | **검색에서 처음 뽑힌 표만** 그때 parquet 변환 (지연 정규화) | `storage/parquet/processed/`, `profiles/` |
| ② View 카드 | 슬롯 조건으로 parquet 을 잘라 Record 생성 | `storage/parquet/views/*.csv` |
| ③ 답변 | HCX 1회 | `save: true` 이면 `kosis_data/answers/` |

### 선택: 미리 해 두면 좋은 것

**A3 정규화 미리 하기** — 큰 표(수백 MB)는 첫 질문에서 1분 넘게 걸리므로 시연 전에 권장

```powershell
# 특정 표만
python -m backend.rag.ingestion.normalize --tables DT_1B040A3 DT_1IN1503

# 원본이 그대로여도 다시
python -m backend.rag.ingestion.normalize --tables DT_1B040A3 --force

# 전체 (오래 걸림)
python -c "from backend.rag.ingestion.meta_profile import load_meta_profiles as L; from backend.rag.ingestion.normalize import ensure_normalized as N; from backend.data_engine.duckdb_client import connect; c=connect(); [print(p['tbl_id'], bool(N(c, p['tbl_id']))) for p in L() if p['raw']['exists']]"
```

- `normalize --tables …` CLI 를 한 번 실행하면 `storage/parquet/dict/` (region_dict · period_rules · symbol_dict · dim_kinds) 도 생성됩니다 → `GET /api/v1/ingest/dict/{name}` 에 필요
- Swagger 로는 `POST /api/v1/ingest/normalize/{tbl_id}` (표 하나)

**검색 순위만 확인** (임베딩만 호출, 답변 생성 없음)

```powershell
python -m backend.rag.retrieval.table_search "최근 5년간 대전의 인구 변화 추이"
```

**예시 12개 일괄 실행** → `storage/parquet/view_records.json`, `view_results.jsonl`

```powershell
python -m backend.rag.ingestion.views
```

---

## [B] legacy 하이브리드 파이프라인 (`/chat/legacy`, `/rag/hybrid-search`)

이미 `kosis_data/rag_views/` (records.jsonl) 와 `kosis_data/index/` 가 있으면 **다시 만들 필요 없습니다.**
`python -m backend.core.config` 에서 `RAG_VIEWS_DIR`, `RAG_INDEX_DIR` 에 ✓ 가 있으면 그대로 사용됩니다.

| 단계 | 명령 | 출력 | 비고 |
|---|---|---|---|
| **B1 정제** | `python -m backend.rag.ingestion.view_builder prepare` | `rag_views/processed/*.parquet`, `profiles/` | 선택된 표 **전체** 변환 → 오래 걸림 (`--surveys`, `--max-tables` 로 제한 가능) |
| **B2 레코드** | `python -m backend.rag.ingestion.view_builder views` | `rag_views/{tables,views,records}.jsonl` | kosis_data 에 `population_table_catalog.jsonl` 이 있으면 자동 결합. `--kiwi` 로 BM25 토큰 필드 추가 |
| B3 보강 (선택) | `python -m backend.rag.ingestion.view_builder enrich --out <폴더>` | 질문·동의어·요약 추가 | `.env` 에 `LLM_API_KEY`(+`LLM_BASE_URL`, `LLM_MODEL`). **`--out` 폴더의 views/records 를 덮어씀** → `rag_views` 를 `rag_views_enriched` 로 복사한 뒤 그 폴더를 `--out` 으로 |
| **B4 인덱스** | `python -m backend.agent.light_agent index --variant base` | `RAG_INDEX_DIR/base/{bm25.pkl, dense.npy, dense_owner.npy, meta.json}` | 레코드마다 HCX 임베딩 (캐시 → 중단 후 이어서). `--workers` 로 동시 호출 수, `--dense-mode multi` 로 질문별 벡터 추가 |
| 보강본 인덱스 | `python -m backend.agent.light_agent index --variant enriched --records storage/kosis_data/rag_views_enriched/records.jsonl` | `RAG_INDEX_DIR/enriched/` | |

CLI 확인·평가

```powershell
python -m backend.agent.light_agent search  "서울 인구 추이"                    # 검색만 (LLM 없음)
python -m backend.agent.light_agent ask     "최근 10년 서울 인구 어떻게 변했어?"
python -m backend.agent.light_agent compare "1인 가구 많은 지역은?"              # base vs enriched
python -m backend.agent.light_agent eval    --variant base --n 200               # Recall@k, MRR
python eval/run_eval.py retrieval --variants base enriched                      # 위 eval 을 변형별로
```

---

## 엔드포인트별 사전 조건

| 엔드포인트 | 필요한 것 |
|---|---|
| `GET /health`, `GET /api/v1/system/paths` | 없음 |
| `/api/v1/rag/query-rewrite`, `/rag/hcx-check` | `.env` HCX 키 |
| `/api/v1/rag/query-bundle`, `/rag/query-examples`, `/rag/query-adapt` | 없음 (HCX 호출 없음) |
| `/api/v1/rag/retrieve`, `/rag/views`, `/rag/views/detail`, `/agent/answer`, **`/chat`** | [0] + **A1 + A2** + HCX 키 |
| `/api/v1/ingest/meta/profiles…` | A1 |
| `/api/v1/ingest/normalize/{tbl_id}` | [0] + A1 |
| `/api/v1/ingest/dict/{name}` | `normalize --tables …` CLI 한 번 |
| `/api/v1/rag/hybrid-search`, `/chat/legacy` | [0] + B1 + B2 + B4 |
| `/api/v1/data/source` | 해당 표의 parquet (A: 질문하면 자동 / B: B1) |

---

## 처음 받은 팀원이 할 일 (요약)

```powershell
# 0) kosis_data 를 storage/kosis_data 에 두기 (또는 .env 의 KOSIS_DATA_DIR 로 지정)
python -m backend.core.config                       # KOSIS_DATA_DIR ✓ 확인
pytest -q                                           # HCX 없이 모듈 연결 확인 (89 passed)

python -m backend.rag.ingestion.meta_profile        # A1
python -m backend.rag.ingestion.table_text          # A2

uvicorn backend.main:app --reload --port 8000       # http://localhost:8000/docs
#   GET  /api/v1/rag/hcx-check   → check.ok: true
#   POST /api/v1/chat            {"question": "작년 대구의 남자 20대 인구 수", "today": "2026-11-02"}
```

### 자주 나는 오류

| 증상 | 원인 | 조치 |
|---|---|---|
| HTTP **409** | 표 색인·메타 프로필·인덱스 없음 | A1 + A2 (legacy 는 B4) |
| HTTP **503** | `.env` 에 키 없음 | `.env` 확인 후 서버 재시작 |
| HTTP **502** | HCX 호출 실패 (429·키·모델명) | `GET /api/v1/rag/hcx-check` |
| HTTP **422** | Body 형식 다름 | `/rag/views` 에는 `bundle` 이 아니라 **`view_bundle`** |
| 첫 질문이 매우 느림 | 큰 표의 지연 정규화 | A3 로 미리 정규화 |
| `pip install` 에서 `cp949` 오류 | Windows 인코딩 | `requirements.txt` 는 ASCII 로 유지, 또는 `$env:PYTHONUTF8=1` |


### streamlit 사용법
python eval/pipeline_review/review_80.py list                     # 찾은 세트·열 매핑·진행 현황
python eval/pipeline_review/review_80.py run --queries 80 --n 5   # 번호 | 이름 일부 | 경로로 선택
python eval/pipeline_review/review_80.py run --all --no-png       # 모든 세트
streamlit run eval/review_app.py