# eval/generator — Generator 평가 도구 (KOS-40)

모듈 2 · 3 · 5 · 6 + QA의 출력 품질을 재현 가능한 절차로 측정한다.

- 기준: [docs/criteria.md](docs/criteria.md) · 방법: [docs/method.md](docs/method.md) · 기준선: [docs/baseline.md](docs/baseline.md)

## 빠른 시작

```bash
# 1) 실행 (실제 HCX, 질문마다 하나씩)
python -m eval.generator.run --mode live --set core34 --runs 2 --tag 1123_base
# 2) 판정 · 집계 (HCX 없음) → storage/runs/eval_generator/1123_base/runs_report/{report.md, summary.json, verdicts.jsonl, review.csv}
python -m eval.generator.report storage/runs/eval_generator/1123_base/runs.jsonl.gz --set core34
# 3) 판정 시트를 채운 뒤 다시 집계
python -m eval.generator.report storage/runs/eval_generator/1123_base/runs.jsonl.gz --set core34 --review review.csv
# 4) 수정 전후 비교
python -m eval.generator.report --compare <이전>/runs_report/verdicts.jsonl <이후>/runs_report/verdicts.jsonl
# 5) v2 보완 데이터셋 (외부 경로, questions/README.md 참고)
python -m eval.generator.v2 check --dataset <v2 경로>
python -m eval.generator.run --mode isolated --v2 <v2 경로> --runs 2 --tag v2_isolated
python -m eval.generator.run --mode isolated --v2 <v2 경로> --slots eval/generator/questions/v2_slots.json --runs 2 --tag v2_isolated_slots
python -m eval.generator.report storage/runs/eval_generator/v2_isolated/runs.jsonl.gz --v2 <v2 경로>
```

## 구성

| 파일 | 역할 |
|---|---|
| `run.py` | live · replay · oracle · isolated · m3_only 실행기. ViewSet · analysis · 모듈 요청 전체 · HCX 호출 · QA 검사 시간 기록 |
| `verdict.py` | 질문 단위 판정 (0단계 범위 → A0 → 1단계 출력 정확성 → 2단계 완전성), 회차 병합 |
| `report.py` | 지표 집계 · 보고서 · 판정 시트 · 쌍 비교 |
| `status.py` | 기대 상태(조건 술어 · A0 기대 라벨) |
| `subq.py` | 기대 하위 질문 ↔ 출력 하위 질문 대응 |
| `resolve.py` | 좌표 · CalcInput → 원본 행, `operands_valid` |
| `claim.py` | 답변 문장의 claim 추출 (숫자 + 단위 + 부호 + 방향어 + 지역 · 연도 레이블, 한국어 수량 합산) |
| `binding.py` | claim 기준 numeric_match · 단위 · 부호 · semantic_ok (binding 기대가 없으면 N/A) |
| `schema_v2.py` · `v2.py` | v2 데이터셋 스키마 · 내부 Question 변환, 경로 · 해시 검증, probe 실행 기록 · fixture, 입력 슬롯 overlay 적용 · 검증 |
| `questions/v2_slots.json` | v2 isolated 입력 슬롯 overlay (oracle 질의 분석 형식) |
| `checks/chart_structure.py` | 차트 구조 판정: 요구 결과 · 조건(정답 좌표 기준) · 표시 · 좌표 포함. 판정 규칙 버전(`JUDGE_RULES`) 2 이상 실행에만 적용 |
| `display_ref.py` | 기대 표시값 (팀 `format_value`와 독립 구현) |
| `reason_codes.py` | 보류 사유 문장 → 사유 코드 |
| `chart_extract.py` | 차트 유형별 figure · ChartContent 정규형 비교 |
| `checks/` | 모듈별 점검 (`m2` · `m3` · `m5` · `m6` · `chart_request` · `qa_semantic` · `normalize`) |
| `render.py` | 모듈 5 재렌더링 + Fidelity · Lint (HCX 없음) |
| `contract.py` | 저장 출력에 현재 QA 스키마 검사 |
| `faults.py` | Fault Injection · FI-SEM · FI-CONTRA · Policy Compliance |
| `metamorphic.py` | MT-1 · MT-2 · MT-3a |
| `legacy.py` | 과거 slim trace → RunRecord |
| `questions/` | 질문 세트 (`core34` 버전 고정(immutable) · `ext_chart_request`) |
| `oracle/m3/` | 검증된 M3 출력 (Oracle 조건) |

## 테스트

```bash
t4core-stat-agent/.venv/Scripts/python -m pytest tests/eval_generator -q     # HCX 없음
```

## 경로

실행 결과는 `backend.core.config.EVAL_RUNS_DIR`(기본 `storage/runs/eval_generator`, git 제외)에 둔다. 저장소에는 질문 세트 · 문서 · 도구 · 테스트만 둔다.
