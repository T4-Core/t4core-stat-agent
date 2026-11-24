---
type: Stat Table
title: 행정구역/거처의 종류/점유형태/사용방수(용도)별 총조사가구(일반가구)
description: 인구총조사 · Y 2000 · 분류 행정구역별, 거처종류별, 점유형태별 · 항목 12개 (계, 침실수 1, 침실수 2 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO18
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GAOO18
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
    name: 거처종류별
    kind: other
    n_codes: 8
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
  - level: 3
    name: 점유형태별
    kind: other
    n_codes: 8
    total_code: '0'
    codes:
    - {code: '0', name: 계, total: true}
    - {code: '1', name: 자가}
    - {code: '2', name: 전세}
    - {code: '3', name: 월세}
    - {code: '4', name: 무보증월세}
    - {code: '5', name: 사글세}
    - {code: '6', name: 무상}
    - {code: '7', name: 미상}
  items:
  - {id: T10, name: 계, unit: 가구, total: true}
  - {id: T21, name: 침실수 1, unit: 가구}
  - {id: T22, name: 침실수 2, unit: 가구}
  - {id: T23, name: 침실수 3, unit: 가구}
  - {id: T24, name: 침실수 4, unit: 가구}
  - {id: T25, name: 침실수 5 이상, unit: 가구}
  - {id: T31, name: 거실수 0, unit: 가구}
  - {id: T32, name: 거실수 1, unit: 가구}
  - {id: T33, name: 거실수 2 이상, unit: 가구}
  - {id: T41, name: 식당수 0, unit: 가구}
  - {id: T42, name: 식당수 1, unit: 가구}
  - {id: T43, name: 식당수 2 이상, unit: 가구}
---
# 행정구역/거처의 종류/점유형태/사용방수(용도)별 총조사가구(일반가구)

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO18

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-ac449e00.md) 예: 전국, 동부, 읍부, 면부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 거처종류별 | other | 8 | 00 | 00 계, 10 주택, 11 단독주택, 12 아파트, 14 연립주택, 15 다세대주택, 16 영업용 건물내 주택, 20 주택이외의 거처 |
| 3 | 점유형태별 | other | 8 | 0 | 0 계, 1 자가, 2 전세, 3 월세, 4 무보증월세, 5 사글세, 6 무상, 7 미상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 계 | 가구 |  |  |
| T21 | 침실수 1 | 가구 |  |  |
| T22 | 침실수 2 | 가구 |  |  |
| T23 | 침실수 3 | 가구 |  |  |
| T24 | 침실수 4 | 가구 |  |  |
| T25 | 침실수 5 이상 | 가구 |  |  |
| T31 | 거실수 0 | 가구 |  |  |
| T32 | 거실수 1 | 가구 |  |  |
| T33 | 거실수 2 이상 | 가구 |  |  |
| T41 | 식당수 0 | 가구 |  |  |
| T42 | 식당수 1 | 가구 |  |  |
| T43 | 식당수 2 이상 | 가구 |  |  |

# 메모

<!-- human:start -->
<!-- human:end -->
