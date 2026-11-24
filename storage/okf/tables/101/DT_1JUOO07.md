---
type: Stat Table
title: 행정구역/연건평/단독주택의 종류/대지면적별 단독주택(총조사)
description: 주택총조사 · Y 2000 · 분류 행정구역별, 단독주택의 종류별, 연건평별 · 항목 14개 (총계, 10평미만, 10-14 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JUOO07
tags: [주택총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:11+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1JUOO07
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
    name: 단독주택의 종류별
    kind: other
    n_codes: 3
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '10', name: 일반단독주택}
    - {code: '20', name: 다가구 주택}
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
  - {id: T11, name: 10평미만, unit: 호}
  - {id: T12, name: 10-14, unit: 호}
  - {id: T13, name: 14-19, unit: 호}
  - {id: T14, name: 19-29, unit: 호}
  - {id: T15, name: 29-39, unit: 호}
  - {id: T16, name: 39-49, unit: 호}
  - {id: T17, name: 49-69, unit: 호}
  - {id: T18, name: 69-99, unit: 호}
  - {id: T19, name: 99-149, unit: 호}
  - {id: T20, name: 149-199, unit: 호}
  - {id: T21, name: 199-249, unit: 호}
  - {id: T22, name: 249-299, unit: 호}
  - {id: T23, name: 299이상, unit: 호}
---
# 행정구역/연건평/단독주택의 종류/대지면적별 단독주택(총조사)

- 조사: 주택총조사 · 작성: 통계청 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JUOO07

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-b97f7033.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 단독주택의 종류별 | other | 3 | 00 | 00 계, 10 일반단독주택, 20 다가구 주택 |
| 3 | 연건평별 | other | 10 | 00 | 00 총계, 06 7평미만, 07 7-9평, 09 9-14평, 14 14-19평, 19 19-29평, 29 29-39평, 39 39-49평, 49 49-69평, 55 69평이상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 총계 | 호 |  |  |
| T11 | 10평미만 | 호 |  |  |
| T12 | 10-14 | 호 |  |  |
| T13 | 14-19 | 호 |  |  |
| T14 | 19-29 | 호 |  |  |
| T15 | 29-39 | 호 |  |  |
| T16 | 39-49 | 호 |  |  |
| T17 | 49-69 | 호 |  |  |
| T18 | 69-99 | 호 |  |  |
| T19 | 99-149 | 호 |  |  |
| T20 | 149-199 | 호 |  |  |
| T21 | 199-249 | 호 |  |  |
| T22 | 249-299 | 호 |  |  |
| T23 | 299이상 | 호 |  |  |

# 메모

<!-- human:start -->
<!-- human:end -->
