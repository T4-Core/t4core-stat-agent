# answer_compose — 모듈 6 (답변 · 통계 표 생성)

모듈 3(질문 계산 + 차트용 계산)이 계산한 결과를 받아 **답변 문장**과 **근거 표**를 만든다.
LLM(HCX)은 문장의 틀만 쓰고, **답변 속 숫자는 전부 모듈 3의 `CalcResult` 값에서 코드가 채운다.**

> 상세 명세: [docs/discussions/2026-11-13-모듈6-구현-명세.md](../../../docs/discussions/2026-11-13-모듈6-구현-명세.md)
> 상태: 구현 완료, 팀 합의 전. **실제 HCX 호출은 아직 확인하지 못했다** (테스트는 가짜 `chat` 함수로만 돈다).

## 한눈에 보기

```
Module3Output.calc_results ─┐
Module3Output.displays      │
chart_plan.answer_steps     ├─▶ Module6Request ─▶ run_module6() ─▶ Module6Output
chart_plan.warnings         │                                       ├ answer      답변 문장
records · query_bundle ─────┘                                       ├ tables      계산 요약 · 계산 목록 · 원본 View 표
                                                                    ├ caveats     주의사항 (못 맞춘 조건 · 계산 실패 · 보류 사유)
                                                                    └ method      hcx | hcx_retry | template | none
```

- 스키마: [`backend/schemas/answer.py`](../../schemas/answer.py)
- API: [`backend/api/v1_answer.py`](../../api/v1_answer.py) — `POST /api/v1/answer/compose`, `/compose/trace` (Swagger 예시 포함)
- 프롬프트: [`backend/agent/prompts.py`](../prompts.py) 의 `ANSWER_COMPOSE_*`

## 쓰는 법

```python
from backend.agent.answer_compose.pipeline import run_module6, run_module6_trace
from backend.schemas.answer import Module6Request

m3 = run_module3(module3_request)                      # 모듈 3
req = Module6Request(
    query_bundle=module3_request.query_bundle,
    records=module3_request.records,                   # 모듈 3에 넣었던 View
    calc_results=m3.calc_results,
    displays=m3.displays,
    answer_steps=m3.chart_plan.answer_steps,           # 선택이지만 주는 것이 좋다 (아래 주의 참고)
    plan_warnings=m3.chart_plan.warnings,              # 계산을 보류한 사유를 답변까지 전달
)
out = run_module6(req)                                  # HCX 호출. 테스트는 run_module6(req, chat=가짜함수)
trace = run_module6_trace(req)                          # 시도마다 프롬프트 · 초안 · 걸린 문제까지
```

### 입력할 때 주의
| 필드 | 안 주면 |
|---|---|
| `answer_steps` | 극값의 방향(최대/최소)을 모른다 → "극값(최대 또는 최소)은 …"으로 단정하지 않고 쓴다. 표의 강조 행이 같은 값의 다른 지역 행까지 잡힐 수 있다 |
| `plan_warnings` | "서울 질문인데 부산 자료만 있어 계산을 보류했다" 같은 이유가 답변에 안 나온다 |
| `displays` | 숫자가 단위별 기본 자릿수로 표시된다 |

## 처리 흐름 (LangGraph, `graph.py`)

```
START → build_tables ─┬ 계산 결과 없음 ────────────────────────────→ assemble   (method=none)
                      ├ 값 있는 계산 없음 → template ──────────────→ assemble   (HCX 안 부름)
                      └ write → fill → check ─ 통과 ───────────────→ assemble
                           ▲                  ├ 실패 1회째 → write (고칠 점을 알려 주고 다시)
                           └──────────────────┘ 실패 2회째 · HCX 오류 → template → assemble
```

| 파일 | 하는 일 | HCX |
|---|---|---|
| `facts.py` | 값 표시(`format_value`), 조사, 방향(끝−처음), 고정 대상(지역 등) 복원, 행 찾기 | — |
| `caveats.py` | `plan_warnings` · View 의 못 맞춘 조건 · 계산 실패 → 주의사항 | — |
| `tables.py` | 계산 요약표 · 목록표 · 원본 View 표 (계산에 쓴 행 강조, 행 제한) | — |
| `reasons.py` | 계산 불가 사유를 사용자용 문장으로 (`join_on 필요` → `비교할 시점을 정하지 못했습니다`) | — |
| `placeholder.py` | `{a1}` 치환 + 검사 | — |
| `template.py` | 연산별 규칙 문장 (HCX 실패 시 마지막 수단) | — |
| `write.py` | 프롬프트 만들기, HCX 호출, 허용 자리표시자 목록 | 씀 |
| `graph.py` · `pipeline.py` | 노드 연결 · 진입점 | — |

## 자리표시자 — 가장 중요한 규칙

HCX는 숫자를 쓰지 않고 `{a1}` 같은 빈칸만 쓴다. 코드가 `CalcResult`로 채운다.

| 표기 | 뜻 |
|---|---|
| `{a1}` / `{a1.abs}` | 계산 결과 값 / 절댓값 (방향은 말로, 숫자는 `.abs`) |
| `{a1.rN}` (+ `.abs` `.key` `.rank`) | 목록 결과의 N번째 값 · 이름 · 순위 |
| `{a1.inN}` (+ `.abs` `.key`) | 계산에 쓴 N번째 입력값 · 시점. `.key`는 `2021년`처럼 "년"이 붙어 나온다 |
| `{a1.key}` | 한 점짜리 목록(극값 등)의 이름 |

`check`가 다음을 걸러내면 1회 다시 쓰게 하고, 그래도 안 되면 템플릿 문장으로 답한다.

1. 풀 수 없거나 **프롬프트에 보여 주지 않은** 자리표시자 (`{a1.r11}` 등)
2. 자리표시자 밖의 숫자 (질문 · 계산 키 · 항목 이름 · 주의사항에 이미 나온 숫자는 허용)
3. 값이 있는 계산의 **결과 값**을 인용하지 않음 (입력값 · 시점만 인용한 것은 인정 안 함. `{a1.in0.key}%` 도 오류)
4. 증가 · 감소 방향 모순 (방향은 값의 부호가 아니라 **끝 − 처음**)

## 표시 규칙 요약
- 연도 뒤에는 문장에서 "년"을 붙인다 (`2025년`). 표의 시점 칸은 `2025`.
- 같은 시점 · 지역은 문장 앞에 한 번만 (`2009년 서울특별시 인구수(…)가 부산광역시 인구수(…)보다 …`).
- 비율(`%`)끼리의 증감 · 차이는 `%p` (모듈 3의 `display.result_unit`).
- 비중(share)은 계산에 쓴 분모를 밝힌다 (`분모: 전국 대비 — 인구수 전국 2025년 …`).
- 계산 불가는 사유를 자르지 않고 보여 주되, 모듈 3 내부 문구는 `reasons.humanize`로 바꾼다. 어느 쪽 값이 빠졌는지(서울/부산)도 밝힌다.
- 일부 시점만 실패한 목록은 값이 있는 시점만 문장에 쓰고 끝에 `(2008년은 계산할 수 없습니다)`.

## 화면으로 확인하기 (질문 → 검색 → 계산 → 답변)

기존 모듈 3 테스트 화면([`frontend/chart-lab`](../../../frontend/chart-lab))에 **⑤ 모듈 6 답변·표** 단계를 붙였다.
질문을 넣으면 ① 질의 분석 → ② 검색·View → ②' 모듈 2 → ③ 모듈 3 → ⑤ 모듈 6 까지 한 번에 돈다 (실제 HCX 를 부르므로 `.env` 의 키가 필요하고, 전체 1~2분 걸린다).

```bash
.venv/Scripts/python.exe -m uvicorn backend.main:app --port 8000
# → http://localhost:8000/lab/chart-lab/
```

- ⑤ 에서 보이는 것: 답변 문장(방법 배지: HCX 첫 시도 / 재시도 / 규칙 문장 / 계산 결과 없음), 주의사항, 근거 표(계산 요약 · 계산 목록 · 원본 View — 계산에 쓴 행은 노란색), 시도마다 HCX 프롬프트 · 초안 · 걸린 문제.
- ⑤ 입력(`Module6Request`)은 ③ 결과로 자동 채워지고, 고쳐서 **⑤ 만 실행**할 수 있다.
- ③ 만 다시 돌리면 ⑤ 는 "낡음"으로 표시된다.

## 테스트

HCX 없이 돈다 (가짜 `chat` 함수).

```bash
.venv/Scripts/python.exe -m pytest tests/answer_compose -q
```

| 파일 | 내용 |
|---|---|
| `test_facts.py` · `test_tables.py` | 조사 · 표 · 강조 행 · 행 제한 |
| `test_placeholder.py` · `test_direction_share.py` | 치환 · 검사 · 방향 · 분모 |
| `test_template.py` · `test_template_ops.py` | 연산별 규칙 문장 (모듈 3 실제 계산 사용) |
| `test_reasons_fixed.py` | 사유 문구 · 지역 복원 |
| `test_review_fixes_m6.py` | 리뷰 지적(5건 + 재현 3건) 회귀 |
| `test_compose_pipeline.py` | 재시도 · 템플릿 대체 · 모듈 3 연결 · API |

## 알려진 한계 · 다음 할 일
- **실제 HCX 확인 전**이다. 서버를 띄워 `/api/v1/answer/compose` Swagger 예시로 한 번 돌려 보고, 프롬프트가 자리표시자 규칙을 잘 지키는지 본다.
- 최종 응답(`/api/v1/chat`)에는 아직 연결하지 않았다. 독립 API만 있다.
- `plan_warnings`는 호출하는 쪽이 넘겨야 한다 (자동 연결 없음).
- `CalcResult.value` 목록 원소의 모양 `{key, value, rank}`는 모듈 3 구현에 맞췄다. 모듈 3 담당자와 합의된 계약은 아니다.
- 날숫자 허용 범위 · 목록을 HCX에 보여 주는 개수(10) · View 표 행 제한(50)은 팀 확인이 필요하다.
- 모듈 3에 걸친 변경(`%p`, CAGR 경과 기간, 음수 기준값, 계산 보류와 `ChartPlan.warnings`)은 [모듈 3 명세](../../../docs/discussions/2026-11-09-차트-계산-명세.md)의 `[11-13]` 표시에 있다.
