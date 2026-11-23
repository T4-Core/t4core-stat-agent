---
type: Stat Table
title: 행정구역/연건평/편익시설수별 단독주택
description: 주택총조사 · Y 1995 · 분류 행정구역별, 연건평별 · 항목 17개 (단독주택수, 거주가구수, 부엌시설 1개 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JU950B
tags: [주택총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:11+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1JU950B
  survey: 주택총조사
  periods:
    Y: ['1995']
  dims:
  - level: 1
    name: 행정구역별
    kind: geo
    n_codes: 311
    total_code: '00'
    classification: /classifications/geo-ac1f7839.md
    examples: [전국, 읍부, 면부, 동부, 서울특별시, 종로구, 중구, 용산구]
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
  - {id: T10, name: 단독주택수, unit: 호}
  - {id: T20, name: 거주가구수, unit: 호}
  - {id: T31, name: 부엌시설 1개, unit: 호}
  - {id: T32, name: 2개, unit: 호}
  - {id: T33, name: 3개, unit: 호}
  - {id: T34, name: 4개, unit: 호}
  - {id: T35, name: 5개이상, unit: 호}
  - {id: T41, name: 화장실시설1개, unit: 호}
  - {id: T42, name: 2개, unit: 호}
  - {id: T43, name: 3개, unit: 호}
  - {id: T44, name: 4개, unit: 호}
  - {id: T45, name: 5개이상, unit: 호}
  - {id: T51, name: 출입구시설 1개, unit: 호}
  - {id: T52, name: 2개, unit: 호}
  - {id: T53, name: 3개, unit: 호}
  - {id: T54, name: 4개, unit: 호}
  - {id: T55, name: 5개이상, unit: 호}
---
# 행정구역/연건평/편익시설수별 단독주택

- 조사: 주택총조사
- 수록 기간: Y 1995
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JU950B

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 311 | 00 | [311개 — 분류 파일](/classifications/geo-ac1f7839.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 연건평별 | other | 10 | 00 | 00 총계, 06 7평미만, 07 7-9평, 09 9-14평, 14 14-19평, 19 19-29평, 29 29-39평, 39 39-49평, 49 49-69평, 55 69평이상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 단독주택수 | 호 |  |  |
| T20 | 거주가구수 | 호 |  |  |
| T31 | 부엌시설 1개 | 호 |  |  |
| T32 | 2개 | 호 |  |  |
| T33 | 3개 | 호 |  |  |
| T34 | 4개 | 호 |  |  |
| T35 | 5개이상 | 호 |  |  |
| T41 | 화장실시설1개 | 호 |  |  |
| T42 | 2개 | 호 |  |  |
| T43 | 3개 | 호 |  |  |
| T44 | 4개 | 호 |  |  |
| T45 | 5개이상 | 호 |  |  |
| T51 | 출입구시설 1개 | 호 |  |  |
| T52 | 2개 | 호 |  |  |
| T53 | 3개 | 호 |  |  |
| T54 | 4개 | 호 |  |  |
| T55 | 5개이상 | 호 |  |  |

# 주석

- 미거주 주택(빈집) 제외.

# 메모

<!-- human:start -->
<!-- human:end -->
