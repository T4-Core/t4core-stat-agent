# api — FastAPI 서버 · Swagger

## 한눈에 보기

| | |
|---|---|
| **하는 일** | View 모듈의 각 단계를 HTTP 엔드포인트로 공개하고, 입출력 형식을 **Swagger(`/docs`)** 로 자동 문서화한다 |
| **왜** | 쿼리·판단 모듈 담당자와 형식(QueryBundle, Record, ViewResult)을 **Swagger 주소 하나로 공유**하고, 다른 모듈이 HTTP 로 부르거나 팀 공용 앱에 라우터를 합칠 수 있게 |
| **실행** | 저장소 루트에서 `.venv/Scripts/python.exe -m uvicorn main:app --reload --reload-dir view_model --app-dir view_model --port 8002` |
| **주소** | Swagger `http://localhost:8002/docs` · ReDoc `/redoc` · 스키마 원본 `/openapi.json` |
| **설치** | `uv pip install --python .venv/Scripts/python.exe -r view_model/requirements.txt` (이 `.venv` 는 uv 로 만들어 pip 가 없음) |

---

## 1. 구조: 로직(services)과 API(routers) 분리

```
요청 ─▶ routers/*.py  (얇은 층: 입력 검증·응답 형식·오류 코드)
            │ 함수 호출
            ▼
        services/*.py (로직: CLI 로도 실행 가능, API 를 몰라도 됨)
            │
            ▼
        output/ (산출물)
```

- **로직은 services 에만** 있다. 라우터는 서비스 함수를 부르고 결과를 스키마에 담기만 한다.
- **입출력은 모두 `schemas.py` 의 Pydantic 모델**. 형식이 틀린 요청은 로직에 닿기 전에 **422** 로 거부된다.

| 파일 | 역할 |
|---|---|
| `main.py` | FastAPI 앱 생성, 라우터 등록, `/health` |
| `schemas.py` | 입출력 스키마 + Swagger 예시 (쿼리 모듈 예시 1번·6번) |
| `routers/meta.py` | ⓪ 메타 프로필 |
| `routers/normalize.py` | ① 정규화 + 공유 사전 |
| `routers/query.py` | ② 슬롯 문자열 → dict (보조), 예시 12개 |
| `routers/search.py` | ③ 자연어 검색, 표 색인 만들기·상태 |
| `routers/views.py` | ④⑤ View 생성 (질의 하나 / 일괄) |

---

## 2. 엔드포인트

| 태그 | 메서드·경로 | 입력 | 출력 | 상태 |
|---|---|---|---|---|
| system | `GET /health` | — | 상태, 메타 프로필·표 색인 유무, 정규화된 표 수 | ✅ |
| ⓪ meta | `POST /meta/profiles/build` | — | `MetaBuildSummary` | ✅ |
| | `GET /meta/profiles?q=&kind=&limit=` | 검색어·분류 종류 | 표 요약 목록 | ✅ |
| | `GET /meta/profiles/{tbl_id}` | tbl_id | 메타 프로필 전체 | ✅ |
| ① normalize | `POST /normalize/{tbl_id}?force=&full=` | tbl_id | `NormalizeResult` | ✅ |
| | `GET /normalize/{tbl_id}/profile?full=` | tbl_id | 정규화 프로필 | ✅ |
| | `GET /dict/{name}` | region_dict / period_rules / symbol_dict / dim_kinds | 사전 JSON | ✅ |
| ② query | `POST /query/bundle` | `SlotQuery` | `QueryBundleResult` (슬롯 문자열 → dict) | ✅ |
| | `GET /query/examples` | — | 예시 12개 (View 모듈 입력 형식) | ✅ |
| ③ search | `POST /search` | `{query, top_k}` | `SearchResult` (후보 순위) | ✅ |
| | `POST /search/index/build` | — | 백그라운드 시작 | ✅ |
| | `GET /search/index/status` | — | 진행 로그, 색인 정보 | ✅ |
| ④ views ⭐ | `POST /views?top_k=&n_views=` | `QueryBundle` | `ViewResult` | ✅ |
| pipeline | `POST /pipeline/run` | `PipelineRequest` (비우면 예시 12개) | `PipelineResult` (+ `output/view_results.jsonl`) | ✅ |
| | `POST /views/detail` | `QueryBundle` | `ViewResult` (확인용: 후보 10개, 카드, 못 맞춘 조건 메모) | ✅ |

⭐ `POST /views` 가 판단 모듈로 넘길 묶음을 만드는 대표 엔드포인트.

### 오류 코드

| 코드 | 언제 |
|---|---|
| 404 | 카탈로그에 없는 표, 아직 정규화되지 않은 표, 메타 프로필 파일 없음 |
| 409 | 원본 CSV 가 없어 정규화 불가 / 표 색인이 아직 없음 / 색인을 이미 만드는 중 |
| 422 | 요청 형식이 스키마와 다름 (FastAPI 자동) |

---

## 3. 스키마 (`schemas.py`)

| 모델 | 누가 → 누구 | 핵심 필드 |
|---|---|---|
| `QueryBundle` | 쿼리 → View | `query_id`, `original`(자연어), `filters`(슬롯 dict), `sub_questions`(서브 자연어), `sub_filters`(서브 슬롯), `rewritten`(슬롯 문자열, 참고), `intent` |
| `Filters` | (QueryBundle 안) | 키 = 슬롯 이름: `시점`, `지역`, `대상`, `성별`, `연령{from,to}`, `지표`, `비교축`, `의도` |
| `Record` | View 하나 | `id`, `lexical_text`, `dense_text`, `doc_type`(= **view**), `parent_id`, `metadata`, `source` |
| `ViewItem` | | `record` + `data`(`columns`, `rows`, `n_rows`, `file`) |
| `Candidate` | 검색 후보 | `rank`, `tbl_id`, `tbl_nm`, `survey_nm`, `score`, `dense`, `bm25_rank`, `has_view` |
| `UnitResult` | 검색 단위 | `unit_id`(main / 서브 ID), `query`, `filters`, `candidates`, `views`, `notes` |
| `ViewResult` | View → 판단 | `query_id`, `original`, `filters`, `units` |

- `Filters.연령` 의 JSON 키는 `from` (파이썬 예약어라 코드에서는 `from_` 으로 받고 alias 로 `from`)
- 팀 공용 스키마(`common/schemas.py`)가 생기면 `QueryBundle`·`Record` 는 그쪽을 import 해서 쓴다

---

## 4. 다른 모듈과 연결하는 법

| 방식 | 하는 법 | 연결 확인 |
|---|---|---|
| 모듈별 서버 | 쿼리 8001 / **View 8002** / 판단 8003 으로 각자 실행, HTTP 로 호출 | 각 `/health`, 서로의 `/openapi.json` 스키마 비교 |
| 공용 앱에 합치기 | 팀 `app.py` 에서 `app.include_router(view_model.routers.views.router, prefix="/view")` | `/docs` 한 화면에 전 모듈, `TestClient` 로 통합 테스트 |

---

## 5. 변경 기록

| 날짜 | 내용 |
|---|---|
| 2026-11-02 | 정리: `routers/planned.py`(⑥ 검증 자리만 있던 파일)와 `ValidateResult` 삭제. `/views` 는 카드 목록, `/views/detail` 은 확인용 상세 |
| 2026-11-02 | 모듈 목적 정정에 맞춰 개편: 입력 = 자연어 + 슬롯 dict, 출력 = 판단 모듈용 `ViewResult`(Record doc_type=view 유지). `routers/search.py`·`routers/views.py` 추가, resolve·records export 스텁 삭제. version 0.2.0 |
| 2026-11-02 | ② 구현: `routers/query.py` (`POST /query/bundle`, `GET /query/examples`) |
| 2026-11-02 | FastAPI 0.162 · uvicorn 0.54 · httpx 0.28 설치 (uv). `services/`·`routers/`·`docs/` 로 재구성, `schemas.py`·`main.py`·⓪① 라우터 작성 |
