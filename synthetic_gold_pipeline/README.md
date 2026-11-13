# synthetic_gold_pipeline — KOSIS Multi-View Synthetic Golden Set 생성 파이프라인

KOSIS 원본 데이터와 **결정론적 Tool** 에서 정답을 먼저 확정하고, 그 Fact 를 정답으로 갖는 질문을 거꾸로 만드는
(Reverse Generation) 평가셋 생성기입니다. 기존 RAG 파이프라인(`backend/`, `eval/`, `configs/` …)과 **독립적으로**
동작하며, 기존 파일은 하나도 수정하지 않습니다. 모든 산출물은 `synthetic_gold_pipeline/outputs/` 아래에만 씁니다.

> LLM 은 연산 계획(JSON)·질문 문장·의미 검수만 담당합니다. 숫자는 LLM 이 만들지 않습니다.
> 모든 수치는 RAW 행 → DuckDB 조회 → Decimal 계산 결과이며, 원본 파일·행 번호·SQL·계산식으로 재현됩니다.

---

## 1. 기존 저장소 · KOSIS 데이터 구조 확인 결과 (feature/kos-14 기준)

| 확인 항목 | 결과 | 이 파이프라인에서의 처리 |
|---|---|---|
| `storage/kosis_data/` | git 에 **데이터 없음** (`storage/README.md`, `.gitkeep` 만) | 실제 데이터로는 검증하지 못함 → 가상 KOSIS 데이터(`demo_data.py`)로 검증 |
| 수집 구조 | `backend/rag/ingestion/collector.py` 기준: `catalog.csv`, `meta/<ORG>_<TBL>.json`(TBL·ITM·PRD·CMMT·SOURCE), `raw/<조사명>/<ORG>_<TBL>.csv`, `store/{tables.csv, dimensions.csv, data/*.parquet}` | 같은 구조를 그대로 읽는 Adapter 구현 (raw 가 없으면 store parquet) |
| RAW 컬럼 | `ORG_ID, TBL_ID, TBL_NM, C1~C8(+_OBJ_NM, _NM), ITM_ID, ITM_NM, UNIT_NM, PRD_SE, PRD_DE, DT, LST_CHN_DE` | C1 = 지역 가정 없음. OBJ_NM 키워드 + 메타 `OBJ_ID_SN` 으로 분류 의미 결정 |
| 기존 HCX Client | `backend/core/llm.py::chat(messages, schema, temperature, max_tokens, model)` — 토큰 사용량 미반환, 키 없으면 `SystemExit` | 같은 환경변수·요청 형식의 **신규 Adapter**(`HCXClient`) 기본 사용. 기존 함수 재사용(`hcx_repo`)도 선택 가능 (시그니처 확인 후 호출만) |
| 기존 View ID | 오프라인 `view::<표key>::<주기>::<번호>::<종류>` (`rag_views/views.jsonl`, `source` 좌표 포함), 온라인 v4 는 질의마다 생성 | `ViewMappingAdapter` 가 views.jsonl 의 `source` 좌표로만 매핑. 없거나 확인 불가면 `UNMAPPED` (추정 안 함) |
| 기존 평가셋 | `eval/golden_set/*.csv|jsonl`, `storage/test_data/kosis_rag_eval_80_*.csv` (`id,survey,test_type,target_module,question`) | 같은 5개 컬럼 질문 CSV 를 **신규 폴더에만** 생성 |

## 2. 디렉터리 구조

```text
synthetic_gold_pipeline/
├── configs/pipeline.yaml            모든 경로·임계값·비율·반올림 정책 (환경변수 ${VAR:-기본값} 지원)
├── schemas/                         Pydantic v2 계약: metadata · planning · calculation · verification · dataset
├── adapters/
│   ├── kosis_raw_adapter.py         RAW+meta → TableMetadata, 방식 B View 생성기(RawViewGenerator)
│   ├── stored_view_adapter.py       방식 A: <root>/<ORG>_<TBL>/*.csv|parquet 저장 View 직접 읽기
│   └── view_mapping_adapter.py      합성 View ↔ 원본 표 ↔ 좌표 ↔ 기존 RAG View ID
├── sampler/
│   ├── metadata_index.py            역색인 (지역·성별 등 코드, 표, 항목명, 주기·시점)
│   ├── index_cache.py               (추가) 표 단위 인덱스 캐시 — 표 하나 끝날 때마다 저장, 중단 후 이어서
│   ├── compatibility_graph.py       구조적/의미적 호환성, 연산 계열별 허용 여부와 이유
│   ├── view_cluster_sampler.py      2~3 View 클러스터 + Hard Negative 후보
│   └── unanswerable_sampler.py      (추가) 답변 불가 5개 유형 생성기
├── tools/                           LLM 없이 동작하는 결정론적 Tool
│   ├── units.py                     (추가) 단위·스케일·결측 기호 파싱
│   ├── calculation_tool.py          Atomic Calculator + SQL 안전성 + DuckDB TableCalculationEngine
│   ├── statistical_validation_tool.py  계획/결과의 통계 적합성 (재시도 가능 vs 즉시 폐기)
│   ├── evaluation_tool.py           수치 검증·Ablation·View 판정·Retriever/Generator 지표·실패 진단
│   └── deduplication_tool.py        Fact Signature + Jaccard + TF-IDF
├── agents/
│   ├── llm_client.py                Mock / HCX(신규) / HCX(기존 함수) / OpenAI 호환
│   ├── planner_agent.py             한국어 가드레일 프롬프트 → OperationPlan
│   ├── reverse_qa_agent.py          자리표시자 기반 질문·모범 답변 역생성
│   └── quality_verifier_agent.py    의미 검수 (결정론적 실패를 뒤집을 수 없음)
├── record_builder.py                (추가) 최종 GoldenRecord 조립 (module_eval M1/M2/M3 포함)
├── main_pipeline.py                 asyncio Orchestrator · 체크포인트 · 보고서
├── score_rag_results.py             (추가) 기존 review_v4 실행 결과(results.json) 채점
├── demo_data.py                     가상 KOSIS 데이터 (아래 사례 표)
├── tests/                           unit + E2E (92개)
├── examples/                        Demo 실행 산출물 예시 (JSONL·CSV·보고서)
└── outputs/                         실행 산출물 (git 제외, 폴더 뼈대만)
    metadata_index/ generated_views/ intermediate_facts/ rejected_samples/ checkpoints/ datasets/ reports/
```

요청 구조에 없던 파일(`utils.py`, `record_builder.py`, `tools/units.py`, `sampler/unanswerable_sampler.py`,
`tests/conftest.py`, `examples/`)은 공용 기능을 한 곳에 두기 위해 추가했습니다.

## 3. 처리 흐름

```text
RAW/Meta (+저장 View)  →  MetadataIndex(역색인) → CompatibilityGraph(지연 계산·캐시)
  → ViewClusterSampler(Taxonomy 사전 할당, seed=f(base_seed, attempt)) → PlannerAgent(LLM, OperationPlan)
  → StatisticalValidator.validate_plan ─(구조 오류: 오류를 붙여 최대 2회 재요청 / 통계·데이터 오류: 즉시 폐기)
  → TableCalculationEngine(샘플마다 새 DuckDB 연결, 외부 접근 차단) → validate_result
  → Ablation(View 하나씩 제거 + 남은/전체 View 의 같은 Fact 탐색, 엔진 재실행으로 확인) → View 판정
  → ReverseQAGeneratorAgent(숫자 대신 {FINAL},{V1},{T1}… 자리표시자, 결정론적 검사 후 재요청)
  → 모범 답변 = LLM 문장(치환) + 근거·계산식 블록(Tool 값) → Evaluation Tool 수치 자기검증
  → QualityVerifierAgent(의미 검수) → Dedup(배치마다 attempt 순서로 순차) → 저장
  → 답변 불가 레코드 (최종 답변 가능 레코드 수 기준 10~15%)
```

### Taxonomy · 하위 유형
| 유형 | 하위 유형 | View | 예 |
|---|---|---|---|
| SIMPLE_LOOKUP (쉬운 셋 전용) | LOOKUP | View 1개 (SINGLE_TABLE_SINGLE_VIEW) | 2024년 서울 총인구 |
| TIME_SERIES_COMPARISON | GROWTH_RATE · DIFFERENCE · PP_DIFFERENCE | 같은 표·항목 2시점 (SINGLE_TABLE) | 대구 총인구 2023→2024 증감률 |
| CROSS_TABLE_RATIO | SHARE(같은 단위 계열, %) · RATE_PER(천 명당) | 서로 다른 표 (MULTI_TABLE) | 경제활동인구(천명) ÷ 주민등록 총인구(명) |
| CONDITIONAL_AGGREGATION | FILTER_SUM/COUNT/MEAN/TOP_K · RATIO_TOP_K · CLASS_DIFF_COUNT · FILTERED_GROWTH_TOP(3 View) | 지표 + 조건 View | 혼인건수 ≤ 기준인 시도의 여자인구 합계 |
| UNANSWERABLE_ABSTENTION | CONTEXT · CORPUS · AMBIGUOUS · OUT_OF_SCOPE · FUTURE_OBSERVATION | — | 2018년(미수록) 경제활동인구 |

### 주요 결정론적 규칙 (발췌)
- 결측 기호 `- * X NaN "" NULL` 은 0 으로 바꾸지 않음 → 필요한 값이면 즉시 폐기. 0·음수는 유효값.
- 단위: (계열, 배수) 관리. 같은 계열만 변환·합산 (천명→명 ×1000). %/%p 구분, 비율 단위 단순 합산·평균 금지.
- 다른 주기(월 202401 vs 분기 202401), 실측/추계, 시나리오, 모집단(예: 외국인 vs 주민등록) 혼합 금지.
- 총계·소계(이름 패턴 또는 하위 코드 보유) 벡터 집계에서 제외, 계층 깊이 혼합 시 재시도 요구.
- Join: 같은 코드의 이름이 다르면 코드 체계 불일치로 폐기, 같은 좌표 중복 행 → 행 증폭으로 폐기 (DuckDB 로 행 수 vs 고유 키 수 비교).
- 구성비는 분모가 분자를 포함해야 함 (분모 항목명 규칙 + 분류 조건 비교, 계산 후 100% 초과 시 폐기).
- 순위·최댓값은 표시 자릿수에서 동점이면 정답이 하나가 아니므로 폐기. 필터가 모든/어떤 원소도 고르지 않으면 재시도·폐기.
- 질문은 필수 시점·지역·분류 조건(시나리오·성별 등)·기준값을 모두 포함해야 통과. 정답 값이 질문에 노출되면 폐기.
- 수치 검증: 값(허용 반올림 자릿수)·단위·부호/증감 방향·중간값·값↔연도/지역 연결(가장 가까운 앞쪽 시점 표기)·뒤바뀜·근거 없는 숫자.

### 쉬운 평가셋 (`configs/pipeline_easy.yaml`)

`pipeline.yaml` 을 바탕으로(`extends`) 바뀐 값만 적은 설정입니다. 출력은 `outputs_easy/` 로 따로 나옵니다.

| 바뀐 것 | 값 |
|---|---|
| 유형 비율 | 단순 조회 1.0 · 두 시점 비교 0.7 (CSV 1개) · 두 표 비율 0.4 (CSV 2개) · 조건부 집계 0 |
| 답할 수 없는 문항 | 0 (검색 평가에는 답할 수 있는 문항만 씀) |
| View 거르기 | 2015년 이후 시점만 (`min_year`) · 분류 조건 1개 이하 · 항목 이름 20자 이하 · 연도 구간으로 쪼갠 표 묶음 제외 (`exclude_table_title_patterns`, 예 '…(2007~2015)') |
| 단순 조회 지역 | 전국(30%) 또는 시도 이름 코드. 시도가 없는 표에서는 이름이 겹치는 시군구('중구')를 고르지 않음 |

```bash
python -m synthetic_gold_pipeline.main_pipeline --config synthetic_gold_pipeline/configs/pipeline_easy.yaml --mode real --target-count 60
python -m table_card_search.alt_gold --golden synthetic_gold_pipeline/outputs_easy/datasets/synthetic_gold_dataset.jsonl   # 대체 정답
python -m table_card_search.compare --golden synthetic_gold_pipeline/outputs_easy/datasets/synthetic_gold_dataset.jsonl \
    --alt synthetic_gold_pipeline/outputs_easy/datasets/alt_positives.jsonl --dense hcx none --name easy
```

기본 설정(`pipeline.yaml`)은 단순 조회 비율이 0 이라 예전과 같은 어려운 셋을 만듭니다.

## 4. 설치 · 실행

```bash
# 저장소 루트에서
pip install -r synthetic_gold_pipeline/requirements.txt

# Demo Mode (API 키 불필요, Mock LLM)
python -m synthetic_gold_pipeline.main_pipeline --config synthetic_gold_pipeline/configs/pipeline.yaml --mode demo --target-count 10

# Real Mode (실제 KOSIS 데이터 + HCX). .env 의 HCX_API_KEY / HCX_BASE_URL / HCX_MODEL / HCX_APP_TYPE 사용
python -m synthetic_gold_pipeline.main_pipeline --config synthetic_gold_pipeline/configs/pipeline.yaml --mode real \
    --data-root storage/kosis_data --target-count 100

# 중단 후 이어서 (같은 데이터 스냅샷이어야 함)
python -m synthetic_gold_pipeline.main_pipeline --config synthetic_gold_pipeline/configs/pipeline.yaml --mode real --resume

# 실제 데이터 처리만 먼저 확인 (LLM 없이)
python -m synthetic_gold_pipeline.main_pipeline --mode real --data-root storage/kosis_data --llm-provider mock --target-count 10

# 테스트
python -m pytest synthetic_gold_pipeline/tests -q
```

Windows · VS Code (PowerShell 터미널, 저장소 루트):
```powershell
py -m pip install -r synthetic_gold_pipeline\requirements.txt
py -m synthetic_gold_pipeline.main_pipeline --config synthetic_gold_pipeline/configs/pipeline.yaml --mode demo --target-count 10
py -m synthetic_gold_pipeline.main_pipeline --mode real --data-root storage/kosis_data --target-count 100
py -m pytest synthetic_gold_pipeline\tests -q
```
### 메타데이터 인덱스 캐시
- 표 하나를 처리할 때마다 `outputs/metadata_index/cache/tables/<표>.json` 에 바로 저장합니다.
  두 번째 실행부터는 바뀌지 않은 표를 다시 읽지 않고, **인덱싱 중간에 끊겨도 끝난 표부터 이어서** 진행합니다.
- 원본 RAW/parquet·메타 JSON 의 (크기, 수정 시각), catalog 행, View 생성 설정(adapter·input), View 파일 존재가 모두 같을 때만 캐시를 씁니다.
  하나라도 다르면 그 표만 다시 읽습니다. 로그에 `캐시 사용 N, 새로 읽음 M, 무효 {...}` 로 표시됩니다.
- 전부 다시 읽기: `--rebuild-index`. 원본 해시까지 다시 확인: `index.verify_source_hash: true`. 끄기: `index.cache_enabled: false`.
- 원본 파일을 복사하거나 git checkout 하면 수정 시각이 바뀌어 그 표는 다시 읽습니다 (안전한 쪽으로 동작).

### 인덱싱 속도
- 캐시가 없는 표는 RAW CSV 전체(모든 행)를 읽습니다. 실제 코드·시점·중복 행·결측을 확인하고 View 스냅샷 해시를 만들기 위해서입니다.
  원본 SHA-256 은 97MB 파일 기준 약 0.3초로 병목이 아닙니다.
- 최적화: (1) `max_views_per_table` 로 남길 View 만 골라 생성 (버릴 View 는 계산·저장 안 함),
  (2) 캐시 안 된 표를 여러 프로세스로 병렬 처리 (`index.workers: auto` = min(4, CPU-1), `1` = 순차),
  (3) 결측 판정·스냅샷 해시를 pyarrow 컬럼 연산으로, 표를 한 번만 정렬해 View 를 복사 없이 자름.
  최적화 전후 인덱스 내용(View 메타·표 메타·순서)이 같음을 비교 확인했습니다 (View ID 의 해시 부분만 형식 변경 → 캐시 형식 v2).
- 측정 (2코어 환경): 78만 행 표 1개 19.6초 → 5.6초 / 12.6만 행 표 16개 65.9초 → 순차 18.7초, 작업자 4개 9.8초 / 캐시 재실행 0.4초.
- 작업자 수만큼 표가 동시에 메모리에 올라갑니다. 큰 표가 많고 메모리가 부족하면 `index.workers` 를 줄이세요.
- pandas 의 pyarrow CSV 엔진은 `dtype=str` 이어도 코드 앞자리 0 을 지워(`00000`→`0`) 사용하지 않습니다.

추가 옵션: `--output-root`, `--seed`, `--concurrency`, `--max-attempts`, `--max-api-calls`, `--llm-provider {mock,hcx,hcx_repo,openai_compat}`.
경로는 YAML·환경변수(`SGP_KOSIS_DATA_ROOT`, `SGP_OUTPUT_ROOT`)·CLI 로만 지정하며 절대 경로를 코드에 넣지 않았습니다.

## 5. 산출물

| 파일 | 내용 |
|---|---|
| `outputs/datasets/synthetic_gold_dataset.jsonl` | 전체 레코드 (정답·원본 좌표·SQL·계산식·검증 결과·module_eval) |
| `outputs/datasets/synthetic_gold_queries.csv` | `id,survey,test_type,target_module,question` 5개 컬럼만. original/paraphrased 각각 별도 ID(`-O`/`-P`) |
| `outputs/datasets/synthetic_gold_answers_references.csv` | 평가자 전용 정답·참고 (질문 CSV 와 `id` 로 연결, RAG 입력 금지) |
| `outputs/reports/generation_report.json` | 시도 수·단계별 성공률·중복 폐기율·Ablation 통과율·분포·API 호출/지연/토큰·실패 사유·부족 사유 |
| `outputs/rejected_samples/rejected_samples.jsonl`, `outputs/reports/validation_errors.jsonl` | 폐기 샘플과 원인, 마지막 연산 계획 |
| `outputs/reports/run_manifest.json` | seed·설정 해시·데이터 스냅샷 ID·git commit·출력 파일 해시 (API 키 미기록) |
| `outputs/intermediate_facts/<sample>.json` | 샘플별 연산 계획 + 계산 결과 (재실행으로 같은 정답 재현) |

**N(목표 개수) = Fact 레코드 수** 입니다 (`run.target_count_unit: fact_records`). 질문 CSV 의 행 수는 2N.
예시는 `examples/` 참고 (Demo 10건 실행 결과).

## 6. 기존 RAG 로 실행하고 채점하기

기존 코드는 수정하지 않습니다. RAG 실행은 기존 `eval/pipeline_review/review_v4.py`(또는 `review_v4.ipynb`)로 하고,
채점은 이 폴더의 `score_rag_results.py` 로 합니다.

```bash
# 1) RAG 실행 — 질문 CSV 경로를 넘기면 같은 폴더의 synthetic_gold_answers_references.csv 를 자동으로 짝지어 읽음
#    (문항마다 HCX 로 쿼리 분석. 수치 답변까지 보려면 --answer: 문항당 HCX 1회 추가)
python eval/pipeline_review/review_v4.py run --queries synthetic_gold_pipeline/outputs/datasets/synthetic_gold_queries.csv
python eval/pipeline_review/review_v4.py hits --queries synthetic_gold_pipeline/outputs/datasets/synthetic_gold_queries.csv

# 2) 채점 (결과: synthetic_gold_pipeline/outputs/reports/rag_eval/<실행 이름>/)
python -m synthetic_gold_pipeline.score_rag_results --rag-results storage/eval_runs/synthetic_gold_queries__v4/results.json
#    --variants paraphrased   일상어 질문만 · --k 1,3,5,10 · --diag-k 5 (진단·비교에 쓸 K)
```

- 정답 CSV 의 `gold_table_ids` 는 기존 도구가 읽는 형식(`DT_A, DT_B`)이라 `review_v4.py hits` 가 **정답표 기준**으로 동작합니다
  (전에는 JSON 목록이라 정답 표를 못 읽고 조사명 일치로 대신 셌습니다. JSON 은 `gold_table_ids_json` 열).
- `score_rag_results.py` 가 추가로 보는 것:

| 지표 | 의미 |
|---|---|
| `Table_Any/All_Hit@K`, `Table_Coverage@K`, `Table_MRR` | 필수 근거 그룹마다 허용 표(대체 표 포함)가 어느 검색 단위 top-K 에 있는가. All = 모든 그룹 (복합 질문) |
| `View_All_Hit`, `Final_Context_All_Hit` | RAG 가 만든 View·최종 문맥의 **source 좌표(표·항목·시점·분류 코드)** 가 필수 원본 좌표를 모두 포함하는가 |
| `query_ok` | 쿼리 분석이 시점·지역 조건을 맞게 뽑았는가 |
| `ans_Numeric/Unit/Intermediate_Fact_Accuracy`, `Abstention_Accuracy` | `--answer` 로 돌렸을 때 답변 수치 채점 |
| `first_failure`, `root_cause` | 단계별 최초 실패 (QUERY_CONDITION_ERROR → RETRIEVAL_MISS/PARTIAL_RETRIEVAL → VALUE_MISMATCH → VIEW_CONDITION_ERROR → FINAL_CONTEXT_MISS → CALCULATION/ANSWER_GENERATION/ABSTENTION_ERROR) |
| `original_vs_paraphrased.csv` | 같은 정답의 공식(-O)/일상어(-P) 결과 비교 → `ORIGINAL_ONLY` = 쿼리 변환 의심 |

- 출력: `per_question.csv`(문항별), `summary.json`(전체·유형별·hop 별·변형별 평균, 실패 분포), `original_vs_paraphrased*.csv`.
- **실제로 확인한 것**: 기존 `review_v4.run_one` 을 기존 테스트용 가짜 HCX(`tests/fake_kosis.py`)로 데모 질문 20개에 돌린 실제
  `results.json` 을 채점했습니다. 기존 hits 는 정답표 기준 hit@5 0.9, View_hit 0.8 이었지만, 좌표 기준으로는
  최종 문맥이 필요한 원본 좌표를 모두 담은 비율이 0.33 이었습니다 (예: 분모 View 를 총인구 대신 여자인구로 만듦,
  시도별 집계가 필요한데 전국 값만 만듦). 가짜 HCX 의 슬롯 품질 탓이 크므로 실제 HCX 결과는 다를 수 있습니다.
- 한계: 대체 Positive 가 다른 표일 때 좌표 판정은 원래 근거 표 좌표 기준이라 보수적입니다. 기존 v4 View 는 월·분기 자료도
  기간을 연도로 적어 시점 판정은 연도 단위입니다.

## 6-1. 평가 함수 (직접 호출)

```python
from synthetic_gold_pipeline.tools.evaluation_tool import evaluate_retrieval, evaluate_generation, diagnose_failure
evaluate_retrieval(record, retrieved_view_ids=[...], retrieved_table_ids=[...], ks=(1, 3, 5))
# view_/table_ Hit@K · Any/All Hit@K · Requirement Coverage@K · Recall@K · MRR · NDCG@K
# (대체 Positive 그룹 반영, UNJUDGED 는 오답으로 세지 않고 순위에서 제외, 조사명 일치는 Hit 아님)
evaluate_generation(record, answer_text, pred_claims=None, pred_coordinates=None, pred_operation=None)
# Numeric/Unit/Intermediate Fact/Evidence Coordinate/Operation/Answer Completeness/Abstention
diagnose_failure(record, run_log)   # 최초 실패 단계 + 추정 근본 원인, 로그 없으면 INSUFFICIENT_TRACE
```

## 7. 구현 · 테스트 상태 (정직한 구분)

**구현되어 실제로 테스트한 것** — `python -m pytest synthetic_gold_pipeline/tests -q` → **92 passed** (가상 KOSIS 데이터 + Mock LLM)
- Adapter: DT_/INH_ 표 ID, meta 없는 표, store parquet 전용 표, 저장 View(원본 행 번호 유지), C1=시나리오·C2=지역 표
- 호환성: 월/분기 같은 PRD_DE 거부, 실측/추계 거부, 코드 체계 충돌, 중복 행 위험, 다른 표 시계열 거부
- 계산: Decimal 원자 연산, 결측 기호 비변환, 0·음수 유지, 분모 0, 행 증폭, 코드 체계 불일치, 천명→명, %p 규칙, SQL 안전성·DuckDB 샌드박스
- 통계 검증: 재시도 가능/불가 분류, 총계 중복, 비가산 합산, 정당화 안 된 가중평균, 좁은 분모, 모집단 비호환, 100% 초과
- 평가: 값↔연도 잘못 연결(실제로 생성 중 발견했던 버그의 회귀 테스트), 부호·단위·반올림 정책, 근거 없는 숫자, 뒤바뀜, Retriever/Generator 지표, 실패 진단, Dedup
- E2E: 20건 생성, 질문 CSV 5컬럼·정답 비노출, 모든 원본 좌표가 실제 RAW 행 값과 일치, 저장된 계획 재실행으로 같은 정답, 답변 불가 10~15%,
  재개(resume) 중복 없음, 동시성 4 vs 1 결과 동일, 목표 미달 시 무한 반복 없이 부족 사유 보고, Self-Correction 재시도 경로 통과
- 인덱스 캐시: 두 번째 실행 결과가 처음과 완전히 같음, 5번째 표에서 강제 중단 후 재실행 시 끝난 4개 표는 캐시 사용,
  원본 수정·View 파일 삭제·설정 변경 시 해당 표만(또는 전부) 다시 읽음, 병렬(spawn)·순차 결과 동일,
  벡터화 결측 판정이 parse_value 와 같은 결과
- RAG 결과 채점: 정상·필수 그룹 누락·분류 코드 누락·일상어만 실패 사례에서 지표와 진단이 기대대로 나옴, 정답 CSV 를 기존 도구 규칙으로 읽음
- hop 판정: 대체 Positive 를 포함해 한 표로 모든 근거를 채울 수 있으면 SINGLE_TABLE (CROSS_TABLE_RATIO 면 폐기)
- Real Mode 경로: 실제 데이터 폴더 구조를 가상 데이터로 `--mode real --llm-provider mock` 실행 확인, 키 없을 때 인덱싱 전에 명확한 오류로 종료

**구현했지만 이 환경에서 검증하지 못한 것**
- 실제 HCX API 호출 (`HCXClient`, `RepoHCXClient`) — API 키·네트워크가 없어 요청/응답 형식은 기존 `backend/core/llm.py` 를 따라 구현만 함.
  특히 HCX Structured Output 이 펼친 JSON Schema(`inline_refs`)를 받아들이는지, `result.usage` 필드명은 실제 호출로 확인 필요.
- 실제 KOSIS 데이터(약 2,300표) 규모의 성능·메모리. 실제 표의 분류명이 키워드 규칙(`adapter.dimension_keywords`)에 맞는지.
- 실제 LLM 이 만든 계획·질문의 품질. Demo 의 Planner/ReverseQA/Verifier 는 **규칙 기반 Mock** 이며 품질 검증이 아닙니다.
  그래서 Demo 레코드는 모두 `verification_status = NEEDS_HUMAN_REVIEW` 로 기록됩니다.
- OpenAI 호환 Client, `sql_plan`(LLM SQL) 실행 경로 (검증기만 테스트, 기본 비활성).

**남은 한계**
- 모집단(population_scope)·실측/추계 판정은 조사명·표 이름 키워드 규칙 기반입니다. 규칙에 안 맞으면 `UNSPECIFIED` + 경고로 남깁니다.
- 구성비 분모 판정은 항목명 패턴 + 분류 조건 비교라 의미적으로 완전하지 않습니다 (계산 후 100% 초과 검사로 일부 보완).
- View 단위는 (항목 × 시점 [+ 성별·시나리오 분할]) 입니다. 대용량 표는 `input.max_views_per_table`(최근 시점 우선)로 줄이며 View 마다 파일을 씁니다.
- Compatibility Graph 는 View 3,000개 이하에서만 전부 계산·저장하고, 그 이상은 역색인으로 후보를 찾아 필요할 때 계산합니다.
- CORPUS_UNANSWERABLE 은 "수집된 스냅샷 기준" 판정입니다 (미수집 KOSIS 표에는 있을 수 있음을 레코드에 기록).
- 답변 불가 질문 문장은 템플릿이며 LLM 의역을 쓰지 않습니다. 기존 RAG View 매핑은 views.jsonl 의 `source` 좌표가 있을 때만 가능합니다.

## 8. 기존 RAG 파이프라인 개선 권고 (직접 수정하지 않음)

1. `backend/core/llm.py::chat` 이 토큰 사용량(`result.usage`)을 버립니다 → 반환값에 usage 를 함께 주면 비용 추적이 가능합니다.
   키가 없을 때 `SystemExit` 대신 예외를 던지면 상위에서 처리하기 쉽습니다.
2. 온라인 v4 View ID(`view::표key::주기::질문ID-순위::종류`)는 질의마다 달라 평가셋과 고정 매핑이 어렵습니다 →
   `source` 좌표(표·항목·분류 코드·시점) 해시를 View 에 함께 기록하면 `ViewMappingAdapter` 로 정확 매핑할 수 있습니다.
3. `eval/golden_set/kosis_rag_eval_50.*` 의 `gold_table_ids`·`gold_answer` 가 비어 있습니다 → 이 파이프라인의 정답 CSV
   (`synthetic_gold_answers_references.csv`)와 같은 형식으로 채우면 같은 Evaluation Tool 로 비교할 수 있습니다.
