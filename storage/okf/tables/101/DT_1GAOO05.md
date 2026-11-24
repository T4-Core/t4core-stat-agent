---
type: Stat Table
title: 행정구역/세대구성/가구주의 교육정도별 총조사가구(일반가구)
description: 인구총조사 · Y 2000 · 분류 행정구역별, 세대구성별 · 항목 10개 (계, 초등, 중학 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO05
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GAOO05
  survey: 인구총조사
  periods:
    Y: ['2000']
  dims:
  - level: 1
    name: 행정구역별
    kind: geo
    n_codes: 314
    total_code: '00'
    classification: /classifications/geo-aace8242.md
    examples: [전국, 동부, 읍부, 면부, 서울특별시, 종로구, 중구, 용산구]
  - level: 2
    name: 세대구성별
    kind: sex
    n_codes: 24
    total_code: '00'
    codes:
    - {code: '00', name: 총계, total: true}
    - {code: '10', name: 1세대가구}
    - {code: '11', name: 부부}
    - {code: '12', name: 부부+형제자매}
    - {code: '13', name: 부부+기타 친인척}
    - {code: '14', name: 가구주+형제자매}
    - {code: '15', name: 가구주+기타 친인척}
    - {code: '19', name: 기타 1세대 가구}
    - {code: '20', name: 2세대가구}
    - {code: '21', name: 부부+자녀}
    - {code: '22', name: 편부+자녀}
    - {code: '23', name: 편모+자녀}
    - {code: '24', name: 부부+양친}
    - {code: '25', name: 부부+편부모}
    - {code: '26', name: 부부+자녀+부부의형제자매}
    - {code: '27', name: 조부모+손자녀}
    - {code: '29', name: 기타 2세대 가구}
    - {code: '30', name: 3세대가구}
    - {code: '31', name: 부부+자녀+양친}
    - {code: '32', name: 부부+자녀+편부모}
    - {code: '39', name: 기타 3세대 가구}
    - {code: '40', name: 4세대이상가구}
    - {code: '50', name: 1인가구}
    - {code: '60', name: 비친족가구}
  items:
  - {id: T01, name: 계, unit: 가구, total: true}
  - {id: T02, name: 초등, unit: 가구}
  - {id: T03, name: 중학, unit: 가구}
  - {id: T04, name: 고등, unit: 가구}
  - {id: T05, name: 대학, unit: 가구}
  - {id: T06, name: 대학교, unit: 가구}
  - {id: T07, name: 대학원 석사, unit: 가구}
  - {id: T08, name: 대학원 박사, unit: 가구}
  - {id: T09, name: 안다녔음, unit: 가구}
  - {id: T10, name: 미상, unit: 가구}
---
# 행정구역/세대구성/가구주의 교육정도별 총조사가구(일반가구)

- 조사: 인구총조사
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO05

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-aace8242.md) 예: 전국, 동부, 읍부, 면부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 세대구성별 | sex | 24 | 00 | 00 총계, 10 1세대가구, 11 부부, 12 부부+형제자매, 13 부부+기타 친인척, 14 가구주+형제자매, 15 가구주+기타 친인척, 19 기타 1세대 가구, 20 2세대가구, 21 부부+자녀, 22 편부+자녀, 23 편모+자녀, 24 부부+양친, 25 부부+편부모, 26 부부+자녀+부부의형제자매, 27 조부모+손자녀, 29 기타 2세대 가구, 30 3세대가구, 31 부부+자녀+양친, 32 부부+자녀+편부모, 39 기타 3세대 가구, 40 4세대이상가구, 50 1인가구, 60 비친족가구 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T01 | 계 | 가구 |  |  |
| T02 | 초등 | 가구 |  |  |
| T03 | 중학 | 가구 |  |  |
| T04 | 고등 | 가구 |  |  |
| T05 | 대학 | 가구 |  |  |
| T06 | 대학교 | 가구 |  |  |
| T07 | 대학원 석사 | 가구 |  |  |
| T08 | 대학원 박사 | 가구 |  |  |
| T09 | 안다녔음 | 가구 |  |  |
| T10 | 미상 | 가구 |  |  |

# 주석

- 특별조사구, 집단가구원, 집단시설가구원 및 외국인 가구원 제외.

# 메모

<!-- human:start -->
<!-- human:end -->
