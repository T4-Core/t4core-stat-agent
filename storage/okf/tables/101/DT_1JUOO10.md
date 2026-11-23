---
type: Stat Table
title: 행정구역/주택의 종류별 미거주 주택(빈집)
description: 주택총조사 · Y 2000 · 분류 행정구역별 · 항목 6개 (계, 단독, 아파트 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JUOO10
tags: [주택총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:11+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1JUOO10
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
  items:
  - {id: T10, name: 계, unit: 호, total: true}
  - {id: T11, name: 단독, unit: 호}
  - {id: T12, name: 아파트, unit: 호}
  - {id: T13, name: 연립, unit: 호}
  - {id: T14, name: 다세대, unit: 호}
  - {id: T15, name: 영업용 건물내 주택, unit: 호}
---
# 행정구역/주택의 종류별 미거주 주택(빈집)

- 조사: 주택총조사
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JUOO10

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-b97f7033.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 종로구, 중구, 용산구 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 계 | 호 |  |  |
| T11 | 단독 | 호 |  |  |
| T12 | 아파트 | 호 |  |  |
| T13 | 연립 | 호 |  |  |
| T14 | 다세대 | 호 |  |  |
| T15 | 영업용 건물내 주택 | 호 |  |  |

# 메모

<!-- human:start -->
<!-- human:end -->
