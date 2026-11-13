"""
[NEW] 모듈 6 — 답변 · 통계 표 생성

  입력: 질문(QueryBundle) + View(Record) + 모듈 3 의 계산 결과(CalcResult · displays)   스키마: backend/schemas/answer.py
  출력: 답변 문장 + 근거 표(계산 요약 · 계산 목록 · 원본 View) + 주의사항(caveats)

  facts.py        표시 · 이름 공통 함수 (format_value 재사용, 조사 처리)
  caveats.py      View 의 못 맞춘 조건 · 계산 실패 → 주의사항 목록
  tables.py       AnswerTable 만들기. 계산에 쓴 View 행 강조, 행 제한
  placeholder.py  '{a1}' 자리표시자 치환 + 검사 (풀 수 없음 · 날숫자 · 인용 누락)
  template.py     HCX 를 쓸 수 없을 때의 규칙 문장
  write.py        HCX 호출 (프롬프트: agent/prompts.py ANSWER_COMPOSE_*)
  graph.py        LangGraph: build_tables → write → fill → check (실패 시 1회 재시도, 그래도 실패면 template) → assemble
  pipeline.py     진입점 run_module6(Module6Request) → Module6Output   (API: backend/api/v1_answer.py)
"""
