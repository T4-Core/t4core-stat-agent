---
type: Stat Table
title: 행정구역/주택의 종류/점유형태별 총조사주택
description: 주택총조사 · Y 2000 · 분류 행정구역별, 주택의종류별 · 항목 8개 (계, 자가, 전세 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JUOO02
tags: [주택총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:11+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1JUOO02
  survey: 주택총조사
  periods:
    Y: ['2000']
  dims:
  - level: 1
    name: 행정구역별
    kind: geo
    n_codes: 314
    total_code: '00'
    classification: /classifications/geo-26aa1a1a.md
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
  items:
  - {id: T1, name: 계, unit: 호, total: true}
  - {id: T2, name: 자가, unit: 호}
  - {id: T3, name: 전세, unit: 호}
  - {id: T4, name: 보증부월세, unit: 호}
  - {id: T5, name: 무보증월세, unit: 호}
  - {id: T6, name: 사글세, unit: 호}
  - {id: T7, name: 무상, unit: 호}
  - {id: T9, name: 미상, unit: 호}
---
# 행정구역/주택의 종류/점유형태별 총조사주택

- 조사: 주택총조사 · 작성: 통계청 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JUOO02

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-26aa1a1a.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 주택의종류별 | other | 6 | 00 | 00 총계, 11 단독주택, 12 아파트, 14 연립주택, 15 다세대주택, 16 영업용 건물내 주택 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T1 | 계 | 호 |  |  |
| T2 | 자가 | 호 |  |  |
| T3 | 전세 | 호 |  |  |
| T4 | 보증부월세 | 호 |  |  |
| T5 | 무보증월세 | 호 |  |  |
| T6 | 사글세 | 호 |  |  |
| T7 | 무상 | 호 |  |  |
| T9 | 미상 | 호 |  |  |

# 메모

<!-- human:start -->
<!-- human:end -->
