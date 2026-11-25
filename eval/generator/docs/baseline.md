# Generator 기준선 (새 지표로 다시 산출)

- 산출일: 2026-11-23, 평가기: `eval/generator` (기준 코드 `develop` `e719402`)
- 입력: 기존 측정 `profiling/modules36/results/full1.jsonl`(11-18, 34문항 × 5회차). 기존 판정은 `docs/evaluation/모듈3_6_전체파이프라인_평가.md`(저장소 밖)
- 재현: `python -m eval.generator.legacy profiling/modules36/results/full1.jsonl --runs 1,2` → `report` · `render` · `faults` (명령은 6장)
- 이 문서의 수치는 **자동 판정**이다. `needs_review` 문항은 판정 시트(`review.csv`) 수동 판정 전 값이다.

## 1. 측정 조건

| 회차 | 시점 · 코드 | 경로 | 비고 |
|---|---|---|---|
| 1 · 2 | 11-18, `develop` `233a1a8` + 모듈 3 · 6 자체 검토분 | 직렬 `run_modules` | 수정 전 기준선 (두 회차 중 낮은 판정) |
| 3 | `develop` `873d81f` | 직렬 | 모듈 코드는 수정 전 |
| 5 | F1~F16 수정 직후 | 직렬 (일부 레코드 QA 출력 있음) | 1회 |

과거 trace는 slim 형식이라(ViewSet 전체 · 모듈 요청 전체 · figure 없음, Record 행 400개까지) 다음은 **N/A**다: replay · oracle, A0 Unanswerable Detection, 내용 경고 P/R, 차트 요청 지표. 하위 질문 연결과 보류 범위는 어댑터로 추정했다(`source=adapter`).

## 2. E2E

| 지표 | 1 · 2회차 | 3회차 | 5회차 |
|---|---|---|---|
| 통과 · 보류 · 미달 (자동) | 19 · 4 · 11 | 20 · 4 · 10 | 31 · 3 · 0 |
| 통과 · 보류 · 미달 (기존 문서) | 12 · 9 · 13 | 15 · 8 · 11 | 21 · 11 · 2 |
| Generator 귀책 미달 (자동) | 11 | 10 | 0 |
| needs_review (수동 판정 대기) | 6 | 4 | 5 |
| silent_omission · failed_to_contain | 3 · 2 | 2 · 2 | 2 · 0 |
| 판정 안정성 (2회) | 94.1% (불안정 2) | N/A (1회) | N/A (1회) |
| 응답률 (값을 낸 회차) | 75.0% | 79.4% | 79.4% |
| 정직한 실패 | 100% | 100% | 100% |
| 답변 방식 (hcx · retry · template · none) | 43 · 8 · 12 · 3 | 21 · 6 · 5 · 1 | 18 · 9 · 3 · 3 |
| 지연 평균 · 중앙 · 최대 (초) | 48.2 · 47.8 · 314.6 | 31.0 · 19.9 · 210.3 | 47.1 · 50.5 · 153.2 |
| HCX 호출 · 실패 · 예외 | 195 · 0 · 0 | 100 · 0 · 0 | 105 · 0 · 0 |
| numeric_match ∧ ¬semantic_ok | 0 | 0 | 0 |

쌍 비교 (1 · 2회차 → 5회차, `report --compare`): 개선 Q01 Q05 Q06 Q08 Q11 Q13 Q20 Q21 Q22 Q23 Q26 Q28 · 악화 없음 · 회귀 없음 · Generator 귀책 미달 11 → 0.

### 2.1 기존 판정과의 차이

**미달은 기존 판정과 문항 단위로 일치한다.** 자동 미달은 기존 미달의 부분집합이고, 빠진 것은 모두 `needs_review`로 수동 판정에 넘어간다.

| 회차 | 기존 미달 | 자동 미달 | 자동이 미달로 정하지 않은 것 |
|---|---|---|---|
| 1 · 2 | Q01 Q05 Q06 Q08 Q11 Q13 Q16 Q21 Q22 Q23 Q26 Q28 Q30 | 같음, Q16 · Q30 제외 | Q16 (보류 + needs_review), Q30 (통과 + needs_review) |
| 3 | Q01 Q06 Q08 Q11 Q13 Q16 Q21 Q22 Q23 Q26 Q33 | 같음, Q16 제외 | Q16 |
| 5 | Q16 Q30 | 없음 | Q16 (보류 + needs_review), Q30 (통과 + needs_review) |

- **Q16** (월별 질문에 연도 값을 '월별 추이'로 답함): 기대 hold(월별 자료 없음) + 근거 있는 값 + 고지 없음 → `silent_omission` + `needs_review`. 연도 값 자체는 원본과 맞아서, '질문과 다른 범위를 사실처럼 말했는가'는 사람이 정한다(method.md 6장).
- **Q30** (혼인건수 49,374에 단위 `명`): 표 메타데이터 단위가 `명`이라 결과 단위 검사는 통과한다. `unit_semantic`(지표 '건수'인데 단위 '명')을 수동 판정으로 넘긴다. 귀책 후보 `data`.

**통과 · 보류 경계는 판정 체계 변경으로 달라졌다.** 원인은 두 가지다.

| 원인 | 해당 문항 | 설명 |
|---|---|---|
| 기대 상태를 입력으로 정함 (criteria.md 2.1) | Q08 · Q19 · Q24 · Q33 · Q34 (5회차), Q19 · Q24 · Q33 · Q34 (1 · 2회차) | ViewSet에 필요한 자료가 없으면 기대 hold다. 사유를 밝히고 보류하면 **Generator 통과**이고 First Failure는 `M1+R`이다. 기존 판정은 '질문을 다 채우지 못함'으로 보류였다. 사용자 관점은 응답률로 따로 본다 |
| 근거 있는 대체 + 고지 | Q14 · Q26 (5회차) | 요청 시점이 없어 다른 시점 값을 고지와 함께 낸 경우 충족 + `rule_review` · `needs_review` |
| 앞 단계 표 선택 | Q01 · Q23 (5회차) | 추계 표가 선택됐지만 그 표 안에서 추계 고지와 함께 맞게 답함 → Generator 통과. 실제 조사 표가 아닌 것은 검색 · View 귀책(U4)으로 기존 문서에 남아 있다 |
| 기간 축소 | Q02 (1 · 2회차) | '최근 5년'이 두 해로 줄었지만 두 해 값이 맞고 `view_has_rows(min_periods=2)`를 충족 → 통과. 기간 축소는 질의 분석 귀책(U1) |

### 2.2 자동 판정이 새로 잡은 것
기존 문서 5장은 "자동 점검의 숫자 대조는 단위 오류(F1)를 잡지 못했다"고 적었다. 새 평가기는 결과 단위 검사로 이를 자동으로 잡는다.

| 결함 | 문항 (1 · 2회차) | 잡은 점검 |
|---|---|---|
| F1 항목 괄호를 단위로 읽음 (`1세이상` · `내국인`) | Q06 Q13 Q21 Q22 Q26 | `result_unit` (M3) |
| F5 분모 = 부분과 같은 행 (100.0%) | Q05 Q28 | `hold_but_value`(근거 없는 값) · `execution` |
| F6 연령 범위 합계 누락 (0세만) | Q11 | `operation` · `execution` |
| F7 다른 지표 표로 답함 (출생성비로 인구 순위) | Q08 | `hold_but_value`(질문한 지표가 아님) |
| F8 추계 미고지 | Q01 Q23 | `caveat_projection` (`failed_to_contain`) |
| F12 앞 40개 시점만 보고 최댓값 (3회차) | Q33 | `execution` (결과 key 1980 ≠ 기대 2022) |

## 3. 모듈별

| 모듈 | 지표 | 1 · 2회차 | 3회차 | 5회차 |
|---|---|---|---|---|
| M2 | Acceptable-set Accuracy | 100% (66/66) | 100% (33/33) | 100% (33/33) |
| M2 | Measure Accuracy | 75.0% (12/16) | 75.0% (6/8) | 75.0% (6/8) |
| M2 | Sub-question Coverage | 100% (43/43) | 100% (25/25) | 100% (25/25) |
| M3 | Plan Validity | 100% | 100% | 100% |
| M3 | Operation Correctness | 94.9% (37/39) | 95.7% (22/23) | 100% (24/24) |
| M3 | Operand Accuracy | 100% (6/6) | 100% (4/4) | 100% (4/4) |
| M3 | Execution Accuracy | 92.0% (81/88) | 95.8% (46/48) | 100% (49/49) |
| M3 | Hold Recall | 44.0% (11/25) | 44.4% (4/9) | 55.6% (5/9) |
| M3 | False-hold Rate | 9.3% (4/43) | 8.0% (2/25) | 4.0% (1/25) |
| M3 | Hold Reason Accuracy | 4/6 | 1/2 | 1/1 |
| M3 | 결과 단위 (F1 유형) | 81.6% (40/49) | 80.0% (20/25) | 100% (26/26) |
| M3 | 표시 반올림 (c)층 | 100% (36/36) | 100% (16/16) | 100% (18/18) |
| M5 | Render Success (재렌더링) | 100% (59/59, skipped 1) | 100% (29/29) | 100% (18/18) |
| M5 | Chart-Data Fidelity (재렌더링) | 100% (57/57, 겹쳐 그린 차트 3 제외) | 100% (28/28, 1 제외) | 100% (17/17, 1 제외) |
| M5 | Spec Lint | 100% | 100% | 100% |
| M6 | First-pass (`method == hcx`) | 65.2% (43/66) | 63.6% (21/33) | 54.5% (18/33) |
| M6 | binding (semantic_ok) | N/A (binding 기대 없음 · numeric_match만 확인) | N/A | N/A |
| M6 | Unsupported Number (자리표시자 검사) | 95.5% | 90.9% | 81.8% |

- binding: `core34` 기대값에는 좌표(binding)가 없다. 이전 집계의 binding 100%는 binding 기대가 없을 때 성공으로 센 값이라 검증 결과가 아니다. 숫자 일치(`numeric_match`)만 확인된 것으로 읽는다. 좌표 검증은 v2 데이터셋(claim마다 binding)에서 잰다.
- Hold Recall은 기대 hold 중 '보류 · 누락 + 고지'만 성공으로 센다. 근거 있는 대체 값(Q14 · Q26 · Q32 등)은 보류가 아니라 분모에서 실패로 남는다.
- Hold Reason 실패: Q34 기대 `missing_operand`(국적 행 없음)인데 사유가 '한 해뿐'(기존 F10). 5회차에서 해소.
- First-pass가 5회차에 낮아진 것은 자리표시자 검사 강화(5회차 수정분)로 재시도가 늘어난 결과다(재시도 9회). 최종 실패(template · none)는 6회로 1 · 2회차 15회보다 적다.

## 4. QA (offline, 5회차 출력 기준)

| 지표 | 값 | 비고 |
|---|---|---|
| Fault Injection Detection Recall | 100% (589/589) | F-MISS · F-TYPE · F-ENUM · F-EMPTY · F-REF · F-EXTRA · F-MULTI |
| Severity Correct | 100% | |
| False Alarm (CLEAN 132건 중 오류 판정) | 0% | CLEAN 20건은 형식 경고(스키마에 없는 키 `by`)만 있음 → Precision 96.7% |
| F-NEWREF | N/A | 11-20 이전 출력에 `sub_question_id` · `withheld` 필드가 없음. 11-23 live 3문항 실행(`v6_live`)에서는 4건 모두 탐지 |
| 현재 QA 스키마 검사 (contract) | 오류 0 | 33회 × 4 지점 |
| FI-SEM Recall | `answer_caveat_conflict` 100% (28/28) · `chart_answer_mismatch` 100% (31/31) · `value_list` 100% (32/32) · `too_many_marks` 100% (7/7) · `measure_mismatch` 92.9% (26/28) · `ratio_missing` 92.6% (25/27) | 미탐지는 `faults.py` 산출 `semantic.json`의 `rows`. 표의 항목이 이미 비율인 경우 등 오탐 방지 규칙과 겹친 사례로 보이며 QA 담당(KOS-39) 확인 필요 |
| FI-CONTRA | 결과 부호 반전 2 · 비중 > 100% 1 · 순위 중복 1 모두 QA 미탐지 | QA 설계 범위(값 의미 미검사) 밖. 의미 정합성 미검사 항목 |

## 5. KOS-40 시점 실측 (`v6_live`, live 3문항)

| 항목 | 값 |
|---|---|
| 실행 | 2026-11-23, `e719402` + 평가기 (dirty: `config.py` 한 줄), HCX-007, QA 경로 |
| 판정 | Q05 통과 (17.5%) · Q11 통과 (1,557,996명) · Q29 통과 (범위 밖) |
| 기록 | ViewSet · analysis 스냅샷, `Module3Request` · `Module6Request` 전체, 11개 결과 키, QA 검사 시간 |
| QA | 상태 ok 2 · n/a 1, A0 중단 0 (기대 `continue` 2) |
| 렌더링 | Q05 donut · Q11 차트 모두 `skipped/no_chart_content` (모듈 3이 차트 내용을 만들지 않음) → Render Success 분모 제외 |
| Fault Injection | 40건 탐지 100%, F-NEWREF 4건 포함, CLEAN 오탐 0 |
| Policy Compliance | 8/8 (재시도 후 회복 · 지속 오류 시 항목 빼기 · 계산 계획(`chart_plan`) 누락 시 중단 · 모듈 6 실패 시 답변 없이), 재시도 상한 위반 0 |

### 5.1 KOS-40 시점 기준선 (`v8_core34`, `core34` live 2회)

- 실행: 2026-11-23 10:59~11:51, `develop` `e719402` + 평가기, HCX-007, QA 경로, `storage/runs/eval_generator/v8_core34/`
- 이 실행부터 ViewSet · 모듈 요청 전체가 저장되어 replay · oracle · A0 · 내용 경고 지표를 산출할 수 있다.

| 지표 | 값 |
|---|---|
| 통과 · 보류 · 미달 | **30 · 3 · 1** (88.2% · 8.8% · 2.9%) |
| Generator 귀책 미달 | 1 (Q32) |
| needs_review | 3 (Q14 · Q16 · Q26) |
| silent_omission · failed_to_contain · scope_error | 2 (Q12 · Q16) · 0 · 0 |
| 판정 안정성 | 100% (34/34) |
| 응답률 · 정직한 실패 | 72.1% · 88.2% (고지 없는 누락: Q12 두 회차) |
| 답변 방식 (hcx · retry · template · none) | 36 · 12 · 11 · 7 |
| 지연 평균 · 중앙 · 최대 (초) | 46.1 · 18.1 · 725.3 (Q02 2회차: HCX ReadTimeout 후 모듈 3 581초. Q22 1회차: HTTP 429 후 464초) |
| HCX 호출 · 실패 · 예외 | 140 · 2 (429 1 · timeout 1) · 0 |
| M2 Acceptable-set · Measure · Coverage | 100% (64/64) · 87.5% (14/16) · 92.2% (47/51) |
| M2 요청 오인식 | 0건 (66/66) |
| M3 Operation · Operand · Execution | 100% (45/45) · 100% (6/6) · 100% (96/96) |
| M3 Hold Recall · False-hold · Hold Reason | 64.7% (11/17) · 3.9% (2/51) · 7/11 |
| M5 Render Success · Fidelity · Lint | 100% (31/31) · 100% (31/31) · 100%. 재렌더링 37개 중 겹쳐 그린 차트 6 제외. `skipped/no_chart_content` 47 |
| M6 First-pass · binding · 결과 단위 · 표시 반올림 | 54.5% · N/A (binding 기대 없음 · numeric_match만 확인) · 100% (49/49) · 100% (32/32) |
| QA 상태 분포 (품질 지표 아님) | ok 41 · warned 23 · partial 2 · n/a 2 (범위 밖) |
| QA 재시도율 · 중단 | 5.9% · 0 |
| QA A0 | 기대 `continue` 66, 관측 중단 0 → 답할 수 있는 질문을 막은 회차 0. 양성 사례가 없어 Precision · Recall N/A |
| QA 내용 경고 (경고 수) | `answer_fallback` 18 · `withheld` 11 · `plan_warning` 8 · `measure_mismatch` 2 · `note` 2 · `value_list` 1. 정답 라벨(판정 시트 tags) 입력 전이라 P/R N/A |
| QA 검사 시간 | 68회 합계 1.75초 (회당 0.026초) |
| Fault Injection | 1,291건 Recall 100% · Severity 100% · CLEAN 264건 오탐 0. F-NEWREF 129건 모두 탐지 |
| FI-SEM Recall | `answer_caveat_conflict` · `chart_answer_mismatch` · `value_list` · `too_many_marks` 100%, `ratio_missing` 88.7% (47/53), `measure_mismatch` 84.3% (43/51) |
| FI-CONTRA | 8건 모두 QA 미탐지 (설계 범위 밖) |
| Policy Compliance | 250 시나리오 100%, 재시도 상한 위반 0 |
| 현재 QA 스키마 검사 (contract) | 오류 0 |

**판정이 통과가 아닌 문항**

| 질문 | 판정 | 원인 | 귀책 후보 |
|---|---|---|---|
| Q32 | 미달 (2회 모두) | 질의 분석이 지역 4곳을 하위 질문 지표로 나눴고, 모듈 3이 `항목=서울`인 다른 표(DT_1PB1608)의 값 440,861명을 계산했다. 모듈 3 메모에 "고른 '결혼 건수' 은 다른 지표"라고 남겼지만, 답변은 그 값을 "결혼 건수"로 단정했다 | M1+R(분해) · M3(지표 불일치를 보류하지 않음) |
| Q12 | 보류 (2회 모두, `silent_omission`) | 출생아수 · 사망자수를 따로 답하고 질문한 차이(−120,252)는 계산하지 않았다. 빠졌다는 고지도 없다. 5회차에는 계산했다 | M2 · M3 (하위 질문에 걸친 계산을 계획하지 않음) |
| Q16 | 보류 + needs_review | 월별 질문에 연도 값을 '월별'로 답함 (기존과 같음) | M1+R · M6 |
| Q25 | 보류 | '1인가구' 항목을 HCX가 '가구수'로 적어 계산 실패 (기존 F18, 미수정) | M3 |

**쌍 비교**

| 비교 | 개선 | 악화 | 판정 |
|---|---|---|---|
| 1 · 2회차 → `v8_core34` | Q01 Q05 Q06 Q08 Q11 Q13 Q20 Q21 Q22 Q23 Q26 Q28 | Q12 · Q32 | 회귀 없음 (Generator 귀책 미달 11 → 1) |
| 5회차 → `v8_core34` | 없음 | Q12 (통과 → 보류) · Q32 (보류 → 미달) | **회귀** (Generator 귀책 미달 0 → 1, 회귀 기준 2) |

5회차 이후 develop에 들어온 변경(KOS-41 차트 요청, KOS-26 질의 분석 어댑터 되돌림, KOS-39 QA)이 원인 후보다. Q12 · Q32 모두 질의 분석의 하위 질문 분해에서 시작하므로, `7b28bf0`(질의 분석 어댑터 되돌림) 전후의 analysis를 replay로 비교하면 귀책을 좁힐 수 있다.

### 5.2 `v8_core34` 실행에서 찾아 고친 판정기 결함
| 결함 | 증상 | 수정 |
|---|---|---|
| 부분 key 일치 점 선택 | Q28 1회차: 모듈 3이 share를 전국 포함 모든 지역에 계산해 `{시점}` key에 전국(100%) · 서울 두 점이 맞았고, 전국 점을 골라 미달로 오판 | 여러 점이 맞으면 기대 지역으로 좁히고, 그래도 여럿이면 판정하지 않음(수동) |
| 대응되지 않은 출력의 값 미검사 | Q32: 출력 하위 질문 4개가 기대와 대응되지 않아 값 검사를 건너뛰고 보류로 판정 | 값을 낸 모든 질문용 계산에 "질문한 지표의 행인가"를 1단계로 검사 (`asked_indicator`). criteria.md 3장 "1단계는 출력한 모든 내용에 적용"의 구현 누락분 |
| 기대 결과 빈틈 | Q11 `item_any`에 `0세`만 있어 1~5세 행을 다른 지표로 오판 | `core34` Q11 `item_any`에 연령 라벨 추가 (질문 의미는 같음) |

수정 후 과거 1 · 2 · 3 · 5회차의 자동 판정은 수정 전과 같다.

## 6. 재현 명령

```bash
python -m eval.generator.legacy profiling/modules36/results/full1.jsonl --runs 1,2 --out storage/runs/eval_generator/legacy/run12.jsonl
python -m eval.generator.legacy profiling/modules36/results/full1.jsonl --runs 3 --renumber --out storage/runs/eval_generator/legacy/run3.jsonl
python -m eval.generator.legacy profiling/modules36/results/full1.jsonl --runs 5 --renumber --out storage/runs/eval_generator/legacy/run5.jsonl
python -m eval.generator.report storage/runs/eval_generator/legacy/run12.jsonl --set core34
python -m eval.generator.render storage/runs/eval_generator/legacy/run12.jsonl
python -m eval.generator.faults storage/runs/eval_generator/legacy/run5.jsonl
python -m eval.generator.report --compare storage/runs/eval_generator/legacy/run12_report/verdicts.jsonl storage/runs/eval_generator/legacy/run5_report/verdicts.jsonl
```
