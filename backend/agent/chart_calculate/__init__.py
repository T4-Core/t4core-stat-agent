"""
[NEW] 모듈 3 — 질문 계산 + 차트용 계산·내용 구성·검증

  명세: docs/discussions/2026-11-09-차트-계산-명세.md   스키마: backend/schemas/chart.py

  select.py    Record.table.rows 에서 행 고르기 (검증 ① 데이터 존재)
  display.py   단위 추출 · digits 기본값 · displays 등록 · 표시 문자열
  calculate.py 연산 11종 실행 (Step → Calc → CalcResult)
  specs.py     차트 15종 표 (필수 역할 · 행 구조 · 기본 requirements)
  validate.py  차트 검증 ①·② (ChartContent → CheckResult)
  content.py   ChartContent 구성 · 대체 차트 재구성 · validation 출력
  planner.py   HCX 결정(Decision) + 모듈 2 charts[] → ChartPlan · displays (규칙 부분, HCX 호출 없음)
  decide.py    HCX 호출 → Decision (프롬프트: agent/prompts.py CHART_PLAN_*)
  pipeline.py  진입점 run_module3(Module3Request) → Module3Output   (API: backend/api/v1_chart.py)
"""
