---
type: Stat Table
title: 행정구역/가구주의 성/가구주의 연령/혼인상태별 총조사가구(일반가구)
description: 인구총조사 · Y 2000 · 분류 행정구역별, 가구주의 성별, 가구주의 연령별 · 항목 7개 (가구원, 가구 계, 미혼가구 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO02
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GAOO02
  survey: 인구총조사
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
    name: 가구주의 성별
    kind: sex
    n_codes: 3
    total_code: '0'
    codes:
    - {code: '0', name: 계, total: true}
    - {code: '1', name: 남자}
    - {code: '2', name: 여자}
  - level: 3
    name: 가구주의 연령별
    kind: age
    n_codes: 18
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '16', name: 15세미만}
    - {code: '20', name: 15 - 19세}
    - {code: '25', name: 20 - 24세}
    - {code: '30', name: 25 - 29세}
    - {code: '35', name: 30 - 34세}
    - {code: '40', name: 35 - 39세}
    - {code: '45', name: 40 - 44세}
    - {code: '50', name: 45 - 49세}
    - {code: '55', name: 50 - 54세}
    - {code: '60', name: 55 - 59세}
    - {code: '65', name: 60 - 64세}
    - {code: '70', name: 65 - 69세}
    - {code: '75', name: 70 - 74세}
    - {code: '80', name: 75 - 79세}
    - {code: '85', name: 80 - 84세}
    - {code: '87', name: 85세 이상}
    - {code: '95', name: 연령미상}
  items:
  - {id: T10, name: 가구원, unit: 명}
  - {id: T20, name: 가구 계, unit: 가구}
  - {id: T21, name: 미혼가구, unit: 가구}
  - {id: T22, name: 유배우가구, unit: 가구}
  - {id: T23, name: 사별가구, unit: 가구}
  - {id: T24, name: 이혼가구, unit: 가구}
  - {id: T25, name: 미상가구, unit: 가구}
---
# 행정구역/가구주의 성/가구주의 연령/혼인상태별 총조사가구(일반가구)

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO02

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-26aa1a1a.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 가구주의 성별 | sex | 3 | 0 | 0 계, 1 남자, 2 여자 |
| 3 | 가구주의 연령별 | age | 18 | 00 | 00 계, 16 15세미만, 20 15 - 19세, 25 20 - 24세, 30 25 - 29세, 35 30 - 34세, 40 35 - 39세, 45 40 - 44세, 50 45 - 49세, 55 50 - 54세, 60 55 - 59세, 65 60 - 64세, 70 65 - 69세, 75 70 - 74세, 80 75 - 79세, 85 80 - 84세, 87 85세 이상, 95 연령미상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 가구원 | 명 |  |  |
| T20 | 가구 계 | 가구 |  |  |
| T21 | 미혼가구 | 가구 |  |  |
| T22 | 유배우가구 | 가구 |  |  |
| T23 | 사별가구 | 가구 |  |  |
| T24 | 이혼가구 | 가구 |  |  |
| T25 | 미상가구 | 가구 |  |  |

# 메모

<!-- human:start -->
<!-- human:end -->
