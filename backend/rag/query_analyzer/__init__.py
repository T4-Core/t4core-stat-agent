"""질의 분석 — 질문 → QueryAnalysis (analyze.analyze)

재작성 (HCX 1회, rewrite.run_pipeline)
  terms.py      일상어 사전 (dictionary/term_dict.json) — HCX 에 넘길 용어 힌트, 일상어 단어 가리기
  extract.py    코드 추출: 상대 시점·연도 범위, 시도·성별·연령·국적·출생연도 (dictionary/rule_dict.json)
  slots.py      HCX 슬롯 추출 (프롬프트)
  validate.py   슬롯 검증 (질문에 없는 값 빼기, 계산 단어 떼기, 하위 질문 정리)
  measures.py   계산 단어·일반 지표 구분 (validate · decompose 공용)
  sentence.py   슬롯 → 문장
  rewrite.py    위 단계를 묶어 RewriteBundle

분석 (CSV 값 사전 기반, analyze.analyze)
  lexicon.py    동의어 조회 (rule_dict > CSV 값 사전 > term_dict > 학습 사전)
  grounding.py  슬롯 값 → CSV 값·표 접지
  clarify.py    시점 규칙 · 필수 슬롯 확인 · 되묻기 후보 · 선택 반영
  decompose.py  표 단위 서브쿼리 분리
  roles.py      분모·조건 검색 단위
  search_text.py 검색 문장
  adapter.py    재작성 슬롯(문자열) → View 입력 슬롯 (연도 int · 연령 {from,to} · View 의도 4종)
  values.py     시점·연령 문자열 파싱
"""
