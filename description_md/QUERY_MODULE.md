# 쿼리 모듈 v4 + CSV 값 사전 (Step 2)

> 기존 v3(재작성·슬롯) 출력과 View 입력 `QueryBundle` 은 그대로이고, 그 위에 **원본 CSV 근거**로 동의어·접지·되묻기·서브쿼리를 더했다.
> `status=ok` 응답의 `view_bundle` 은 기존 `POST /api/v1/rag/views` 에 그대로 들어간다.

## 처음 한 번

```bash
pip install -r requirements.txt                       # pyyaml 추가
python -m backend.rag.csv_index build                 # 원본 CSV 스캔 → storage/csv_index/  (이후엔 바뀐 표만)
python -m backend.rag.csv_index summary
uvicorn backend.main:app --reload                     # Swagger: ⓪ CSV 값 사전 (v4) · ① Query 질의 분석 v4
```

## 흐름

```
질문 ─ 1-1 재작성 v3 (HCX 1회, 기존 그대로) ─ 슬롯(문자열) · 하위 슬롯 · 의도
     ├ (대상·지표가 비면) 질문 문장 × CSV 값 사전으로 보충
     ├ 시점 규칙: 시점이 '명시'되지 않았으면 최근·요즘 → 2026년 / 추이·변화 → 2022~2026년
     ├ 1-2·1-3 동의어 조회 + 슬롯 접지 (CSV 값 사전)
     ├ 1-4 필수 슬롯(시점·지역·대상) — 빠지면 status=needs_clarification + 후보(options) → 멈춤
     ├ 1-5 서브쿼리 (표 단위)
     └ 1-1 검색 문장 + view_bundle
```

| 단계 | 코드 | 근거 |
|---|---|---|
| CSV 값 사전 | `backend/rag/csv_index/` (`source` → `scanner` → `store`) | 원본 CSV 의 헤더, `C{i}_OBJ_NM`(열 머리), `C{i}`·`C{i}_NM`(분류 값), `ITM_ID`·`ITM_NM`·`UNIT_NM`(항목·단위), `PRD_SE`·`PRD_DE`(기간). 메타 JSON 은 주석·조사명만 |
| 1-2 동의어 | `query_analyzer/v4/lexicon.py` | learned(승인된 학습 사전) → rule_dict(지역·성별 등 규칙 슬롯에만) → CSV 정확·표기 변형 → term_dict → CSV 포함 일치 → 비슷한 이름(제안만) |
| 1-3 접지 | `query_analyzer/v4/grounding.py` | 시점=그 해 자료가 있는 표, 지역=지역 분류 값, 연령=겹치는 연령 코드가 있는 표, 대상·지표=CSV 항목·분류 값 |
| 1-4 되묻기 | `query_analyzer/v4/clarify.py` | 후보: 지역=대상 표들의 실제 지역(전국 → 시도), 시점=그 표들의 실제 연도, 대상=비슷한 CSV 이름 |
| 1-5 서브쿼리 | `query_analyzer/v4/decompose.py` | v3 하위 질문이 있으면 그대로 / 없으면 지표들을 **함께 가진 표**가 CSV 값 사전에 없을 때만 지표별 분리 |
| 검색 문장 | `query_analyzer/v4/search_text.py` | `v3`(기본): v3 문장에서 지역·시점 빼고 CSV 표준 이름 보강 / `llm`: HCX 로 한 번 더 |
| 전체 | `query_analyzer/v4/pipeline.py` `analyze()` | 단계마다 `StepTrace`(params·출력·초) |

## 결정 사항 (Step 1 질의응답)

- **대상 필수 슬롯**: `대상` 또는 `지표` 중 하나라도 CSV 의 **행 값(항목·분류 값)** 에 접지되면 충족. 표 이름에만 있으면 충족 아님
- **시점 2026 규칙**: 표에 2026년이 없어도 되묻지 않음. 슬롯에 `note: 2026년 자료가 있는 표가 없음` 을 남기고 View 단계의 최신 자료 대체에 맡김
  - 질문에 시점이 명시(연도·작년·최근 N년·월·분기 …)되면 v3 해석 그대로. '최근 3년' → 2023~2025 (v3)
- **CSV 범위**: 값 사전은 raw 폴더 전체를 스캔하고, 조회는 `csv_scope: selected`(지금 검색 대상과 같은 catalog.csv selected 표)가 기본
- **대상·지표 값 바꾸기**: 사전(rule·learned·term) 또는 CSV 정확 일치일 때만 View 입력 값을 CSV 이름으로 바꿈. 표기 변형('인구수' → '인구')·포함 일치는 원래 값 유지 (근거는 `slots[].csv`)

## API (Swagger)

| 경로 | 설명 |
|---|---|
| `POST /api/v1/csv-index/build` | 값 사전 만들기 (`scope`, `limit`, `force`, `workers`) |
| `GET /api/v1/csv-index/summary` · `/values?slot=지역` · `/find?text=출생아 수` · `/tables/{tbl_id}` | 조회 |
| `POST /api/v1/rag/v4/analyze` | ★ 질문 → `QueryAnalysis` |
| `POST /api/v1/rag/v4/clarify` | `selections` + `previous`(직전 응답 전체) → 이어서 분석 (HCX 다시 안 부름) |
| `POST /api/v1/rag/v4/lexicon/lookup` · `/learn` · `GET /lexicon/pending` | 동의어 확인·학습 사전 |
| `POST /api/v1/rag/v4/decompose` | 슬롯 → 서브쿼리 (HCX 없음) |
| `GET /api/v1/rag/v4/settings` | 지금 설정 |

### 되묻기 왕복 예

```jsonc
// POST /api/v1/rag/v4/analyze {"question": "출생아 수 알려줘"}
{"status": "needs_clarification",
 "clarifications": [
   {"slot": "시점", "reason": "시점이 없음 …", "options": [{"option_id": "시점-range", "value": "2021~2025년", …}, {"value": "2025년", …}]},
   {"slot": "지역", "reason": "지역이 없음", "options": [{"value": "전국", "n_tables": 3, …}, {"value": "서울특별시", …}]}],
 "state": {…}, "trace": […]}

// POST /api/v1/rag/v4/clarify {"question": "출생아 수 알려줘", "previous": <위 응답 전체>,
//                              "selections": {"지역": ["대전광역시"], "시점": ["2025년"]}}
{"status": "ok", "view_bundle": {"filters": {"시점": [2025], "지역": ["대전광역시"], "지표": ["출생아수"], …}, "search_text": "출생아수"}}
```

## 설정 (`configs/query_v4.yaml`, 요청마다 `overrides` 로 일부 변경)

`base_year` · `trend_years` · `recent_words` · `trend_words` · `required_slots` · `n_options` · `csv_scope` · `contain_min_len` ·
`fuzzy_cutoff` · `search_text_mode` · `split_when_no_common_table` · `max_sub_queries` · `save_runs`

## 기록·평가

- 응답 `trace`: 단계마다 `{step, params, output, notes, seconds}`
- `save_runs: true` (또는 `Tracer(save=True)`) → `storage/runs/<run_id>/params.json · steps.jsonl · result.json`
- 실험 노트북: `notebooks/v4/query_v4_steps.ipynb` (단계별 함수를 따로 불러 설정을 바꿔 가며)

## 테스트

`tests/v4/test_query_v4.py` — 가짜 KOSIS 데이터 + HCX 대역, Swagger 와 같은 HTTP 경로:
값 사전(열·분류 종류·연도·주석·증분 스캔) → 동의어(띄어쓰기·term_dict·rule_dict·포함·제안·학습 승인) → 접지 → 시점 규칙 3종 →
되묻기 왕복(HCX 1회) → 서브쿼리 3종(공통 표 없음·있음·대상 흡수) + v3 하위 질문 → 범위 밖 → **view_bundle 을 기존 /rag/views 에 그대로**

## 다음 (Step 3 · 4)

- Step 3: `retrieval/` 인터페이스·Factory·YAML 구성 (토크나이저·임베더·리랭커 교체) + 실행 결과를 **사람이 나란히 비교**하는 검토 출력
- Step 4: 서브쿼리별 View 묶음 + Point 충돌 판정 + 선택지(주석은 csv_index `footnotes`, 설명은 표 구조) + 선택 API
