---
type: Stat Table
title: 행정구역/거처의 종류별 거처수,가구수,핵수,가구원
description: 주택총조사 · Y 2000 · 분류 행정구역별, 거처종류별 · 항목 7개 (거처수, 총가구수, 일반가구수 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JUOO01
tags: [주택총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:11+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1JUOO01
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
    name: 거처종류별
    kind: other
    n_codes: 12
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '10', name: 주택}
    - {code: '11', name: 단독주택}
    - {code: '12', name: 아파트}
    - {code: '14', name: 연립주택}
    - {code: '15', name: 다세대주택}
    - {code: '16', name: 영업용 건물내 주택}
    - {code: '20', name: 주택이외의 거처}
    - {code: '21', name: 오피스텔}
    - {code: '22', name: 호텔여관등 숙박업소}
    - {code: '23', name: 기숙사및특수사회시설}
    - {code: '29', name: 기타}
  items:
  - {id: T1, name: 거처수, unit: 개}
  - {id: T2, name: 총가구수, unit: 가구}
  - {id: T3, name: 일반가구수, unit: 가구}
  - {id: T4, name: 핵수, unit: 개}
  - {id: T5, name: 가구원수, unit: 명}
  - {id: T6, name: 집단가구수, unit: 가구}
  - {id: T7, name: 집단가구원수, unit: 명}
---
# 행정구역/거처의 종류별 거처수,가구수,핵수,가구원

- 조사: 주택총조사
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JUOO01

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-b97f7033.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 거처종류별 | other | 12 | 00 | 00 계, 10 주택, 11 단독주택, 12 아파트, 14 연립주택, 15 다세대주택, 16 영업용 건물내 주택, 20 주택이외의 거처, 21 오피스텔, 22 호텔여관등 숙박업소, 23 기숙사및특수사회시설, 29 기타 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T1 | 거처수 | 개 |  |  |
| T2 | 총가구수 | 가구 |  |  |
| T3 | 일반가구수 | 가구 |  |  |
| T4 | 핵수 | 개 |  |  |
| T5 | 가구원수 | 명 |  |  |
| T6 | 집단가구수 | 가구 |  |  |
| T7 | 집단가구원수 | 명 |  |  |

# 주석

- 특별조사구, 외국인 및 미거주 주택(빈집) 제외

# 메모

<!-- human:start -->
<!-- human:end -->
