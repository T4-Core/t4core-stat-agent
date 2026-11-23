# Generator 평가 방법

기준은 `criteria.md`, 실행 명령은 `../README.md`를 따른다. 이 문서는 **질문 세트를 만들고 측정 · 판정 · 재측정하는 절차**다.

## 1. 질문 세트 구성

### 1.1 구성 조건 (모듈 담당자가 자기 세트를 만들 때)

| # | 조건 | 이유 |
|---|---|---|
| 1 | 연산 12종(raw · change · growth_rate · cagr · share · diff · ratio · rank · extreme · aggregate · combine · index)을 한 번 이상 | 연산마다 식 · 단위 · 방향이 다르다 |
| 2 | 실패하기 쉬운 축마다 질문: 시점(없는 연도 · 연도 없음 · 기간 · 월별), 지역(전국 · 시군구 · 다중 지역), 단위 · 자릿수(천명 · % · %p · 비율 지표), 결측, 여러 하위 질문, 범위 밖 · 계산 불가 | 기준선에서 오류가 모인 축 |
| 3 | 실제 사용자가 쓸 말(구어체 · 동의어) | 규칙형 질문은 질의 분석의 약한 곳을 건드리지 못한다 |
| 4 | 기대 결과는 **실행 전에** 적는다 | 결과를 보고 맞다고 판단하지 않기 위해 |
| 5 | 원본 표와 대조할 수 있는 사실 질문을 중심에 | 판정에 감상이 들어가지 않게 |
| 6 | 표에 자료가 있는지 미리 확인하지 않는다 | 자료가 없을 때 정직하게 답하는지도 평가 대상이다. 답변 가능성은 `answerable_when`이 실행 후 ViewSet으로 정한다 |
| 7 | 차트 지정 요청은 별도 세트(`ext-chart-request`)로: 지원 · 미지원 · 부적합 · 제외 · 하위 질문별 · 오인식 대조군 | KOS-41 |

### 1.2 기대 결과 작성 (`questions/*.yaml`, 스키마 `schema.py`)

1. `scope`: 질문 자체가 통계 범위인가 (`in` · `out`).
2. 하위 질문을 나눈다. 질의 분석이 나누는 방식과 같을 필요는 없다(내용 matcher로 대응). 한 계산이 여러 지표를 쓰면(출생 − 사망) 하위 질문 하나로 둔다.
3. 하위 질문마다:
   - `match`: `item_any`(지표 이름) · `region_any` · `op_any`
   - `answerable_when`: 계산이면 `operands_valid`(피연산자 · 분모 좌표), 값 조회면 `view_has_row` · `view_has_rows`, 순위 · 비교면 `view_has_categories`. 마지막 규칙은 조건 없는 `hold` (`hold_reason: from_predicate`)
   - `m2`: `acceptable_charts`(정답이 여럿이면 모두, 차트 없음 허용은 `null`), `measure`
   - `m3`: `op`, `operands`, `denominator`, `result_unit`(ratio)
   - `values`: 원본 View 행에서 읽은 값을 **평가 정규형**으로 (`%` → ratio, 천명 → 명). FINAL은 `binding`, 목록은 점마다 `key`
   - `direction`: 증감 방향이 정해진 질문만
4. `required_caveats`: `projection` · `missing_period:YYYY` · `missing_period` (조건이 성립할 때만 검사된다)
5. `verified: false`로 커밋하고, 작성자가 아닌 팀원이 원본 View와 대조한 뒤 `true`로 바꾼다.

## 2. 실행

| 단계 | 명령 | 비고 |
|---|---|---|
| 사전 준비 | `python -m backend.rag.csv_index build --workers 4` | 처음 한 번. 임베딩 캐시는 첫 질문에서 만들어진다 (HCX 임베딩 989회) |
| live | `python -m eval.generator.run --mode live --set core34 --runs 2 --tag <이름>` | 실제 HCX. **최소 2회.** 질문은 하나씩 차례로 |
| replay | `python -m eval.generator.run --mode replay --from <EVAL_RUNS_DIR>/<이름>/runs.jsonl.gz --runs 2 --tag <이름>_replay` | 검색 변동을 뺀 Generator 변동. ViewSet이 없는 문항(범위 밖 · 되묻기)은 건너뛰고 `run.log`에 기록 |
| QA off | 위 replay에 `--no-qa` | QA on/off 비교 전용 |
| oracle | `python -m eval.generator.run --mode oracle --from <runs.jsonl.gz> --only Q05,... --runs 2` | `oracle/m3/<id>.json`(검증된 M3 출력)이 있는 문항만. 저장한 `Module6Request`가 없는 실행은 `no_full_request`로 건너뜀 |

실행 결과는 `EVAL_RUNS_DIR/<tag>/`(`storage/runs/eval_generator`, git 제외)에 `runs.jsonl.gz` · `manifest.json`(git sha · dirty · 모델 · 프롬프트 해시 · 세트 해시) · `run.log`로 남는다.

## 3. 판정 · 집계

```bash
python -m eval.generator.report <EVAL_RUNS_DIR>/<tag>/runs.jsonl.gz --set core34 [--review review.csv]
```

산출물(`<tag>/runs_report/`): `verdicts.jsonl`(회차별 판정 · 근거), `summary.json`(지표), `report.md`(표), `review.csv`(판정 시트)

### 3.1 자동 점검 항목
| 항목 | 단계 | 내용 |
|---|---|---|
| 금지 문구 | 1 | `None` · `nan` · `null` · `내부 오류` · `Traceback` · `{a` · `undefined` |
| 연산 · 피연산자 · 계산 값 | 1 | 기대 op, 원본 행 좌표, (a)층 수치 |
| 결과 단위 · 표시 반올림 | 1 | 연산별 결과 단위, (c)층 기대 표시값 |
| binding · 방향 | 1 | FINAL 값의 지역 · 기간, 증감 단어 |
| 필수 주의사항 | 1 | 추계 고지 · 없는 시점 고지 |
| 기대 hold인데 값 | 1 | 근거 확인 |
| 렌더링 · Fidelity | 1 | `render_status`, 차트 유형별 정규형 비교 |
| 완전성 | 2 | 하위 질문별 기대 대 관측, 고지 여부 |
| 형식 지표 | 지표 | `method` · 자리표시자 검사 · Step Coverage · 모듈 6의 차트 서술 · Spec Lint · Fallback |
| 차트 요청 | 지표 | 해석 · 최종 결과 · 안내 · 오인식 |
| QA | 지표 | A0 대 기대 라벨, 내용 경고 대 판정 시트 태그 |

### 3.2 수동 검토 절차 (판정 시트 `review.csv`)
1. `needs_review=True`인 행과 `auto_verdict=미달`인 행을 먼저 본다.
2. `verdicts.jsonl`의 근거(`findings` · `subs`)와 `runs.jsonl.gz`의 원본 View 행을 대조한다. KOSIS 원본 사이트와의 대조가 필요하면 `records[].source.kosis_url`을 쓴다.
3. 채울 열: `verdict`(자동 판정을 바꿀 때만), `first_failure`, `slot`(0 틀림 · 1 부정확하나 오해 없음 · 2 정확), `faithfulness`(같은 척도, 숫자 없는 서술), `tags`(내용 경고 정답 라벨: `condition_not_applied` · `ratio_not_answered` · `measure_ignored` · `held_value_asserted` · `chart_without_answer` · `unreadable_chart` · `long_list`), `note`
4. `--review review.csv`로 다시 집계한다.
5. 검토자 2인이 1회차를 독립 판정하면 Cohen's κ를 보고한다. κ < 0.6이면 rubric 문구를 고친 뒤 다시 판정한다.

## 4. offline 점검 (HCX 없음)

```bash
python -m eval.generator.render <runs.jsonl[.gz]> [--png]     # 모듈 5 재렌더링 + Fidelity · Lint (PNG 는 Visual Defect 수동 검토용)
python -m eval.generator.contract <runs.jsonl[.gz]>           # 현재 QA 스키마 검사를 저장 출력에 다시
python -m eval.generator.faults <runs.jsonl[.gz]> [--policy]  # Fault Injection · FI-SEM · FI-CONTRA (· Policy Compliance: source=full 만)
python -m eval.generator.metamorphic mt3a <runs.jsonl.gz>     # 실제 HCX (모듈 6만)
python -m eval.generator.metamorphic mt1  <runs.jsonl.gz>     # 실제 HCX (replay)
```

## 5. 재측정 · 비교

1. 수정할 때마다 실패 입력(ViewSet 스냅샷 + HCX 응답 원문, `runs.jsonl.gz`에 있다)을 `tests/`의 회귀 테스트로 먼저 만든다.
2. 같은 세트 · 같은 모드로 2회 이상 다시 잰다. `core34`는 바꾸지 않는다. 새 질문은 별도 세트로 더한다.
3. `python -m eval.generator.report --compare <이전>/verdicts.jsonl <이후>/verdicts.jsonl`로 질문 단위 개선 · 악화 · 회귀를 본다. n=34에서 1문항은 2.9%p라서 비율 차이는 방향 지표로만 쓴다.
4. 과거 slim trace(`profiling/modules36/results`)는 `python -m eval.generator.legacy <파일> --runs 1,2 [--renumber]`로 변환해 같은 판정기로 다시 집계한다. ViewSet · 요청 전체가 없어 replay · oracle · A0 · 내용 경고 지표는 N/A다.

## 6. 한계

- 기대값은 5회차 계산값 중 기준선에서 원본 View와 일치로 판정된 것을 옮겼다(`verified: false`). 제3자 대조 전에는 C2 자동 판정이 그 회차의 계산을 기준으로 한다.
- 표 메타데이터 단위 자체가 틀린 경우(혼인건수의 `명`)는 자동으로 판정하지 못한다(`unit_semantic` → 수동).
- 월별 질문에 연도 값을 답하는 것처럼 근거는 있지만 질문과 다른 범위를 쓴 경우는 고지가 없으면 `silent_omission` + `needs_review`로 넘긴다. 미달 여부는 사람이 정한다.
- 판정 시트의 `slot` · `faithfulness`는 수동 rubric이다. LLM judge는 다른 계열 모델이 정해진 뒤 별도 이슈로 도입한다.
