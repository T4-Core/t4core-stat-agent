# 검증된 M3 출력 (Oracle 조건, 계획 2.4.2)

- 파일: `<질문 id>.json` = `Module3Output` 전체(JSON). 모듈 6 입력에 쓰이는 필드(`calc_results` · `displays` · `chart_plan.answer_steps` · `chart_plan.warnings` · `chart_plan.withheld`)를 사람이 원본 View와 대조해 확정한다.
- 값은 M3 스키마 표현 그대로 둔다(share = `17.458`, 단위 `%`). 평가 정규형으로 바꾸지 않는다.
- 같은 문항 · 같은 실행에서 저장한 `Module6Request`가 있어야 짝 실행이 된다(`run.py --mode oracle`). 과거 slim trace는 대상이 아니다.
- 아직 확정한 파일이 없다. live 실행 결과에서 통과로 판정된 문항의 `requests.m3` 결과를 옮기고 검토한 뒤 추가한다.
