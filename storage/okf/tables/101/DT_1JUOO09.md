---
type: Stat Table
title: 행정구역/점유형태/총방수/거처의 종류별 총조사주택
description: 주택총조사 · Y 2000 · 분류 행정구역별, 점유형태별, 총방수별 · 항목 8개 (계, 주택, 단독 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JUOO09
tags: [주택총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:11+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1JUOO09
  survey: 주택총조사
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
    name: 점유형태별
    kind: other
    n_codes: 6
    total_code: '0'
    codes:
    - {code: '0', name: 계, total: true}
    - {code: '1', name: 자가}
    - {code: '2', name: 전세}
    - {code: '3', name: 월세}
    - {code: '6', name: 무상}
    - {code: '7', name: 미상}
  - level: 3
    name: 총방수별
    kind: other
    n_codes: 8
    total_code: '0'
    codes:
    - {code: '0', name: 계, total: true}
    - {code: '1', name: 1개}
    - {code: '2', name: 2개}
    - {code: '3', name: 3개}
    - {code: '4', name: 4개}
    - {code: '5', name: 5개}
    - {code: '6', name: 6개}
    - {code: '7', name: 7개이상}
  items:
  - {id: T10, name: 계, unit: 호, total: true}
  - {id: T20, name: 주택, unit: 호}
  - {id: T21, name: 단독, unit: 호}
  - {id: T22, name: 아파트, unit: 호}
  - {id: T23, name: 연립, unit: 호}
  - {id: T24, name: 다세대, unit: 호}
  - {id: T25, name: 영업용 건물내 주택, unit: 호}
  - {id: T30, name: 주택이외의 거처, unit: 호}
---
# 행정구역/점유형태/총방수/거처의 종류별 총조사주택

- 조사: 주택총조사
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JUOO09

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-b97f7033.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 점유형태별 | other | 6 | 0 | 0 계, 1 자가, 2 전세, 3 월세, 6 무상, 7 미상 |
| 3 | 총방수별 | other | 8 | 0 | 0 계, 1 1개, 2 2개, 3 3개, 4 4개, 5 5개, 6 6개, 7 7개이상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 계 | 호 |  |  |
| T20 | 주택 | 호 |  |  |
| T21 | 단독 | 호 |  |  |
| T22 | 아파트 | 호 |  |  |
| T23 | 연립 | 호 |  |  |
| T24 | 다세대 | 호 |  |  |
| T25 | 영업용 건물내 주택 | 호 |  |  |
| T30 | 주택이외의 거처 | 호 |  |  |

# 주석

- 주) 주택에는 미거주 주택(빈집) 제외

# 메모

<!-- human:start -->
<!-- human:end -->
