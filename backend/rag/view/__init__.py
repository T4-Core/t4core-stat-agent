"""View — 검색 단위별 View 카드 · Point 충돌 판정 · 선택

  build.py      표 + 슬롯 → View 카드(Record)
  run.py        view_bundle → 검색 단위마다 표 검색 + View 카드
  points.py     Record → Point (교차점 key + 기본 단위 값)
  conflict.py   필수 메타 사용 확인(judge 슬롯 판정) + 같은 key 값 비교 → ok / ambiguous / partial / empty
  selection.py  선택지 서명 토큰 발급·검증 + 선택 반영 (서버 세션 없음)
  viewset.py    build_viewset(질문 | QueryAnalysis | view_bundle) → 단위별 View + 충돌 + records / pending
"""
