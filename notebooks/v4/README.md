# v4 노트북

저장소 루트(또는 이 폴더)에서 열기. 실제 데이터·HCX 없이 구조만 보려면 `V4_NB_FAKE=1` 환경변수로 Jupyter 를 띄운다
(가짜 KOSIS 데이터 + HCX 대역. 전체 흐름 노트북은 충돌 재현용 표도 넣음).

| 노트북 | 보는 것 |
|---|---|
| **`pipeline_v4_e2e.ipynb`** | **질문 → ① 쿼리 분석 → ② 검색(구성별) → ③ View 묶음 → ④ 충돌·선택 → ⑤ 최종 View(잘라 낸 표)** 를 한 번에, 단계별 입력·파라미터·출력 표. 실험 질문 여러 개 요약 + 질문별 자세히 + 선택 + 결과 저장 |
| `query_v4_steps.ipynb` | ① 쿼리 모듈 단계 함수를 하나씩 (CSV 값 사전 · 동의어 · 접지 · 시점 규칙 · 되묻기 · 서브쿼리) |
| `retrieval_lab.ipynb` | ② 검색 구성 비교 (토크나이저·임베더·리랭커·합치기) · 보고서 · 사람 판정 → 점수 |
| `view_conflict.ipynb` | ③④ View 묶음 · Point · 충돌 판정 · 선택 3가지 방법 · 허용 오차 |

`e2e_helpers.py` 는 `pipeline_v4_e2e.ipynb` 의 화면 출력 함수 (계산은 모두 backend 함수 — API·CLI 와 같음).
실행 Windows 예: `set V4_NB_FAKE=1 && jupyter lab` (PowerShell: `$env:V4_NB_FAKE=1; jupyter lab`)

**평가 질문 단계별 검수 카드**는 `eval/pipeline_review/review_v4.ipynb` (질문 파일의 질문 문장만 → 질문마다 단계별 근거 카드 HTML·PNG →
단계별 판정·첫 실패 단계 → 집계). 설명: `docs/query_retrieval_v4/REVIEW_V4.md`
