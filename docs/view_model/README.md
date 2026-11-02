> **[이동됨]** 이 문서는 예전 폴더(`view_model/` · `Rewritten_fastapi/`) 기준입니다. 코드는 `backend/` 아래로 옮겨졌고 엔드포인트는 통합 Swagger(`uvicorn backend.main:app`, `/api/v1/...`)에 있습니다. 경로 대응표는 저장소 루트의 `MIGRATION.md`.

# view_model — View 모듈 (FastAPI)

> 담당: 김연서 (View 모듈) · 시작: 2026-11-02
> 쿼리 모듈이 보낸 **자연어 + 슬롯 dict** 로, 자연어는 메타데이터 검색(bge-m3 + BM25)에, 슬롯은 raw CSV 에서 View 를 자르는 데 쓴다.
> 질의·서브쿼리마다 **View 여러 개**를 만들어 질의와 엮어 **판단 모듈**(자연어와 View 가 잘 연관됐는지 판단)로 넘긴다.
> 엔드포인트마다 `docs/<이름>.md` 에 **요약 → 코드 설명 → 변경 기록**을 누적한다.

## 실행

```bash
.venv/Scripts/python.exe -m uvicorn main:app --reload --reload-dir view_model --app-dir view_model --port 8002
```

Swagger: `http://localhost:8002/docs` — 데스크톱 앱에서는 브라우저 패널의 `view-api`(`.claude/launch.json`)로도 띄울 수 있다.
패키지 설치(최초 1회, 이 `.venv` 는 uv 로 만들어 pip 가 없음):

```bash
uv pip install --python .venv/Scripts/python.exe -r view_model/requirements.txt
```

처음 한 번: `POST /meta/profiles/build`(10초) → `POST /search/index/build`(설명문 + BM25 토큰, 약 10초)

## 전체 흐름

```
[사전 준비, 질의와 무관]
⓪ meta_profile    카탈로그 992개 메타 → meta_profiles.jsonl (메타데이터)
   table_text      메타데이터 → 표 설명문 989개 → bge-m3(HCX) 임베딩 + BM25 토큰 → table_index/

[쿼리 모듈] 자연어 + 슬롯 dict (서브쿼리도 자연어 + 슬롯)
      │
      ▼  검색 단위 = 상위 질의 + 서브쿼리 각각
③ search          자연어 → bge-m3 + BM25 → RRF → 메타데이터 상위 10개   (표를 하나로 확정하지 않음)
      │  상위 3개마다
      ▼
① normalize       그 표 raw CSV → 정제 parquet (처음 한 번, 지연 실행)
④ build_view      슬롯 dict → 그 표의 코드 조건 → View 데이터 + Record(doc_type="view")
      │
      ▼
⑤ views           질의(자연어·슬롯) + 단위별 후보·View Record 묶음 ──▶ [판단 모듈]
```

| # | 로직 (`services/`) | API (`routers/`) | 설명 문서 (`docs/`) | 상태 |
|---|---|---|---|---|
| - | — | `main.py`, `schemas.py` | `api.md` | 완료 |
| 0 | `meta_profile.py` | `meta.py` | `meta_profile.md` | 완료 |
| 1 | `normalize.py` | `normalize.py` | `normalize.md` | 완료 (지연 정규화) |
| 2 | `query_bundle.py` | `query.py` | `query_bundle.md` | 완료 (슬롯 문자열 → dict 보조, 예시 12개) |
| 3 | `embedding.py`, `table_text.py`, `search.py` | `search.py` | `search.md` | 완료 |
| 4·5 | `build_view.py`, `views.py` | `views.py` | `build_view.md` | 완료 |

## 확정된 결정 (2026-11-02)

| 항목 | 결정 |
|---|---|
| 모듈 목적 | 자연어로 메타데이터 검색 → 슬롯으로 View 생성 → 질의·서브쿼리마다 View 여러 개 → 질의와 엮어 **판단 모듈**로 |
| 입력 | 자연어(`original`, `sub_questions`) + 슬롯 dict(`filters`, `sub_filters`). 슬롯 문자열(`rewritten`)은 참고용, dict 가 없을 때만 파싱 |
| 검색 | 자연어만 사용. **순차**: BM25(kiwi 형태소)로 989개 중 **10개** → 그 10개만 bge-m3(HCX)로 다시 줄 세움 → 상위 **3개** (본 프로젝트에서 raw 전체로 늘면 dense 를 전부에 계산하기 느려서) |
| View | 재정렬 상위 **3개**만 View 카드 생성. 상위 질의와 서브쿼리 **모두** 검색 (예시 12개 → 검색 16번 → 카드 48장) |
| 출력 | **카드(Record) 목록 하나** `output/view_records.json`. 카드 = `id`(view::표key::주기::질문ID-순위::종류), `lexical_text`, `table{columns, rows}`, `doc_type: view`, `parent_id`(table::표key), `metadata`(survey_nm, category, survey_type, view_type, prd_se, prd_from, prd_to, is_latest, unit, geo_level, n_points, items, dims), `source`. dense_vectors·질문 정보는 넣지 않음 (받는 쪽 예시와 같게). 확인용 상세는 `view_results.jsonl` |
| 표 탐색 범위 | 카탈로그 전체 (원본 있는 989개). 코드 어디에도 표 목록을 두지 않음 |
| 메타데이터 | **초안**. 바뀌면 `table_text()` 와 `build_view` 의 match_* 함수만 고치고 색인을 다시 만듦 |
| 빈 슬롯 기본값 | 값 조회 = 조건에 값이 있는 최신 연도, 추이 = 전체 기간, 지역 없음 = 전국, 시나리오 = 중위 |
| 입력 질의 | 쿼리 모듈 담당자가 준 12개 (11/1 실험 결과값은 사용하지 않음) |
| API | FastAPI + Swagger, 로직(services)과 API(routers) 분리, 포트 8002 |

## 폴더

```
view_model/
 ├─ README.md          이 문서
 ├─ main.py            FastAPI 앱 (Swagger /docs)
 ├─ schemas.py         입출력 스키마 (QueryBundle, Filters, Record, ViewResult …)
 ├─ config.py          공통 경로·공용 함수
 ├─ requirements.txt   fastapi, uvicorn, httpx
 ├─ routers/           API 층 (meta, normalize, query, search, views)
 ├─ services/          로직 층 — CLI: cd view_model && ../.venv/Scripts/python.exe -m services.<이름>
 ├─ data/              고정 입력 (slot_queries.json: 쿼리 모듈 예시 12개)
 ├─ docs/              엔드포인트별 설명 (api, meta_profile, normalize, query_bundle, search, build_view)
 └─ output/            산출물 (meta_profiles.jsonl, table_index/, embed_cache.sqlite, processed/, profiles/, views/, view_results.jsonl …)
```

> 이 폴더는 `.gitignore` 에 없어 git 에 새 폴더로 보입니다. 커밋에서 빼려면 `.gitignore` 에 `view_model/` 을 직접 추가하세요.
