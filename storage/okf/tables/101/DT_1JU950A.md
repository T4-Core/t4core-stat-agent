---
type: Stat Table
title: 시도/주택의종류/연건평/건축년도별 주택
description: 주택총조사 · Y 1995 · 분류 시도별, 거처의종류별, 연건평별 · 항목 12개 (총계, 1995, 1994 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JU950A
tags: [주택총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:11+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1JU950A
  survey: 주택총조사
  periods:
    Y: ['1995']
  dims:
  - level: 1
    name: 시도별
    kind: geo
    n_codes: 55
    total_code: '00'
    classification: /classifications/geo-8bbcd2bc.md
    examples: [전국, 읍부, 면부, 동부, 서울특별시, 부산광역시, 읍부, 면부]
  - level: 2
    name: 거처의종류별
    kind: other
    n_codes: 6
    total_code: '00'
    codes:
    - {code: '00', name: 총계, total: true}
    - {code: '11', name: 단독주택}
    - {code: '12', name: 아파트}
    - {code: '14', name: 연립주택}
    - {code: '15', name: 다세대주택}
    - {code: '16', name: 비주거용 건물 내 주택}
  - level: 3
    name: 연건평별
    kind: other
    n_codes: 10
    total_code: '00'
    codes:
    - {code: '00', name: 총계, total: true}
    - {code: '06', name: 7평미만}
    - {code: '07', name: 7-9평}
    - {code: 09, name: 9-14평}
    - {code: '14', name: 14-19평}
    - {code: '19', name: 19-29평}
    - {code: '29', name: 29-39평}
    - {code: '39', name: 39-49평}
    - {code: '49', name: 49-69평}
    - {code: '55', name: 69평이상}
  items:
  - {id: T10, name: 총계, unit: 호, total: true}
  - {id: T11, name: '1995', unit: 호}
  - {id: T12, name: '1994', unit: 호}
  - {id: T13, name: '1993', unit: 호}
  - {id: T14, name: '1992', unit: 호}
  - {id: T15, name: '1991', unit: 호}
  - {id: T16, name: '1990', unit: 호}
  - {id: T17, name: 1989-1980, unit: 호}
  - {id: T18, name: 1979-1970, unit: 호}
  - {id: T19, name: 1969-1960, unit: 호}
  - {id: T20, name: 1959-1950, unit: 호}
  - {id: T21, name: 1949이전, unit: 호}
---
# 시도/주택의종류/연건평/건축년도별 주택

- 조사: 주택총조사
- 수록 기간: Y 1995
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JU950A

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 시도별 | geo | 55 | 00 | [55개 — 분류 파일](/classifications/geo-8bbcd2bc.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 부산광역시, 읍부, 면부 |
| 2 | 거처의종류별 | other | 6 | 00 | 00 총계, 11 단독주택, 12 아파트, 14 연립주택, 15 다세대주택, 16 비주거용 건물 내 주택 |
| 3 | 연건평별 | other | 10 | 00 | 00 총계, 06 7평미만, 07 7-9평, 09 9-14평, 14 14-19평, 19 19-29평, 29 29-39평, 39 39-49평, 49 49-69평, 55 69평이상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 총계 | 호 |  |  |
| T11 | 1995 | 호 |  |  |
| T12 | 1994 | 호 |  |  |
| T13 | 1993 | 호 |  |  |
| T14 | 1992 | 호 |  |  |
| T15 | 1991 | 호 |  |  |
| T16 | 1990 | 호 |  |  |
| T17 | 1989-1980 | 호 |  |  |
| T18 | 1979-1970 | 호 |  |  |
| T19 | 1969-1960 | 호 |  |  |
| T20 | 1959-1950 | 호 |  |  |
| T21 | 1949이전 | 호 |  |  |

# 주석

- 미거주 주택(빈집) 제외.

# 메모

<!-- human:start -->
<!-- human:end -->
