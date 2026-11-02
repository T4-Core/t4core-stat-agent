# build_view.py · views.py — ④ View 생성 → Record(doc_type="view") → 판단 모듈용 묶음

> **카드 모양 변경 (2026-11-02 오후)** — 받는 쪽 예시에 맞춤. 아래 2장(Record 표)은 이전 모양 기록이다.
>
> | 칸 | 내용 |
> |---|---|
> | `id` | `view::표key::주기::질문ID-순위::종류` (예: `view::101_DT_1B040A3::Y::12-1::trend`, 서브쿼리는 `6-1-2`). 종류 = 의도: 추이 → trend, 비교·순위 → breakdown, 값 조회 → value |
> | `lexical_text` | 표 이름 · 조사명 · 적용 조건 · 항목 · 단위 |
> | `table` | 자른 표 `{columns, rows}` 전체 행 (columns = 시점, 분류들, 항목, 값) |
> | `doc_type` | `view` |
> | `parent_id` | `table::표key` (문자열) |
> | `metadata` | survey_nm, category, survey_type, view_type, prd_se, prd_from, prd_to, is_latest, unit, geo_level, n_points, items, dims(코드를 2개 이상 고른 분류) |
> | `source` | table_key, file, org_id, tbl_id, prd_se, itm_id, dims `{c1: {codes}}`, period(추이·전체 기간이면 `{}`, 아니면 `{in: [연도]}`), kosis_url |
>
> dense_text·dense_vectors·질문 정보·notes 는 카드에 넣지 않음 (notes 는 상세 결과 `view_results.jsonl` 에만).
> 출력: 카드 목록 하나 `output/view_records.json` (예시 12개 → 48장), API `POST /views`(목록), `POST /views/detail`(상세), `POST /pipeline/run`.

## 한눈에 보기

| | |
|---|---|
| **하는 일** | 검색으로 찾은 표마다 **슬롯 dict** 조건으로 raw CSV(정제 parquet)를 잘라 **View** 를 만들고, View 하나를 **Record(doc_type = "view")** 로 만든다. 질의와 View 들을 엮어 판단 모듈로 넘긴다 |
| **입력** | `QueryBundle`: `original`(자연어) + `filters`(슬롯 dict) + `sub_questions`(서브 자연어) + `sub_filters`(서브 슬롯 dict) |
| **출력** | `ViewResult` = `{query_id, original, filters, units: [{unit_id, query, filters, candidates(10), views: [{record, data}], notes}]}` |
| **실행** | API `POST /views` (질의 하나), `POST /pipeline/run` (예시 12개 → `output/view_results.jsonl`) · CLI `cd view_model && ../.venv/Scripts/python.exe -m services.views` |
| **코드 위치** | `services/build_view.py`(View 하나), `services/views.py`(질의 하나·일괄), API `routers/views.py` |

```
QueryBundle
  │ units_of(): 검색 단위 = main(자연어 original, 슬롯 filters) + 서브쿼리 각각(자연어, 슬롯)
  ▼ 단위마다
search(자연어) → 후보 10개
  │ 상위 3개마다
  ▼
build_view(표, 슬롯)
  ① ensure_normalized(표)            raw CSV → 정제 parquet (처음 한 번, 이후 캐시)
  ② 슬롯 → 그 표의 실제 코드          시점·지역·성별·연령·지표/대상
  ③ parquet 에서 잘라 View           output/views/<id>.csv
  ④ Record(doc_type="view")
  ▼
ViewResult (질의 + 단위별 후보 + View Record·데이터) ──▶ 판단 모듈
```

---

## 1. 슬롯 → 코드 조건 (`build_view.py`)

| 슬롯 | 규칙 | 표에 없을 때 |
|---|---|---|
| 시점 | 요청 연도만. 비었으면: 의도 `추이` = 전체 기간, 그 외 = **조건에 실제 값이 있는 가장 최근 연도** | 없는 연도는 notes. 모두 없으면 최신 연도 + notes |
| 주기 | 연간(Y) 우선 → 다년(F) → 부정기 → 반기 → 분기 → 월 | — |
| 지역 | 표준명이 같은 코드. 같은 표준명이 여럿이면 상위(depth 작은) 하나 (세종·울산 중복 방지). 동/읍/면부 제외 | notes + 기본값(전국) |
| 비교축 | `시도`·`지역` = 시도 전체, `시군구` = 시군구 전체 (표준명 중복 제거) | notes + 기본값 |
| 지역 없음 | 전국(합계) | — |
| 성별 | 성별 분류가 있으면 그 코드. 없으면 **다른 분류 코드 이름**(`기대수명 - 남`) → **항목 이름**(`남자인구수`) 순서로 | notes "성별 구분 없음" |
| 성별 없음 | 성별로 나뉜 코드·항목은 빼고 합계 쪽만 (예: 인구수 → 총인구수만) | — |
| 연령 | 범위 안의 코드 중 **가장 잘게 나뉜 것들** (20~29세 → 20~24세 + 25~29세). 범위를 빈틈없이 덮는지 검사 | notes "정확히 덮는 코드 없음" |
| 지표·대상 | 그 밖의 분류 코드 이름과 항목 이름에서 단어로 찾음. `…수` 로 끝나면 앞부분으로도 (인구수 → 인구) | 분류는 기본값(합계·중위·첫 코드) + notes, 항목은 12개 이하면 전체 아니면 합계 항목 + notes |
| 시나리오 | 지표로 안 걸리면 기본값(중위), notes 없음 | — |

**원칙**
- 표에 없는 조건은 억지로 맞추지 않고 `metadata.notes` 에 남긴다 → 판단 모듈이 "조건을 못 맞춘 View" 를 알 수 있다
- 숫자는 parquet 에서만. 설명문(`dense_text`)에는 숫자를 넣지 않는다
- 슬롯 → 코드 규칙은 메타데이터 초안 기준이라 바뀔 수 있다. 규칙은 `match_period`, `match_level`, `match_items`, `pick_sex`, `age_codes` 에만 있다
- View 최대 5000행 (넘으면 잘라내고 notes), 응답에는 앞 200행 (전체는 CSV)

## 2. Record (doc_type = "view")

| 필드 | 내용 | 예 (12번, `DT_1B040A3`) |
|---|---|---|
| `id` | `질의ID::단위ID::표ID` | `12::main::DT_1B040A3` |
| `lexical_text` | 조사·표 이름·조건·항목·단위를 단어로 | 주민등록인구현황 행정구역(시군구)별, 성별 인구수 시점 2021~2025, … 총인구수 명 |
| `dense_text` | View 를 문장으로 | 주민등록인구현황의 「행정구역(시군구)별, 성별 인구수」 통계표에서 시점 2021~2025, 행정구역(시군구)별 대전광역시 조건으로 총인구수(명) 값을 가져온 View입니다. |
| `doc_type` | 항상 `view` | `view` |
| `parent_id` | View 를 만든 표 | `["table::101_DT_1B040A3"]` |
| `metadata` | 질의(`query_id`, `unit_id`, `query`, `filters`), 검색(`rank`, `score`, `dense`, `bm25_rank`), 표(`tbl_id`, `tbl_nm`, `survey_nm`), View(`prd_se`, `year_from/to`, `units`, `applied`, `n_rows`, `notes`) | `applied = {시점: 2021~2025, 행정구역(시군구)별: [대전광역시], 항목: [총인구수]}` |
| `source` | 다시 조회하는 좌표: 정제 parquet 경로 + `prd_se`, `years`, `itm_id`, `dims{c1: [코드]}` | `{file: processed/101_DT_1B040A3.parquet, dims: {c1: ["25"]}, …}` |

View 데이터(`data`)는 Record 옆에 따로: `columns`, `rows`(앞 200행), `n_rows`, `file`(전체 CSV).

## 3. 묶음 (`views.py`)

| 함수 | 하는 일 |
|---|---|
| `units_of(bundle)` | 검색 단위 만들기: `main` + 서브쿼리 각각. 서브 슬롯이 없으면 상위 슬롯을 씀. `filters` 가 없고 `rewritten` 만 있으면 파싱 |
| `run_query(bundle, top_k=10, n_views=3)` | 단위마다 검색 → 상위 3개 View → Record. View 하나가 실패해도 나머지는 계속 (notes) |
| `run_examples()` | 예시 12개 (`data/slot_queries.json`) 일괄 |
| `save_results()` | `output/view_results.jsonl` (한 줄 = 질의 하나) |

- 후보 10개 중 **상위 3개만 View** 를 만든다 (큰 표는 처음 정규화에 1분 이상). 나머지 7개는 `candidates` 에 순위·점수만. API 의 `n_views` 로 바꿀 수 있다
- 서브쿼리가 있으면 **상위 질의와 서브쿼리를 모두** 검색 (6번 = main, 6-1, 6-2)
- 예시 12개의 서브쿼리 자연어는 베이스라인 문장. 11번처럼 베이스라인에 서브쿼리가 없으면 슬롯 값을 이어 붙인 문장(예: "기대수명 추이")으로 검색하고 notes

---

## 4. 시험 결과 (2026-11-02, 검색 없이 표를 지정해 View 생성 로직만)

| 질의 | 표 | View |
|---|---|---|
| 12 대전 5년 추이 | `DT_1B040A3` | 대전광역시 총인구수 2021~2025, 5행 |
| 2 대구 인구 | `DT_1B040A3` | 대구광역시 총인구수 2025, 1행 |
| 1 대구 남자 20대 | `DT_1B04005N` | 대구광역시 × 20~24세·25~29세 × 남자인구수 2025, 2행 |
| 5 2023 시도별 인구 | `DT_1B040A3` | 17개 시도 (세종 중복 없음) × 2023 |
| 8 남녀 기대수명 | `INH_1B8000F_02` | 기대수명 - 남 80.8 / - 여 86.6, 2024 (notes: 2025는 값이 없어 2024) |

### 시험 중 고친 것
1. 지표 `인구수` 가 총·남자·여자 인구수에 모두 걸림 → 성별을 묻지 않으면 성별로 나뉜 항목 제외
2. 성별이 분류 코드 이름 끝(`기대수명 - 남`)에 있는 표에서 "성별 구분 없음" 으로 잘못 기록 → 분류 코드에서도 성별을 찾음
3. 최신 연도 2025 가 `-` 로만 채워진 표 → "최신" = 조건에 실제 값이 있는 가장 최근 연도

## 4-1. 전체 실행 결과 (2026-11-02, 검색 → View → Record, 예시 12개)

| 항목 | 값 |
|---|---|
| 질의 / 검색 단위 / View | 12 / 16 (6·11번은 main + 서브 2개) / **48** |
| doc_type | 48개 모두 `view` |
| View 생성 실패 | 0 |
| 빈 View | 1 (`1::main::DT_1MI8506`: 1985년 자료만 있는 표, notes 에 사유) |
| 새로 정규화한 표 | 33개 (원본 약 489MB, 표당 0.1~1.4초) |
| 최대 행 수 | 113 |
| notes 가 있는 View | 30 / 48 (요청 시점 없음, 시도 코드 없음, 연령 범위, 시나리오 기본값 등) |
| 저장 | `output/view_results.jsonl` (한 줄 = 질의 하나), View CSV `output/views/` |

대표 View:

| View | 적용 조건 → 결과 | notes |
|---|---|---|
| `6::6-2::DT_1B82A01` | 대구광역시 · 계 · 사망자수 · 2025 → 17,279명 | 없음 |
| `3::main::INH_1B8000F_01` | 출생아수(명) · 1970~2025 (추이) → 56행 | 없음 |
| `8::main::DT_1BPA201` | 중위 · 남자(A)/여자(B) · 기대수명 · 2072 → 89.5 / 92.7 | 없음 (장래 표라는 판단은 판단 모듈 몫) |
| `12::main::DT_1IN0001_25` | 대전광역시 · 2010 → 1,490,158명 | 요청 2021~2025 는 이 표에 없음 (수록 1990~2010) |
| `11::main::DT_1BPA403` | 높은 출산율 · 인구(천명) · 2022~2072 | 중위 시나리오가 없어 첫 코드 사용 |

### 전체 실행 중 고친 것
4. **시나리오가 지표에 걸림**: 시나리오 이름 `높은 출산율 추계(… 기대수명-중위 …)` 에 '기대수명' 이 들어 있어 6개 시나리오가 모두 선택 → 1428행. 시나리오는 지표로 고르지 않고 기본값(중위) 하나. 중위가 없으면 notes
5. **성별 코드 `남자(A)`·`여자(B)`**: 괄호 표기 때문에 '남자' 와 불일치 → 끝 괄호를 떼고 비교 (`sex_name`)
6. **항목이 하나뿐인 표**: "맞는 항목 없음 → 항목 전체" notes 가 37개 View 에 붙어 잡음 → 항목이 하나면 notes 없음 (37 → 17)

---

## 5. 변경 기록

| 날짜 | 내용 |
|---|---|
| 2026-11-02 | 예시 12개 전체 실행 (View 48). 위 4~6 수정 |
| 2026-11-02 | 작성. 표 하나 확정(resolve) 설계를 버리고, 검색 상위 3개마다 View + Record(doc_type=view). 위 1~3 수정 |
