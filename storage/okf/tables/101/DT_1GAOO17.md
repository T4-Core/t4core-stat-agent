---
type: Stat Table
title: 행정구역/점유형태/가구원수/사용방수별 총조사가구(일반가구)
description: 인구총조사 · Y 2000 · 분류 행정구역별, 점유형태별, 가구원수별 · 항목 7개 (가구 계, 사용방수 1, 사용방수 2 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO17
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GAOO17
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
  - {id: T1, name: 가구 계, unit: 가구}
  - {id: T2, name: 사용방수 1, unit: 가구}
  - {id: T3, name: 사용방수 2, unit: 가구}
  - {id: T4, name: 사용방수 3, unit: 가구}
  - {id: T5, name: 사용방수 4, unit: 가구}
  - {id: T6, name: 사용방수 5, unit: 가구}
  - {id: T7, name: 사용방수 6개이상, unit: 가구}
---
# 행정구역/점유형태/가구원수/사용방수별 총조사가구(일반가구)

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO17

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-ac449e00.md) 예: 전국, 동부, 읍부, 면부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 점유형태별 | other | 6 | 0 | 0 계, 1 자가, 2 전세, 3 월세, 6 무상, 7 미상 |
| 3 | 가구원수별 | other | 8 | 00 | 00 총계, 01 1인, 02 2인, 03 3인, 04 4인, 05 5인, 06 6인, 07 7인이상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T1 | 가구 계 | 가구 |  |  |
| T2 | 사용방수 1 | 가구 |  |  |
| T3 | 사용방수 2 | 가구 |  |  |
| T4 | 사용방수 3 | 가구 |  |  |
| T5 | 사용방수 4 | 가구 |  |  |
| T6 | 사용방수 5 | 가구 |  |  |
| T7 | 사용방수 6개이상 | 가구 |  |  |

# 메모

<!-- human:start -->
<!-- human:end -->
