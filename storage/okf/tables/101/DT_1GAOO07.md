---
type: Stat Table
title: 행정구역/가구의 크기/핵수별 총조사가구(일반가구)
description: 인구총조사 · Y 2000 · 분류 행정구역별, 가구의 크기별 · 항목 9개 (가구, 인구, 남자 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO07
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GAOO07
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
    name: 가구의 크기별
    kind: other
    n_codes: 12
    total_code: '00'
    codes:
    - {code: '00', name: 총계, total: true}
    - {code: '20', name: 1인 가구}
    - {code: '21', name: 2인}
    - {code: '22', name: 3인}
    - {code: '23', name: 4인}
    - {code: '24', name: 5인}
    - {code: '25', name: 6인}
    - {code: '28', name: 7인}
    - {code: '29', name: 8인}
    - {code: '30', name: 9인}
    - {code: '31', name: 10인}
    - {code: '32', name: 11인이상 가구}
  items:
  - {id: T10, name: 가구, unit: 가구}
  - {id: T20, name: 인구, unit: 명}
  - {id: T21, name: 남자, unit: 명}
  - {id: T22, name: 여자, unit: 명}
  - {id: T30, name: 핵수, unit: 가구}
  - {id: T31, name: 핵수 0, unit: 가구}
  - {id: T32, name: 핵수 1, unit: 가구}
  - {id: T33, name: 핵수 2, unit: 가구}
  - {id: T34, name: 핵수 3개이상, unit: 가구}
---
# 행정구역/가구의 크기/핵수별 총조사가구(일반가구)

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO07

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-ac449e00.md) 예: 전국, 동부, 읍부, 면부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 가구의 크기별 | other | 12 | 00 | 00 총계, 20 1인 가구, 21 2인, 22 3인, 23 4인, 24 5인, 25 6인, 28 7인, 29 8인, 30 9인, 31 10인, 32 11인이상 가구 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 가구 | 가구 |  |  |
| T20 | 인구 | 명 |  |  |
| T21 | 남자 | 명 |  |  |
| T22 | 여자 | 명 |  |  |
| T30 | 핵수 | 가구 |  |  |
| T31 | 핵수 0 | 가구 |  |  |
| T32 | 핵수 1 | 가구 |  |  |
| T33 | 핵수 2 | 가구 |  |  |
| T34 | 핵수 3개이상 | 가구 |  |  |

# 주석

- 핵이란 가족을 구성하는 최소단위임

# 메모

<!-- human:start -->
<!-- human:end -->
