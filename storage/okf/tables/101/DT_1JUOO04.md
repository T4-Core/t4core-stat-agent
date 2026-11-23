---
type: Stat Table
title: 행정구역/주택의 종류/연건평/총방수별 총조사주택
description: 주택총조사 · Y 2000 · 분류 행정구역별, 주택의종류별, 연건평별 · 항목 9개 (계, 1개, 2개 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JUOO04
tags: [주택총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:11+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1JUOO04
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
    name: 주택의종류별
    kind: other
    n_codes: 6
    total_code: '00'
    codes:
    - {code: '00', name: 총계, total: true}
    - {code: '11', name: 단독주택}
    - {code: '12', name: 아파트}
    - {code: '14', name: 연립주택}
    - {code: '15', name: 다세대주택}
    - {code: '16', name: 영업용 건물내 주택}
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
  - {id: T10, name: 계, unit: 호, total: true}
  - {id: T11, name: 1개, unit: 호}
  - {id: T12, name: 2개, unit: 호}
  - {id: T13, name: 3개, unit: 호}
  - {id: T14, name: 4개, unit: 호}
  - {id: T15, name: 5개, unit: 호}
  - {id: T16, name: 6개, unit: 호}
  - {id: T17, name: 7개, unit: 호}
  - {id: T18, name: 8개이상, unit: 호}
---
# 행정구역/주택의 종류/연건평/총방수별 총조사주택

- 조사: 주택총조사 · 작성: 통계청 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JUOO04

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-b97f7033.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 주택의종류별 | other | 6 | 00 | 00 총계, 11 단독주택, 12 아파트, 14 연립주택, 15 다세대주택, 16 영업용 건물내 주택 |
| 3 | 연건평별 | other | 10 | 00 | 00 총계, 06 7평미만, 07 7-9평, 09 9-14평, 14 14-19평, 19 19-29평, 29 29-39평, 39 39-49평, 49 49-69평, 55 69평이상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 계 | 호 |  |  |
| T11 | 1개 | 호 |  |  |
| T12 | 2개 | 호 |  |  |
| T13 | 3개 | 호 |  |  |
| T14 | 4개 | 호 |  |  |
| T15 | 5개 | 호 |  |  |
| T16 | 6개 | 호 |  |  |
| T17 | 7개 | 호 |  |  |
| T18 | 8개이상 | 호 |  |  |

# 메모

<!-- human:start -->
<!-- human:end -->
