# backend.rag.search — 표 검색 (v5)

질문 원문에서 조건을 읽고, 표 전체에 여러 채널 점수를 매겨 합친 뒤, 표 구조로 가능성 계수를 곱하는 검색입니다.
`table_cards`·`table_card_expend`·`table_card_search`·`table_search_v5`를 이 폴더 하나로 합쳤습니다.

## 1. 측정 결과 (retrieval_golden.jsonl 89문항, 11-13 실행 — 이번 수정 **이전** 코드)

| 구성 | Hit@1 | Hit@5 | Hit@10 | MRR | 합친 후보 50 안 정답 |
|---|---|---|---|---|---|
| baseline[hcx] | 0.348 | 0.573 | 0.640 | 0.437 | 0.753 |
| table_card_expend[hcx] | 0.326 | 0.539 | 0.596 | 0.414 | 0.753 |
| v5[none] | 0.427 | 0.719 | 0.798 | 0.541 | 0.809 |
| **v5[hcx]** | **0.494** | **0.775** | 0.820 | **0.615** | **0.888** |
| v5_expend[hcx] | 0.483 | 0.742 | 0.832 | 0.585 | 0.843 |

- 같은 질문에서 한쪽만 Hit@5: baseline 3 · v5 21 (hcx).
- 정답 표가 코퍼스에 없는 문항이 4건이라 Hit 의 상한은 0.955 입니다 (`DT_1PM…`·`DT_1PA…`·`DT_1PH…`).
- 카드 글(`v5_expend`)은 표 설명문(`v5`)보다 낫지 않았고(한쪽만 Hit@5: 1 대 4) hcx 실행에 1,297초가 걸려 뺐습니다.
- 아래 3절의 변경은 이 표에 반영돼 있지 않습니다. 다시 측정해야 합니다.

## 2. 그 실행에서 본 문제

**쿼리 모듈** — 89문항 중 슬롯을 낸 것은 41건.

| 상태 | 건수 | 원인 | 조치 |
|---|---|---|---|
| `error:IndexError` | 13 | `validate.py`: 지표 없이 대상만 있는 개념이 있으면 로그 문장을 만들다 죽음 | 수정 + soft 모드에서는 어떤 오류든 코드 추출 값으로 진행 |
| `needs_clarification` | 30 | 시점·지역이 없으면 멈춤 (`시도별 이혼 건수`, `가구 통계`) | `clarify_mode: soft` — 없는 시점은 최신, 지역은 전국으로 두고 검색. 되묻기 후보는 `clarifications`에 그대로 |
| `out_of_scope` | 5 | `조출생률 통계 어디서 봐?`, `이사하는 이유로 제일 많은 게 뭐야?`를 범위 밖으로 판정 | 질문에 통계 용어(CSV 값 사전·일상어 사전)가 있으면 뒤집음 |
| `ok` 이지만 틀림 | — | `5세별` → 연령 5세, `1995년부터 5년마다` → 1995 하나, 비교축 `국적취득연도별` | 연령 구간 표기 제외, 끝없는 기간 펼치기, 포함 일치는 값을 바꾸지 않음 |

**검색 (v5[hcx] Hit@5 실패 20건)** — 코퍼스에 없음 4, 일상어 7(`수도권으로 몰리는`, `시집온`, `몇 살에 죽는지`), 표 구조 4(`40대 남성 이혼` → 연령 분류 없는 표, `시군구 성별 인구` → 수준, `태어난 아이` → 세부 교차표가 먼저), 시점 3(`상반기`, `1995년부터`, `2005년과 2025년`), 6위에 걸린 것 2.

## 3. 지금 구조

```
질문 원문 ── query.py ──▶ 시점 · 출생연도 · 주기(월·분기·반기) · 시도 · 시군구 · 지역 수준(시군구별) · 연령/성별을 물었는가
                          군말 제거('알 수 있는 자료') · 일상어→통계어 (configs/colloquial.yaml + term_dict)
        │
        ├─ channels.py ─▶ 표 전체(약 1,100개)에 채널 점수
        │     dense  임베딩 (HCX bge-m3)            가중 1.6   ← 1단계부터 BM25 와 함께, 어휘 채널보다 크게
        │     value  질문 속 표현 = 어느 표의 항목·분류 값인가   1.6
        │     title  표 이름이 질문에 들어 있는가        1.4
        │     lex    Kiwi BM25 (표 설명문)             1.0
        │     ngram  글자 2·3-gram BM25              0.8
        │     + 재작성 문장으로 같은 채널 (보조)
        ├─ 가중 RRF
        ├─ router.feasibility ─▶ × 표 구조 계수
        │     시점   하나도 못 담음 0.12 / 일부 담음 0.6 + 0.4 × 비율 / 다 담음 1.0   (실제 수록 연도 기준)
        │     주기 · 시군구 이름 · 지역 수준 · 시도 · 연령 분류 · 성별 분류 · 조사 이름 · 질문이 안 쓰는 분류 수
        ├─ siblings.py ─▶ [11-16] 형제 표 해소: 같은 조사·같은 통계의 (계)/(남)/(여)·전국/시도/시군구판·연도판 무리 안에서
        │                질문 좌표(성별 · 지역 수준 · 연도)에 맞는 표를 무리의 가장 앞 자리로 (무리 사이 순서는 그대로)
        ├─ (분모 단위) [11-16] '인구'·'가구' 뿐인 하위 질의 또는 filters.역할 = 분모 → 그 말이 제목·항목에 있는
        │                단순한 표 × 본 질의 1위 표와 같은 조사면 1.5
        └─ (선택) llm_rerank.py ─▶ 상위 12개(+ 상위 5개 무리의 빠진 형제 4개)를 표 구조 요약으로 HCX 가 다시 줄 세움
                         카드에 '형제 A: 성별 … · 수준 …' 표시. LLM 뒤에 형제 규칙을 한 번 더 (무리 안의 선택은 규칙)
```

`facets.py`가 표 구조를 읽습니다. CSV 값 사전(`python -m backend.rag.csv_index build`)이 있으면 실제 수록 연도·분류 값 전부·시군구 이름 전부를, 없으면 메타 프로필을 씁니다.

### 제안하신 방향에 대한 판단

| 제안 | 판단 | 적용 |
|---|---|---|
| BM25 + dense 를 한 번에, dense 에 가중치를 더 | 타당. 측정에서 dense 를 붙이면 concept 문항의 후보 50 안 정답이 0.59 → 0.91 | 기본 `dense: hcx`, 가중 1.0 → 1.6. 정확한 값은 `tune`으로 |
| CSV 의 지역(행)·대상(열) 구조를 먼저 검사해 필터링 | 방향은 타당하나 **걸러 내기(제외)는 하지 않음**. 메타가 틀리거나 질문 해석이 틀리면 정답이 사라지고 되돌릴 수 없음 | 구조 불일치는 곱하는 계수로 (연령·성별·지역 수준·주기 추가) |
| 필터링된 결과를 LLM 설명으로 다시 리랭킹 | 타당. Hit@10 0.82 대 Hit@1 0.49 — 10위 안에서 순서를 바로잡을 여지가 큼 | `llm_rerank.py`. 미리 만든 설명문 대신 구조 요약을 그때 조립. 기본은 꺼 둠(질의 단위마다 HCX 1회) |
| 표를 고른 뒤 연도를 탐색, 일부만 있어도 줌 | 절반만 타당. 같은 이름의 연도판(1985·1990·1995 총조사 표)은 연도가 표를 고르는 기준이라 연도를 뒤로 미룰 수 없음 | 연도는 순위에 남기되, 일부만 담은 표를 0.6 이상으로 살림. View 는 있는 연도만 주고 없는 연도를 메모로 남김(기존 동작) |

## 4. 실행

```bash
python -m backend.rag.csv_index build                    # 권장

python -m backend.rag.search "2023년 서울 40대 남성 이혼 건수"            # 순위·채널별 순위·계수가 깎인 이유
python -m backend.rag.search --llm --no-analyze "수도권으로 사람들이 얼마나 몰리는지"

python -m backend.rag.search.compare --golden tests/retrieval_golden.jsonl --methods baseline v5 --dense hcx --llm
python -m backend.rag.search.tune --golden tests/retrieval_golden.jsonl --split dev --dense hcx \
    --cache <compare 실행 폴더>/analysis_cache.jsonl
```

- `compare` 결과는 `storage/runs/search_compare/<시각>_compare/`. `--llm`을 주면 `v5+llm` 구성이 함께 나옵니다.
- 쿼리 모듈을 고쳤으므로 **이전 `analysis_cache.jsonl`을 재사용하지 말고** 새 폴더로 실행하세요.
- 서비스 경로: `views.run_query`의 기본 검색이 v5 입니다(`/chat`·`/rag/views`·`build_viewset` 공통). 예전 검색으로 돌리려면 환경변수 `TABLE_SEARCH=legacy`.
- LLM 재정렬을 서비스에서 켜려면 `configs/search.yaml`의 `llm_rerank.enabled: true`.

## 5. 확인한 것과 못 한 것

확인함 (`pytest tests` 134건 통과, HCX·실데이터 없음)
- `tests/search/test_search.py`: 실패 유형을 줄인 27개 표 코퍼스 — 재작성에서 사라진 값, 질문 속 표 이름, 출생연도, 연도판·시도판, 분기·반기, 구조 계수(연령·성별·지역 수준·간결), 일부 연도, LLM 재정렬(가짜 응답·오류·캐시)
- `tests/v4/test_fix_1113.py`: 규칙 추출 → 접지 → 분석(strict/soft, 범위 밖 뒤집기, 재작성 오류) → 검색 → View
- `tests/query_analyzer/test_fix_1113.py`: IndexError 재현, `5세별`, `1995년부터 5년마다`

확인하지 못함
- **3절 변경 뒤의 실제 Hit·MRR.** 구조 계수·dense 가중·일상어 사전은 실패 20건을 보고 정한 값이라, 그 20건에 맞춘 것일 수 있습니다. `tune`의 held-out(test 60문항) 점수로 확인하세요.
- **LLM 재정렬의 실제 효과와 HCX 응답 형식.** 가짜 응답으로만 돌렸습니다.
- **soft 모드에서 HCX 가 실제로 내는 슬롯.** 분석 테스트는 손으로 만든 슬롯을 넣었습니다.

## 6. 정리한 파일

지움
- `table_cards/` `table_card_expend/` `table_card_search/` — 비교 도구(`compare.py`·`alt_gold.py`)만 이 폴더로 옮김
- `kosis_fetch/` — `table_card_expend`의 표본 표 다운로드에만 쓰임
- `backend/rag/query_analyzer/{rewriter,decomposer,filter_extractor}.py`, `backend/rag/retrieval/reranker.py` — 어디서도 import 하지 않는 10줄 안팎의 자리 표시 파일
- `check_subquery.py` `pipeline_v4_e2e_preview.html` `kosis_pipeline.mmd` `오늘 정리.md` `notebooks/why/`
- `tests/query_analyzer/test_against_saved.py` — 저장된 프롬프트 기록과 현재 프롬프트가 달라 브랜치에서 이미 실패하던 테스트

남김 (지워도 된다고 하셨지만 손대지 않은 것)
- `backend/`의 legacy 경로(`view_builder.py`, `light_agent.py`의 하이브리드 검색, `backend/rag/retrieval/`의 실험실) — `/chat/legacy`·`/rag/hybrid-search`·`/retrieval-lab` API 가 import 합니다. 엔드포인트를 없앨지는 서비스 쪽 결정이라 그대로 뒀습니다. `baseline` 비교도 여기에 기댑니다
- `eval/` — `query_bundles.json`·`kosis_rag_eval_50.jsonl`을 실험실과 테스트가 읽습니다
- `PIPELINE.md`·`RETRIEVAL_LAB.md`·`description_md/` — `docs/` 아래 같은 이름의 문서와 내용이 달라 어느 쪽이 최신인지 판단할 수 없었습니다
- `synthetic_gold_pipeline/` — 골든셋 생성기

## 7. 11-16 수정 (P0~P3)

| | 무엇 | 어디 |
|---|---|---|
| P0 | 원문 표현(`question_terms`)은 낱말 경계 + 같은 이름만 (`(반)지하`·`(t+3년)변화`·`0명`·시도 이름이 들어가던 문제) · 검색 문장의 숫자 조각·반복 단어 빼기(`resolve.tidy_query`) · '요즘' = 자료의 최신 연도(`base_year_mode: data`) · 지역 모양 값('안동군')을 지표로 옮기지 않음 | `query_analyzer/v4/lexicon.py`, `pipeline.py`, `ingestion/resolve.py`, `csv_index/store.py` |
| P1 | 형제 표 해소 | `search/siblings.py`, `router.py` |
| P2 | 분모(`…중 비율`·`…로 나눈`·`천 명당`)·조건(`…가 N명 이상`) 검색 단위 + 분모 단위 검색 | `query_analyzer/v4/roles.py`, `router.py` (`roles`) |
| P3 | LLM 카드에 형제 표시 · 형제 끼워 넣기 · LLM 뒤 형제 규칙 | `llm_rerank.py`, `router.py` |
| P4 | 일상어 사전 캐내기 (O·P 문항 쌍, dev 레코드만) → 사람이 골라 `configs/colloquial.yaml` 에 · 보류 문항 대리 지표 | `colloq_mine.py`, `configs/colloquial.yaml` |
| P5 | 개념 카탈로그 (대체 정답으로 확인된 '같은 값 표' 묶음, dev 레코드만) → LLM 후보에 끌어오고 카드에 '같은 값 묶음' 표시 | `concepts.py`, `router.py`, `llm_rerank.py` |
| 평가 | 합성 셋도 dev / heldout 으로 나눔 (`splits.py`, `compare --split heldout`) — P4·P5 를 캐낸 문항과 평가 문항을 가름 | `splits.py`, `compare.py` |

```bash
# P4: 후보 만들기 → 사람이 고름 → 보류 문항으로 확인
python -m backend.rag.search.colloq_mine mine --golden <합성 셋…> --per-query <compare 폴더>/per_query.csv --out colloquial.candidates.yaml
python -m backend.rag.search.colloq_mine eval --golden <합성 셋…> --extra colloquial.candidates.yaml
# P5: 개념 카탈로그 (alt_gold.py 결과로)
python -m backend.rag.search.concepts build --alt <alt_positives.jsonl…> --golden <합성 셋…>
python -m backend.rag.search.concepts show
# 평가는 보류 문항으로
python -m backend.rag.search.compare --golden <합성 셋> --alt <alt_positives.jsonl> --split heldout --methods v5 --dense hcx --llm
```

끄기: `configs/search.yaml` 에 `siblings: {enabled: false}` · `roles: {enabled: false}` · `llm_rerank: {add_siblings: 0}`,
`configs/query_v4.yaml` 에 `role_units: false` · `base_year_mode: fixed`, `concepts: {enabled: false}` (또는 concepts.json 을 지움).

## 8. 남은 일

1. 다시 측정 → `tune` → `configs/search.yaml`
2. 정답 표가 코퍼스에 없는 4문항: 표를 수집하거나 골든셋에서 뺌
3. 반기·분기·월: 검색은 주기를 보지만 View 는 연도 단위로만 자릅니다 (`2024년 상반기 혼인 건수` → 2024년 연간 값)
4. 조건부 집계(`가구원수 99,000명 이상인 지역의 …`)는 View 가 임계값으로 거르지 못합니다
