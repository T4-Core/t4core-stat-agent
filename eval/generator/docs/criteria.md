# Generator 평가 기준

- 대상: 모듈 2 `chart_decision` · 3 `chart_calculate` · 5 `draw_chart` · 6 `answer_compose` · QA (`backend/agent/qa`)
- 범위: ViewSet 이후부터 사용자에게 나간 최종 응답까지. 질의 분석 · 검색 · View 품질은 `synthetic_gold_pipeline/score_rag_results.py`가 평가한다.
- 기준 코드: `develop` `e719402`
- 합격선은 **제안값**이며 팀 합의 후 확정한다(6장).

## 1. 평가 계층

| 계층 | 실행 모드 | 입력 | 목적 |
|---|---|---|---|
| Generator E2E | `live` | 질문 → 질의 분석 → ViewSet → QA 경로 | 사용자가 받는 품질 |
| Generator E2E | `replay` | 저장한 ViewSet + analysis | 검색의 회차 간 변동을 뺀 Generator 품질 |
| QA ablation | `replay --no-qa` | 같은 스냅샷 → 직렬 `run_modules` | QA on/off 비교 전용 |
| Component | `oracle` | 저장한 `Module6Request` + 검증된 M3 출력 | M3 출력 대체의 관측 개선 폭 |
| Component (규칙) | `offline` | 저장한 trace | 자동 점검, 모듈 5 재렌더링, QA fault injection, 스키마 점검 |

- 운영 입구(`run_chat(answer_mode="modules")`, `POST /api/v1/agent/modules`)는 모두 QA 경로다. **판정 대상은 QA 적용 후 사용자에게 나간 최종 `result`다.**
- 실행 경로(`qa` / `modules`)와 모드가 다른 결과는 합쳐서 집계하지 않는다.
- Oracle 조건과 Pipeline 조건의 점수 차이는 "M3 출력 대체의 관측 개선 폭"이다. M3의 독립 오류 기여도로 해석하지 않는다.

## 2. 기대 결과 (질문 세트)

### 2.1 범위와 답변 가능성
- `scope: in | out`은 **실행 전 고정값**이다. `analysis.status`로 정하지 않는다.
- 하위 질문마다 `answerable_when` 규칙으로 기대 상태(`answer` / `hold` + 사유 코드)를 정한다. 질문 기대 상태는 하위 질문 기대 상태의 집계다(전부 answer → answer, 전부 hold → hold, 섞임 → partial).
- 조건 술어는 **ViewSet만** 본다. Generator 출력과 `analysis.status`를 보면 순환 판정이 된다.
- 계산이 필요한 하위 질문(`m3.op` ≠ `raw`)은 `operands_valid`를 쓴다.

### 2.2 `operands_valid`
피연산자 좌표마다 ViewSet의 Record에서 행을 찾고 차례로 검사한다. 처음 실패한 검사의 사유 코드가 기대 보류 사유다.

| 순서 | 검사 | 실패 시 사유 코드 |
|---|---|---|
| 1 | 좌표에 맞는 행이 정확히 1개 (지정하지 않은 차원은 합계 행 우선, 항목은 앞부분 일치 우선) | `missing_operand` · `missing_denominator` · `ambiguous_row`(수동) |
| 2 | 값이 숫자이고 결측 표기가 아님 | `missing_value` |
| 3 | 분모 ≠ 0 (`share` · `ratio` 분모, `growth_rate` · `cagr` · `index` 기준값) | `zero_denominator` |
| 4 | 같은 시점을 요구하는 연산(`share` · `diff` · `ratio` · `combine`)의 시점이 같음 | `period_mismatch` |
| 4a | 수록 주기가 같고 모두 알려짐 | `cycle_mismatch` |
| 5 | 단위 정합 (연산별, 아래 표) | `unit_mismatch` |
| 6 | `share`의 분자 · 분모가 비교 차원 밖의 차원에서 같음 | `population_mismatch` |

| 연산 | 단위 요구 | 결과 단위 |
|---|---|---|
| `diff` · `combine` · `share` | 모두 같은 단위 (M3 `same_unit=True`와 같은 엄격 규칙). 환산 가능(천명 ↔ 명)해도 `unit_mismatch` + `convertible_unit` 태그(개선 후보, False-hold로 세지 않음) | `diff`: 같은 단위(`%`끼리 `%p`), `share`: `%` |
| `ratio` | 검사 없음. 대신 분자 · 분모 항목과 결과 단위(`m3.result_unit`)를 검사 | 같으면 `배`, 다르면 `분자/분모` (예: 명/㎢) |
| 그 밖 | 단일 계열 | `growth_rate` · `cagr`: `%`, `index`: 지수 |

### 2.3 A0 기대 라벨
A0 조기 중단 기대는 하위 질문 보류 사유와 **분리해서** 입력 스냅샷으로 정한다.

| 순서 | 조건 | 라벨 |
|---|---|---|
| 1 | ViewSet `status` ≠ `ok` | `stop_status` |
| 2 | `ViewSet.records`가 비어 있음 | `stop_no_data` |
| 3 | analysis 메모의 미등록 지표가 역할 단위가 아닌 모든 단위의 지표이고, 어느 Record의 항목에도 없음(평가기가 Record를 직접 본다) | `stop_indicator_not_found` |
| 4 | 그 밖 | `continue` |

`stop_*`이면 하위 질문 기대는 모두 `hold`이고 사유는 A0 사유(`no_data` · `item_mismatch`)다. 분모 누락처럼 Record는 있는데 계산이 안 되는 경우는 `continue`이며 M3가 보류해야 한다.

## 3. 질문 단위 판정

판정은 단계 순서대로 한다. **출력한 정보가 틀렸는지가 상태 조합보다 우선이다.**

### 0단계: 범위
| `scope` | 관측 | 판정 |
|---|---|---|
| `out` | 범위 밖 안내 | 통과 |
| `out` | 통계 답변 | 미달 (`scope_error:false_in`, M1+R) |
| `in` | `out_of_scope` · 되묻기 | 보류 (`scope_error:false_out`, M1+R). 하위 질문 지표 분모 제외 |
| `in` | QA A0 중단 | 하위 질문 관측을 모두 `hold`로 두고 1 · 2단계. 모듈 2~6 지표 분모 제외 |

### 1단계: 출력 정확성 (상태와 무관하게 출력한 모든 내용) — 하나라도 실패하면 **미달**

| 조건 | 내용 | 자동 | 귀책 |
|---|---|---|---|
| C1 연산 | 대응된 하위 질문의 연산이 기대 op | 자동 | M3 |
| C2 수치 | 계산 값이 기대값과 일치 ((a)층). 값이 하나인 결과의 key가 다르면 실패 | 자동 (기대값이 없으면 수동) | M3 |
| C2 피연산자 | 기대 피연산자 · 분모 좌표가 계산 입력의 원본 행에 있음 | 자동 | M3 |
| C3 결과 단위 | 표시 단위가 연산 · 입력 단위로 정해지는 결과 단위와 같음 (F1 `1세이상` 유형) | 자동 | M3 |
| C3 표시 반올림 | 계산 요약 표의 결과 문자열 == 기대 표시값 ((c)층) | 자동 | M3 |
| C3 binding | FINAL 값이 기대 지역 · 기간 · 지표에 연결됨 (`semantic_ok`). binding 기대가 없으면 N/A | 자동 (모호하면 수동) | M6 |
| C3 claim 단위 · 부호 · 자릿수 | 답변 숫자의 단위 · 부호 · 요구 자릿수 (`claim_unit` · `claim_sign` · `required_digits`, 4.3) | 자동 | M6 |
| C3 근거 가시성 | LLM 답변의 숫자 · 근거 라벨이 M6 가시 문맥에 있음 (`invisible_citation`, 4.4) | 자동 | M6 |
| C3 인과 단정 | 근거 없는 인과 단정 (`unsupported_causal`, 4.4). 가능성 표현은 수동 | 자동 (가능성 표현은 수동) | M6 |
| C3 방향 | 기대 방향과 증감 단어가 맞음 | 자동 | M6 |
| C4 필수 주의사항 | 추계 표를 썼으면 추계 고지, 요청 시점이 없으면 그 사실 고지 | 자동 | M6 (`failed_to_contain`) |
| 기대 hold인데 값 | 근거(원본 행 복원 · share 분자≠분모 · 질문한 지표)가 없으면 실패 | 자동 | M3 |
| C5 금지 문구 | `None` · `nan` · `내부 오류` 등 | 자동 | M6 |
| C6 차트 | 렌더링 실패, Chart-Data Fidelity 불일치 | 자동 | M5 |
| 단위 의미 | 지표와 표 메타데이터 단위가 어긋남 (혼인건수인데 `명`) | 수동 | data |

### 2단계: 완전성 (1단계를 통과한 응답만)

| 하위 질문 기대 | 관측 | 결과 |
|---|---|---|
| `answer` | 값 있음 | 충족 |
| `answer` | 보류 · 누락 + 고지 | 미충족(고지) |
| `answer` | 보류 · 누락, 고지 없음 | 미충족(`silent_omission`) |
| `hold` | 보류 · 누락 + 고지 | 충족 (사유 코드가 다르면 Hold Reason 지표에만 반영) |
| `hold` | 근거 있는 값 + 고지(대체 시점 등) | 충족 + `rule_review` · `needs_review` |
| `hold` | 근거 있는 값, 고지 없음 | 미충족(`silent_omission`) + `needs_review` |

질문 판정: 1단계 실패 → **미달** / 미충족 있음 → **보류** / 그 밖 → **통과**.
- v2 문항(`strict_final`)은 계산이 됐어도 FINAL claim이 답변 문장에 없으면 **보류**다 (하위 질문 하나를 답변에서 빠뜨림).
- `m3_only` 조건은 모듈 3 항목(연산 · 계산 · 보류)만 보고, 완전성은 기대대로 값을 냈는가 · 보류했는가로 정한다(고지는 모듈 6 몫).
- 자동 판정이 정하지 못한 항목(`ok=None`)은 `needs_review` 태그로 판정 시트에 넘긴다. 사람이 판정 시트의 `verdict`를 채우면 그 값이 최종이다.
- 기대가 hold인 하위 질문을 올바르게 보류하면 **Generator 기준 통과**다. 사용자 질문은 답을 받지 못했으므로 E2E 응답률을 함께 보고하고, First Failure는 `M1+R`로 기록한다.

### 회차 병합 · 귀책
- 질문 판정 = 회차 판정의 최솟값(미달 < 보류 < 통과). 회차 판정이 다르면 `unstable`.
- First Failure: `M1+R`(질의 분석 · 검색 · View) · `M2` · `M3` · `M5` · `M6` · `QA` · `data`. 자동 후보를 판정 시트에서 확정한다. 뒤 단계가 막거나 알렸어야 하는 경우는 `failed_to_contain` 태그로 따로 기록한다.

## 4. 수치 비교

### 4.1 평가 정규형
| 관측 단위 | 정규형 | 변환 |
|---|---|---|
| `%` | `ratio` | ÷ 100 |
| `%p` | `pp` | ÷ 100 (`ratio`와 비교하지 않음) |
| `배` | `times` | 그대로 |
| 천명 · 만 명 등 | 원단위 | × 배율 |

정규형은 평가기 안에서만 쓴다. Oracle 입력에는 M3 스키마 표현을 그대로 넣는다.

### 4.2 허용오차 3층
| 층 | 비교 | 기준 |
|---|---|---|
| (a) 원값 계산 | `CalcResult` 값 vs 기대 원값 | 개수 단위 `atol=0.5`, 파생값 `rtol=1e-6` (문항별 `atol` · `rtol`로 덮어씀) |
| (b) figure 좌표 | figure 값 vs `v / unit_scale` | `rtol=1e-9` (렌더러는 반올림하지 않음) |
| (c) 표시 반올림 | 표시 문자열 vs 기대 표시값 | 정확히 일치. 기대 표시값 = `Decimal(repr(v)) / Decimal(repr(unit_scale))` → `ROUND_HALF_UP` → 음수 0 제거. 천명 → 만 명은 `|값| ≥ 100`이거나 0이면 소수 0자리. 문장 숫자를 원값과 비교할 때만 원단위 `0.5 × 10^-digits × unit_scale` |

표시 기대값은 팀 `format_value`를 import하지 않고 독립 구현(`display_ref.py`)하며, 같은 경계값 목록을 양쪽에 건다.

### 4.3 numeric_match와 semantic_ok
문장은 claim 단위로 읽는다(`claim.py`): 숫자 + 단위 + 부호 + 방향어 + 지역 · 연도 레이블. 한국어 수량은 한 숫자로 합친다(`23만 8,317` → 238317). 연도 · 월 · 순위 · `1명당`은 claim이 아니다.
- `numeric_match`: 기대값과 크기가 같은 claim이 있다. 허용오차는 max(표시 허용오차, 그 숫자 표기의 정밀도).
- `claim_unit`: 그 claim의 단위가 기대 단위와 같은 정규형이다(명 ≠ 가구, % ≠ %p). 단위를 적지 않았으면 판정하지 않는다.
- `claim_sign`: 음수 기대값은 음수 부호 또는 감소 · 순유출 방향어가 있어야 한다. 양수 수준값의 방향어는 추이 서술이라 판정 근거가 아니다.
- `semantic_ok`: 숫자 앞 가장 가까운 지역 레이블 · 연도 · 항목 어휘가 기대 binding과 맞는다. 분모 위치 지역(`전국 대비` · `전국 중`)은 대상이 아니다. 그 값을 만든 계산의 원본 행을 복원해 구조 좌표도 대조하고, 복원이 모호하면 `binding_unresolved`(수동). **binding 기대가 없으면 N/A**(행을 내지 않는다).
- `required_digits`: 질문이 정밀도를 요구하거나(`소수 셋째 자리`) v2 claim에 `display.digits`가 있으면, 표기 정밀도가 요구 자릿수 이상이어야 한다.
- Answer Accuracy = `numeric_match ∧ semantic_ok`. `numeric_match=1 ∧ semantic_ok=0` 건수를 따로 보고한다.

### 4.4 근거 가시성과 인과 단정
- `invisible_citation`: LLM이 쓴 답변(`method=hcx`)의 숫자는 M6 프롬프트에 실린 자리표시자 값(`m6_shown_tokens`, 없으면 기록된 M6 메시지에서 추출)이나 질문 속 숫자여야 한다. 목록 개수 표현(`외 14개`)은 제외한다. v2 문항은 답변의 근거 라벨(`[E1]`)이 가시 근거 라벨이어야 한다. 템플릿 답변은 대상이 아니다.
- `table_complete`(지표): 사용자 표가 목록 결과의 점을 모두 담았는가. 문장 인용 가능성과 따로 센다.
- `unsupported_causal`: 답변이 인과를 단정(`때문`, `로 인해`, `효과가 입증`, `초래했다` 등)하고 근거에 인과 항목이 없으면 1단계 실패. 가능성 표현(`~일 수 있다`)은 수동 판정, 산술 설명(문장의 숫자가 모두 계산 결과 · 입력값)과 보류 고지는 대상이 아니다.

## 5. 지표

| 모듈 | 지표 | 정의 |
|---|---|---|
| E2E | 통과 · 보류 · 미달률 | 질문 단위 병합 판정 |
| E2E | Generator 귀책 미달 | 미달 중 First Failure ∈ {M2, M3, M5, M6, QA} |
| E2E | failed_to_contain · silent_omission · scope_error · needs_review | 태그가 붙은 질문 수 |
| E2E | 판정 안정성 | 회차 판정이 모두 같은 질문 비율 (2회 이상) |
| E2E | 응답률 | 값을 낸 회차 비율 |
| E2E | 정직한 실패 | 보류 · 누락이 있는 회차 중 모두 고지한 비율 |
| E2E | 답변 방식 · 지연 · HCX 호출 · 예외 | `method` 분포, 평균 · 중앙 · 최대(초), 호출 · 실패 수 |
| M2 | Acceptable-set Accuracy · Measure Accuracy | 기대 하위 질문 단위 |
| M2 | Sub-question Coverage | 기대 answer 하위 질문 중 대응된 출력이 있는 비율 |
| M2 | Request Parse · 요청 오인식 | 차트 지정 요청 해석 |
| M3 | Plan Validity · Operation · Operand · Execution | 1단계 항목의 통과율 |
| M3 | Hold Recall · False-hold | 기대 hold 중 보류 · 고지 / 기대 answer 중 보류 |
| M3 | Hold Reason Accuracy | 평가기 사유 코드 일치 (미분류는 분모 제외, 건수 표시) |
| M5 | Render Success | `drawn` ÷ (`drawn` + `failed`). `skipped`는 사유별 건수 |
| M5 | Chart-Data Fidelity · Spec Lint · Fallback Rate | 차트 유형별 extractor 정규형 비교 · 축 제목 · % 표기 · 범례 |
| M6 | First-pass · 형식 검사 · binding · 방향 · 주의사항 | `method == hcx` 비율, 자리표시자 검사, 4.3, 1단계 |
| E2E | Request Outcome · Notice 정합 | 차트 요청의 최종 결과와 안내 |
| QA | Detection Recall · Precision · False Alarm · Severity · Per-type | 형식 fault injection (내용 경고 제외) |
| QA | Semantic Detection P/R · FI-SEM Recall · 알았지만 나감 | 내용 경고 detector |
| QA | Unanswerable Detection P/R · 답할 수 있는 질문을 막음 | A0 기대 라벨 대비 |
| QA | Policy Compliance · 재시도 상한 위반 | 변이 출력에 대한 재시도 · 빼기 · 중단 |
| QA | Retry Rate · Stop by Stage · QA 경로 E2E 지연 차이 · 검사 시간 | 운영 지표. `qa.status`는 품질 지표로 쓰지 않는다 |

분모가 0인 지표는 `N/A`로 보고한다. 어댑터로 추정한 값(`source=adapter`)은 건수를 함께 표시한다.

## 6. 합격선 · 회귀 (제안, 팀 합의 필요)

| 구분 | 조건 |
|---|---|
| 필수 | Generator 귀책 미달 0건 |
| 필수 | `failed_to_contain` 미달 0건 |
| 목표 | 통과율 ≥ 70%, 미달율 ≤ 5% (`core34`) |
| 목표 | 판정 안정성 ≥ 95% (2회 이상) |
| 목표 | M5 Render Success ≥ 98%, Chart-Data Fidelity 100% |
| 목표 | QA Detection Recall ≥ 95%, False Alarm ≤ 2% |
| 목표 | Request Outcome Accuracy ≥ 95%, 요청 오인식 0건, Chart Notice 정합 100% |
| 참고 | Template 비율 ≤ 20%, 중앙 지연 ≤ 60초 |
| 참고 | `silent_omission` · `scope_error` · `numeric_match ∧ ¬semantic_ok` 0건, A0가 답할 수 있는 질문을 막은 회차 0건 |

회귀 판정: 다음 중 하나면 회귀다.
1. 이전 실행에서 통과였던 질문이 모든 회차에서 미달
2. Generator 귀책 미달이 늘어남
3. offline 지표(Fault Injection Recall, Render Success, Fidelity)가 이전 값보다 낮아짐

수정 전후는 같은 세트 · 같은 모드 · 회차 2회 이상으로 비교하고, 비율보다 질문 단위 쌍 비교(`report --compare`)를 먼저 본다.
