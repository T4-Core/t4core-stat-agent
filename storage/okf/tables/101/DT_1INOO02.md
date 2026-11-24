---
type: Stat Table
title: 행정구역/연령/성/교육정도별 총조사 인구(6세이상)
description: 인구총조사 · Y 2000 · 분류 행정구역별, 연령별, 교육정도별 · 항목 3개 (인구, 남자, 여자)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO02
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:10+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1INOO02
  survey: 인구총조사
  periods:
    Y: ['2000']
  dims:
  - level: 1
    name: 행정구역별
    kind: geo
    n_codes: 314
    total_code: '00'
    classification: /classifications/geo-b97f7033.md
    examples: [전국, 읍부, 면부, 동부, 서울특별시, 종로구, 중구, 용산구]
  - level: 2
    name: 연령별
    kind: age
    n_codes: 70
    total_code: '00'
    classification: /classifications/age-130c17e5.md
    examples: [계, 6 - 9세, 6세, 7세, 8세, 9세, 10 - 14세, 10세]
  - level: 3
    name: 교육정도별
    kind: other
    n_codes: 32
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '10', name: 재학}
    - {code: '103', name: 초등학교, parent: '10'}
    - {code: '104', name: 중학교, parent: '10'}
    - {code: '105', name: 고등학교, parent: '10'}
    - {code: '106', name: 대학, parent: '10'}
    - {code: '107', name: 대학교, parent: '10'}
    - {code: '108', name: 대학원석사, parent: '10'}
    - {code: '109', name: 대학원박사, parent: '10'}
    - {code: '20', name: 졸업}
    - {code: '203', name: 초등학교, parent: '20'}
    - {code: '204', name: 중학교, parent: '20'}
    - {code: '205', name: 고등학교, parent: '20'}
    - {code: '206', name: 대학, parent: '20'}
    - {code: '207', name: 대학교, parent: '20'}
    - {code: '208', name: 대학원석사, parent: '20'}
    - {code: '209', name: 대학원박사, parent: '20'}
    - {code: '30', name: 중퇴}
    - {code: '303', name: 초등학교, parent: '30'}
    - {code: '304', name: 중학교, parent: '30'}
    - {code: '305', name: 고등학교, parent: '30'}
    - {code: '306', name: 대학, parent: '30'}
    - {code: '307', name: 대학교, parent: '30'}
    - {code: '308', name: 대학원석사, parent: '30'}
    - {code: '309', name: 대학원박사, parent: '30'}
    - {code: '40', name: 수료}
    - {code: '406', name: 대학, parent: '40'}
    - {code: '407', name: 대학교, parent: '40'}
    - {code: '408', name: 대학원석사, parent: '40'}
    - {code: '409', name: 대학원박사, parent: '40'}
    - {code: '50', name: 안다녔음}
    - {code: '99', name: 미상}
  items:
  - {id: T1, name: 인구, unit: 명}
  - {id: T2, name: 남자, unit: 명}
  - {id: T3, name: 여자, unit: 명}
---
# 행정구역/연령/성/교육정도별 총조사 인구(6세이상)

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO02

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-b97f7033.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 연령별 | age | 70 | 00 | [70개 — 분류 파일](/classifications/age-130c17e5.md) 예: 계, 6 - 9세, 6세, 7세, 8세, 9세, 10 - 14세, 10세 |
| 3 | 교육정도별 | other | 32 | 00 | 00 계, 10 재학, 103 초등학교, 104 중학교, 105 고등학교, 106 대학, 107 대학교, 108 대학원석사, 109 대학원박사, 20 졸업, 203 초등학교, 204 중학교, 205 고등학교, 206 대학, 207 대학교, 208 대학원석사, 209 대학원박사, 30 중퇴, 303 초등학교, 304 중학교, 305 고등학교, 306 대학, 307 대학교, 308 대학원석사, 309 대학원박사, 40 수료, 406 대학, 407 대학교, 408 대학원석사, 409 대학원박사, 50 안다녔음, 99 미상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T1 | 인구 | 명 |  |  |
| T2 | 남자 | 명 |  |  |
| T3 | 여자 | 명 |  |  |

# 주석

- 외국인 제외
- 휴학 포함

# 메모

<!-- human:start -->
<!-- human:end -->
