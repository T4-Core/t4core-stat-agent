# 개념 파일 (사람이 관리)

통계 개념 하나(분류 코드 하나 또는 항목 하나) = 파일 하나. 이름은 영문 slug, 제목은 한글.

- 형식: [docs/OKF_FORMAT.md](../../../docs/OKF_FORMAT.md) — `type: Stat Concept`, `x-t4-concept` (aliases · not · binds · calc)
- 처음 만들기: `python -m backend.rag.okf migrate aliases` (vocab_aliases.csv → 개념 파일)
- 벡터+HCX 가 제안한 별칭 승인: `python -m backend.rag.okf pending` → `python -m backend.rag.okf approve <표현>`
- 새 개념이 자동으로 생기면 `_inbox/` 에 놓임 → 정의·경계를 채우고 알맞은 폴더(예: household/)로 옮기기
- 고친 뒤: `python -m backend.rag.okf lint` → `python -m backend.rag.okf build`

이 README 는 프론트매터가 없어 OKF 문서로 읽히지 않습니다 (OKF v0.3).
