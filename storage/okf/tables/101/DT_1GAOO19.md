---
type: Stat Table
title: 행정구역/세대구성/거처의 종류별 총조사가구(일반가구)
description: 인구총조사 · Y 2000 · 분류 행정구역별, 세대구성별 · 항목 12개 (계, 주택, 단독 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO19
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GAOO19
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
  - {id: T10, name: 계, unit: 가구, total: true}
  - {id: T20, name: 주택, unit: 가구}
  - {id: T21, name: 단독, unit: 가구}
  - {id: T22, name: 아파트, unit: 가구}
  - {id: T23, name: 연립, unit: 가구}
  - {id: T24, name: 다세대, unit: 가구}
  - {id: T25, name: 영업용 건물내 주택, unit: 가구}
  - {id: T30, name: 주택이외의 거처, unit: 가구}
  - {id: T31, name: 오피스텔, unit: 가구}
  - {id: T32, name: 호텔·여관 등, unit: 가구}
  - {id: T33, name: 기숙사회시설, unit: 가구}
  - {id: T34, name: 기타, unit: 가구}
---
# 행정구역/세대구성/거처의 종류별 총조사가구(일반가구)

- 조사: 인구총조사
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO19

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-aace8242.md) 예: 전국, 동부, 읍부, 면부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 세대구성별 | sex | 24 | 00 | 00 총계, 10 1세대가구, 11 부부, 12 부부+형제자매, 13 부부+기타 친인척, 14 가구주+형제자매, 15 가구주+기타 친인척, 19 기타 1세대 가구, 20 2세대가구, 21 부부+자녀, 22 편부+자녀, 23 편모+자녀, 24 부부+양친, 25 부부+편부모, 26 부부+자녀+부부의형제자매, 27 조부모+손자녀, 29 기타 2세대 가구, 30 3세대가구, 31 부부+자녀+양친, 32 부부+자녀+편부모, 39 기타 3세대 가구, 40 4세대이상가구, 50 1인가구, 60 비친족가구 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 계 | 가구 |  |  |
| T20 | 주택 | 가구 |  |  |
| T21 | 단독 | 가구 |  |  |
| T22 | 아파트 | 가구 |  |  |
| T23 | 연립 | 가구 |  |  |
| T24 | 다세대 | 가구 |  |  |
| T25 | 영업용 건물내 주택 | 가구 |  |  |
| T30 | 주택이외의 거처 | 가구 |  |  |
| T31 | 오피스텔 | 가구 |  |  |
| T32 | 호텔·여관 등 | 가구 |  |  |
| T33 | 기숙사회시설 | 가구 |  |  |
| T34 | 기타 | 가구 |  |  |

# 메모

<!-- human:start -->
<!-- human:end -->
