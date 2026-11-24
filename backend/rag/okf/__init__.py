"""
OKF 지식 카탈로그 (Open Knowledge Format v0.3) — 표·분류·개념 지식의 단일 원천

  storage/okf/                         번들 (git 에 커밋, docs/OKF_FORMAT.md)
    index.md · log.md                  번들 정보 (okf_version "0.3") · 변경 기록
    tables/<기관>/<tbl_id>.md          type: Stat Table       ← 프로필에서 자동 생성 (tables.py)
    classifications/<kind>-<해시>.md   type: Classification   ← 코드가 많은 차원 (자동 생성)
    concepts/<영역>/<slug>.md          type: Stat Concept     ← 사람이 관리 (코드 하나 = 개념 하나)
  storage/okf_build/<해시>/            파생물 (vocab.json · aliases.json · catalog.json · codebooks.json …)
  storage/okf_build/CURRENT            지금 쓰는 빌드 해시 (원자적 교체 — build.py)

  doc.py      md 읽기·쓰기 (프론트매터 · 사람 구간 보존 · 경로 해석)
  tables.py   프로필 → 표·분류 파일 (내용이 같으면 쓰지 않음 → git diff 는 실제 변경만)
  lint.py     참조 무결성 검사 (빌드 전에 오류면 멈춤)
  build.py    파생물 빌드 + CURRENT 교체
  catalog.py  실행 중 조회 (표 · 질문에 걸린 개념 · 코드북)
  curate.py   별칭 옮기기 (vocab_aliases.csv · 학습 사전 → 개념 파일) · 승인

  python -m backend.rag.okf tables | lint | build | show | migrate | approve
"""
