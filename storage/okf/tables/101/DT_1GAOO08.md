---
type: Stat Table
title: 행정구역/가구주의 성/연령/거처의 종류별 총조사가구(일반가구)
description: 인구총조사 · Y 2000 · 분류 행정구역별, 가구주의 성별, 가구주의 연령별 · 항목 12개 (계, 주택, 단독 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO08
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GAOO08
  survey: 인구총조사
  periods:
    Y: ['2000']
  dims:
  - level: 1
    name: 행정구역별
    kind: geo
    n_codes: 314
    total_code: '00'
    classification: /classifications/geo-ac449e00.md
    examples: [전국, 동부, 읍부, 면부, 서울특별시, 종로구, 중구, 용산구]
  - level: 2
    name: 가구주의 성별
    kind: sex
    n_codes: 3
    total_code: '0'
    codes:
    - {code: '0', name: 계, total: true}
    - {code: '1', name: 남자}
    - {code: '2', name: 여자}
  - level: 3
    name: 가구주의 연령별
    kind: age
    n_codes: 18
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '16', name: 15세미만}
    - {code: '20', name: 15 - 19세}
    - {code: '25', name: 20 - 24세}
    - {code: '30', name: 25 - 29세}
    - {code: '35', name: 30 - 34세}
    - {code: '40', name: 35 - 39세}
    - {code: '45', name: 40 - 44세}
    - {code: '50', name: 45 - 49세}
    - {code: '55', name: 50 - 54세}
    - {code: '60', name: 55 - 59세}
    - {code: '65', name: 60 - 64세}
    - {code: '70', name: 65 - 69세}
    - {code: '75', name: 70 - 74세}
    - {code: '80', name: 75 - 79세}
    - {code: '85', name: 80 - 84세}
    - {code: '87', name: 85세 이상}
    - {code: '95', name: 연령미상}
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
# 행정구역/가구주의 성/연령/거처의 종류별 총조사가구(일반가구)

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO08

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-ac449e00.md) 예: 전국, 동부, 읍부, 면부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 가구주의 성별 | sex | 3 | 0 | 0 계, 1 남자, 2 여자 |
| 3 | 가구주의 연령별 | age | 18 | 00 | 00 계, 16 15세미만, 20 15 - 19세, 25 20 - 24세, 30 25 - 29세, 35 30 - 34세, 40 35 - 39세, 45 40 - 44세, 50 45 - 49세, 55 50 - 54세, 60 55 - 59세, 65 60 - 64세, 70 65 - 69세, 75 70 - 74세, 80 75 - 79세, 85 80 - 84세, 87 85세 이상, 95 연령미상 |

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
