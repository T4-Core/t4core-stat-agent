# v4 파이프라인 단계별 검수 카드

평가 질문(예: `kosis_rag_eval_80_queries.csv`)의 **질문 문장만** v4 파이프라인에 넣고, 질문마다 **카드 한 장(HTML + PNG)** 에
단계별 근거를 모은다. 사람이 카드를 보고 **어느 단계가 처음 틀렸는지** 판정하면 단계별 문제가 집계된다.

- 노트북: `eval/pipeline_review/review_v4.ipynb` (Cell 1 설정 → 2 실행 → 3 신호등 → 4 단계별 집계 → 5 카드 → 6 판정 저장)
- 코드·CLI: `eval/pipeline_review/review_v4.py` (`list` · `run` · `cards` · `summary`)
- 입력: `review_80.py` 와 같은 테스트 세트 탐색 (`TEST_DATA_DIR`: `storage/test_data` → `./test_data` …). 파일 경로를 직접 줘도 됨
  (`QUERIES = "test_data/kosis_rag_eval_80_queries.csv"`). 질문 열만 쓰고 정답 참고 열은 무시
- 출력: `storage/eval_runs/<질문 파일 이름>__v4/` — `results.json` · `json/Q001.json` · `cards/Q001.html·png` · `review.csv` · `run_meta.json`
  (기존 `review_80` 결과 폴더와 따로)

## 카드 구성

| 구역 | 근거 | 자동 진단 사유 코드 |
|---|---|---|
| ① 쿼리 분석 | 재작성(v3) 문장 · HCX 슬롯 · 슬롯 → CSV 값 접지 표 (출처 · 그 값을 가진 표 수 · 근거 표:값(종류)) · 시점 규칙 · 되묻기 후보와 자동 응답 · 서브쿼리 · 검색 문장 · View 슬롯 | `q.clarify` 되묻기 필요 · `q.clarify_stop` · `q.ungrounded` 슬롯 값이 CSV 에 없음 · `q.no_target` · `q.out_of_scope`(CHECK) · `q.time_no_table`(참고) |
| ② 검색 | 단위마다 후보 10개: 순위 · 조사 · 표 · 점수 · BM25 순위 · 못 맞춘 조건(빨간 행) · View 생성 | `s.none_ok` 모두 조건 못 맞춤 · `s.top1_unmet` 1위가 못 맞춤 · `s.no_cand` |
| ③ View | View 마다 KOSIS 통계표 링크 · 원본 CSV · View CSV · 필수 메타 사용(판단 모듈 근거) · 못 맞춘 조건 · 좌표 · **잘라 낸 표 ↔ 원본 CSV 같은 좌표 행** (값 일치 수) | `v.none` · `v.error` · `v.empty` · `v.unusable` · `v.raw_mismatch` 원본과 값 다름 · `v.raw_missing` |
| ④ 충돌·선택 | 같은 교차점 값이 다른 표 · 선택지(주석·산출 기준·KOSIS) · 자동 선택 | `c.ambiguous` · `c.partial` · `c.empty` |
| ⑤ 답변 (선택) | HCX 답변 · 사용 View · 근거에 없는 숫자(형광) | `a.insufficient` · `a.unverified` · `a.error` |

자동 판정 = 사유 중 가장 나쁜 등급 (PASS < CHECK < PARTIAL < FAIL). **초안**이고, 사람 판정(단계별 · 첫 실패 단계 · 코멘트)이 최종.
다시 실행(`FORCE=True`)해도 사람 판정은 유지된다.

## 찾은 표가 정답인가 — hit 지표

노트북 Cell 4-1 · CLI `python eval/pipeline_review/review_v4.py hits --queries 80` · `review.csv` 의 `첫_정답_순위`·`hit@1`·`hit@5`·`MRR` 열.

정답 기준 (우선순위)
1. **사람이 고른 정답 표** — Cell 6 `RELEVANT = ["DT_…"]` (`set_review(…, relevant=[…])`)
2. **정답 참고 파일의 표 ID 열** — 질문 파일과 이름이 짝인 `…_answers_references.csv` (또는 질문 파일의 남는 열) 중
   이름에 `tbl` · `table_id(s)` · `표id` · `정답표` 가 든 열, 값에서 `DT_…` 모양만
3. **조사명** (약한 기준) — 같은 조사의 표면 정답으로 봄

정답 참고는 **점수 계산·카드 ★ 표시에만** 쓰고 파이프라인 입력에는 넣지 않는다.

| 지표 | 뜻 |
|---|---|
| `첫_정답_순위` · `hit@1/3/5/10` · `MRR` | ② 검색 후보(단위마다 10개) 중 정답 표의 가장 좋은 순위 (서브쿼리면 단위 중 최선) |
| `View_hit` | ③ View 를 만든 표에 정답이 있는가 |
| `최종_hit` | ④ 이후 답변으로 넘긴 View 에 정답이 있는가 |

셋을 나란히 보면 어디서 놓쳤는지 보인다: 후보에 없음 → 검색 · 후보엔 있는데 View 없음 → `n_views`·조건 확인 순서 ·
View 엔 있는데 최종 없음 → 충돌 선택. 카드 맨 위에 정답 기준·첫 정답 순위·hit 가, 후보 표·View 에 ★ 가 붙는다.

`review_80.expected_tables` 도 같이 고침: 이전엔 이름에 `tbl` 이 든 열만 읽어 `gold_table_ids` 열을 못 읽었다.

## 원본 대조

View 의 좌표(항목 ID · 분류 코드 · 연도)로 원본 CSV(`kosis_data/raw/<카테고리>/<기관>_<표>.csv`)의 행을 다시 골라
View 의 값마다 원본에 같은 값이 있는지 센다 (`✅ 원본 대조 n/n칸 일치`). 다르면 정규화·View 자르기 단계 문제.

## 설정 (노트북 `SETTINGS` / CLI 옵션)

| 키 | 기본 | 뜻 |
|---|---|---|
| `today` | 2026-11-02 | '작년'·'최근' 기준일 |
| `clarify` | first | 되묻기에 첫 후보로 자동 응답 (카드에 표시) · none = 멈춤 |
| `select` | first | 충돌이면 검색 순위 높은 선택지 자동 (카드에 표시) · none = 선택 대기 |
| `n_views` | 3 | 단위마다 View 를 만들어 비교할 표 수 |
| `retrieval_config` | None | 검색 구성 (None = 기존 검색). 전체 임베딩 구성은 처음 실행 때 오래 걸림 |
| `answer` | False | ⑤ HCX 답변까지 (문항당 HCX 1회 추가) |
| `raw` | True | 원본 CSV 대조 |

HCX 호출: 문항당 쿼리 분석 1회 (+ answer). 후보 표 임베딩은 캐시. 큰 표가 처음 골리면 정규화에 시간이 걸릴 수 있음 (이후 캐시).

## PNG

카드 PNG 는 **별도 파이썬 프로세스**에서 만든다 (`review_80.png_many`, `review_80` 카드도 같은 함수).
Windows 의 Jupyter 는 하위 프로세스를 못 띄우는 이벤트 루프를 써서, 노트북 안에서 playwright 를 바로 부르면
`NotImplementedError` · `Future exception was never retrieved` 가 났다 (예전 `review_80` 도 같은 문제).
- 브라우저: playwright chromium → 설치된 Chrome → Edge 순. 셋 다 없으면 html2image, 그것도 없으면 HTML 카드만 (경고 한 줄)
- 자동 실행(`run_batch`)은 HTML 을 문항마다 바로 쓰고, PNG 는 끝에 한 번에 만든다 (브라우저 한 번만 띄움).
  중간에 멈췄으면 `rv.write_cards(RUN, png=True)` 로 다시
