---
type: Stat Table
title: 시도/연건평/대지면적별 단독주택
description: 주택총조사 · Y 1995 · 분류 시도별, 연건평별 · 항목 14개 (총계, 10평미만, 10-14 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JU950C
tags: [주택총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:11+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1JU950C
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
  - {id: T11, name: 10평미만, unit: 호}
  - {id: T12, name: 10-14, unit: 호}
  - {id: T13, name: 15-19, unit: 호}
  - {id: T14, name: 20-29, unit: 호}
  - {id: T15, name: 30-39, unit: 호}
  - {id: T16, name: 40-49, unit: 호}
  - {id: T17, name: 50-69, unit: 호}
  - {id: T18, name: 70-99, unit: 호}
  - {id: T19, name: 100-149, unit: 호}
  - {id: T20, name: 150-199, unit: 호}
  - {id: T21, name: 200-249, unit: 호}
  - {id: T22, name: 250-299, unit: 호}
  - {id: T23, name: 300이상, unit: 호}
---
# 시도/연건평/대지면적별 단독주택

- 조사: 주택총조사
- 수록 기간: Y 1995
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JU950C

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 시도별 | geo | 55 | 00 | [55개 — 분류 파일](/classifications/geo-8bbcd2bc.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 부산광역시, 읍부, 면부 |
| 2 | 연건평별 | other | 10 | 00 | 00 총계, 06 7평미만, 07 7-9평, 09 9-14평, 14 14-19평, 19 19-29평, 29 29-39평, 39 39-49평, 49 49-69평, 55 69평이상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 총계 | 호 |  |  |
| T11 | 10평미만 | 호 |  |  |
| T12 | 10-14 | 호 |  |  |
| T13 | 15-19 | 호 |  |  |
| T14 | 20-29 | 호 |  |  |
| T15 | 30-39 | 호 |  |  |
| T16 | 40-49 | 호 |  |  |
| T17 | 50-69 | 호 |  |  |
| T18 | 70-99 | 호 |  |  |
| T19 | 100-149 | 호 |  |  |
| T20 | 150-199 | 호 |  |  |
| T21 | 200-249 | 호 |  |  |
| T22 | 250-299 | 호 |  |  |
| T23 | 300이상 | 호 |  |  |

# 주석

- 미거주 주택(빈집) 제외.

# 메모

<!-- human:start -->
<!-- human:end -->
