# 질문 세트

| 파일 | 세트 | 용도 | 변경 규칙 |
|---|---|---|---|
| `core34.yaml` | core34 | 회귀 비교 (수정 전후를 같은 세트로) | **버전 고정(immutable).** 문항 추가 · 의미 변경 금지 |
| `ext_chart_request.yaml` | ext-chart-request | 차트 지정 요청(KOS-41) 처리 | 버전 고정(immutable), 문항 추가만 허용 |
| (새 파일) | ext-* | 모듈 담당자가 추가하는 세트 | 버전을 붙여 추가만 |

스키마는 `eval/generator/schema.py`의 `Question`이다. 필드 의미와 판정 규칙은 `eval/generator/docs/criteria.md` 2장을 따른다.

## v2 보완 데이터셋 (`generator-gapset-v2`)

저장소에 넣지 않는 외부 데이터셋이다. 경로는 `--v2 <경로>` 인자 또는 환경 변수 `EVAL_V2_DIR`로 준다. 데이터셋 안의 `.py`는 실행하지 않고 JSON만 읽는다.

```
python -m eval.generator.v2 check --dataset <경로>          # manifest.sha256.json 해시 · 스키마 · 필드 손실 검사 (없거나 다르면 exit 1)
python -m eval.generator.run --mode isolated --v2 <경로>     # inputs/<ID>.json 격리 ViewSet → QA 경로
python -m eval.generator.run --mode m3_only  --v2 <경로>     # oracle_m3_inputs/<ID>.json → run_module3 만
python -m eval.generator.report <runs.jsonl.gz> --v2 <경로>
python -m eval.generator.v2 fixture --dataset <경로>        # 평가 하네스 probe fixture 다시 만들기
python -m eval.generator.run --mode isolated --v2 <경로> --slots eval/generator/questions/v2_slots.json   # 입력 슬롯 overlay 적용
```

- 변환(`schema_v2.to_question`): 기대 상태는 하위 질문의 `expected_status` 고정값, 하위 질문 대응은 입력 `query_bundle.sub_questions` 순번, claim 값은 원값을 표시 단위로 옮긴 뒤 평가 정규형으로, 요구 자릿수는 `display.digits`.
- v2 문항은 FINAL claim이 답변 문장에 없으면 보류다(`strict_final`).
- 입력 슬롯 overlay(`v2_slots.json`): 데이터셋 입력의 `query_bundle.filters`에는 `의도`만 있어서, M2가 질문이 요청한 나눔(지역 · 성별 · 연령 · 비교축)을 알 수 없다. 이 파일은 운영 질의 분석과 같은 형식의 슬롯을 76문항(A0 대상 제외)에 덧씌운다.
  - 슬롯은 질문 원문에서만 뽑는다. View에 없는 좌표에 맞춰 줄이지 않는다(경계 문항 정답 누출 방지). 이름 없이 수만 말한 지역('다섯 지역')은 `비교축: [지역]`이고, 월별 · 분기별은 `시점`에 연도 정수와 `비교축: 월 · 분기`를 쓴다.
  - 적용하면 `dataset_version`이 `<버전>+slots`가 되고 `input_hash`는 입력 파일 + 슬롯 항목의 해시다. 슬롯 없는 isolated와 `--compare`로 섞이지 않는다.
- 평가 하네스 probe(J01~J14)는 `tests/eval_generator/fixtures/v2_probes.json`(원본 해시 기록)으로 데이터셋 없이 항상 테스트한다.
- 집계 키는 `(dataset, dataset_version, condition, id)`다. 조건이 다른 실행은 `--compare`에서 비교하지 않는다.

## 작성 규칙

1. **실행 전에 작성한다.** 실행 결과를 보고 기대를 바꾸지 않는다. 기대가 틀렸다고 판단되면 그 근거(원본 View 행)를 `notes`에 적고 버전을 올린다.
2. `scope`는 질문 자체가 통계 범위 안인지를 실행 전에 정한다. `analysis.status`로 정하지 않는다.
3. 하위 질문마다 `answerable_when`을 둔다. 계산이 필요한 하위 질문(`m3.op` ≠ `raw`)은 `operands_valid`를 쓴다. `view_has_row`는 값 조회 전용이다.
4. 조건 술어는 ViewSet만 본다. Generator 출력을 보지 않는다.
5. 기대값(`values`)은 평가 정규형으로 쓴다: `%` → `ratio`(÷100), `%p` → `pp`, `배` → `times`, 천명 · 만 명 → 원단위(명).
6. FINAL 값에는 가능하면 `binding`(지역 · 기간 · 지표)을 적는다. 목록 결과는 점마다 `key`를 적는다.
7. `verified: true`는 작성자가 아닌 사람이 원본 View와 대조한 뒤에만 쓴다.

## 지원하는 조건 술어

| 술어 | 인자 | 참이 되는 조건 |
|---|---|---|
| `operands_valid` | `operands: [Coord]`, `denominator: Coord?`, `op?` | 2.2.1의 검사(행 1개 · 결측 · 분모 0 · 시점 · 주기 · 단위 · 모집단)를 모두 통과 |
| `view_has_row` | `item`, `period?`, `region?` | 좌표에 맞는 행이 1개 이상, 값이 숫자 |
| `view_has_rows` | `item`, `min_periods` | 한 Record에 그 항목의 서로 다른 시점이 `min_periods`개 이상 |
| `view_has_categories` | `dim`, `min`, `item?` | 열 이름에 `dim`이 들어간 분류에서 합계(계 · 전체 · 전국 · `_계`)가 아닌 서로 다른 값이 `min`개 이상 (순위 · 비교 질문). 예: Q34 국적 행 없이 `계`만 오면 거짓 |
| `view_note_has` | 문자열 | ViewSet의 Record 열 이름 또는 View 메모에 그 문자열이 있음 |

## 주의사항 코드 (`required_caveats`)

| 코드 | 필요 조건 | 충족 기준 |
|---|---|---|
| `projection` | 계산에 쓴 Record가 추계 표(조사명 · 표 이름에 `추계` · `전망` · `예측`)일 때만 | 답변 또는 주의사항에 `추계` · `전망` · `예측` |
| `missing_period:YYYY` | 그 시점이 ViewSet에 없을 때만 | 답변 또는 주의사항에 그 연도와 `없` |
| `missing_period` | 요청 기간 일부가 없을 때 | 주의사항(`view_missing` · `plan_warning`) 1개 이상 |
