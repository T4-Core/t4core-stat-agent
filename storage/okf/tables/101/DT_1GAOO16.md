---
type: Stat Table
title: 행정구역/가구원수/거실수,식당수,침실수별 총조사가구(일반가구)
description: 인구총조사 · Y 2000 · 분류 행정구역별, 가구원수별 · 항목 12개 (계, 침실수 1, 침실수 2 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO16
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GAOO16
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
    name: 가구원수별
    kind: other
    n_codes: 8
    total_code: '00'
    codes:
    - {code: '00', name: 총계, total: true}
    - {code: '01', name: 1인}
    - {code: '02', name: 2인}
    - {code: '03', name: 3인}
    - {code: '04', name: 4인}
    - {code: '05', name: 5인}
    - {code: '06', name: 6인}
    - {code: '07', name: 7인이상}
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
# 행정구역/가구원수/거실수,식당수,침실수별 총조사가구(일반가구)

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO16

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-ac449e00.md) 예: 전국, 동부, 읍부, 면부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 가구원수별 | other | 8 | 00 | 00 총계, 01 1인, 02 2인, 03 3인, 04 4인, 05 5인, 06 6인, 07 7인이상 |

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
