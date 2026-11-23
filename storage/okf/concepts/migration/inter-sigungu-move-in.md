---
type: Stat Concept
title: 시군구간전입
description: 국내인구이동통계 통계표의 항목으로, 특정 연령대에서 한 시군구에서 다른 시군구로 이동한 사람의 수를 나타냅니다.
tags: []
status: deprecated
generated: {by: 'process:okf-drafts/1', at: '2026-11-23T14:10:06+09:00'}
x-t4-concept:
  aliases:
  - text: 이사 온
    by: draft:compare
    at: '2026-11-23T14:10:06+09:00'
    records: [SG-1fb6a31269a1]
    evidence: [colloquial → 전입, '⚠ colloquial 은 ''인구이동, 이동자수'' 로도 바꿈 — 뜻이 넓거나 다름']
    example: 2019년 울산에서 다른 구나 군으로 이사 온 사람들이 전체 주민들 중에서 몇 퍼센트를 차지할까? 그 비율이 가장 높은 곳은 어디일까?
    review: {by: 'process:okf-assist-hcx/1', at: '2026-11-23T14:24:15+09:00', verdict: same, reason: 질문은 특정 시군구 간 전입에 대해 묻고 있습니다.}
    verified: {by: 'human:JSH', at: '2026-11-23T17:22:38+09:00'}
  - text: 옮긴
    by: draft:compare
    at: '2026-11-23T14:10:06+09:00'
    records: [SG-2bcc97bd17de]
    evidence: [⚠ colloquial 은 '전출' 로도 바꿈 — 뜻이 넓거나 다름]
    example: 2024년에 다른 시도에서 온 사람이 5,100명 이상인 경남의 시군구 중, 그 지역에서 다른 시군구로 옮긴 사람 수가 가장 많은 곳은 어디일까요?
    review: {by: 'process:okf-assist-hcx/1', at: '2026-11-23T14:24:15+09:00', verdict: same, reason: 질문은 특정 시군구 간 전입 및 전출에 대한 정보를 요구하고 있습니다.}
  not:
  - {text: 총전입, why: '총전입은 모든 전입의 합계를 의미하며, 특정 시군구 간의 전입과는 다릅니다.', by: 'process:okf-assist-hcx/1'}
  - {text: 총전출, why: '총전출은 모든 전출의 합계를 의미하며, 특정 시군구 간의 전입과는 다릅니다.', by: 'process:okf-assist-hcx/1'}
  - {text: 순이동, why: '순이동은 전입과 전출의 차이를 의미하며, 특정 시군구 간의 전입과는 다릅니다.', by: 'process:okf-assist-hcx/1'}
  binds:
  - {table: /tables/101/DT_1B26B08.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B01.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B02.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B03.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B04.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B05.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B06.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B07.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B09.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B10.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B11.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B12.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B13.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B14.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B15.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B16.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B17.md, item: T31, name: 시군구간전입}
  - {table: /tables/101/DT_1B26B18.md, item: T31, name: 시군구간전입}
  calc: []
x-t4-draft: {definition: hcx, text: '국내인구이동통계 통계표의 항목으로, 특정 연령대에서 한 시군구에서 다른 시군구로 이동한 사람의 수를 나타냅니다.', by: 'process:okf-assist-hcx/1', at: '2026-11-23T14:24:15+09:00'}
verified:
- {by: 'human:JSH', at: '2026-11-23T17:22:38+09:00'}
---
# 정의

국내인구이동통계 통계표의 항목으로, 특정 연령대에서 한 시군구에서 다른 시군구로 이동한 사람의 수를 나타냅니다.

근거(표 정보): 국내인구이동통계 통계표의 항목 '시군구간전입' (단위 명). 같은 이름이 있는 표 18개 (예: 울산광역시 시군구 각세별 이동자수 · 시도/각세별 이동자수 외 16개). 나누는 분류: 각세.

# 헷갈리는 말

- 총전입 — 총전입은 모든 전입의 합계를 의미하며, 특정 시군구 간의 전입과는 다릅니다.
- 총전출 — 총전출은 모든 전출의 합계를 의미하며, 특정 시군구 간의 전입과는 다릅니다.
- 순이동 — 순이동은 전입과 전출의 차이를 의미하며, 특정 시군구 간의 전입과는 다릅니다.

# 표

- [시군구간전입](/tables/101/DT_1B26B08.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B01.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B02.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B03.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B04.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B05.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B06.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B07.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B09.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B10.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B11.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B12.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B13.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B14.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B15.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B16.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B17.md) — 항목 T31
- [시군구간전입](/tables/101/DT_1B26B18.md) — 항목 T31
