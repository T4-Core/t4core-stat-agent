---
type: Stat Table
title: 행정구역/성/연령/혼인상태/거처의 종류별 1인 총조사가구
description: 인구총조사 · Y 2000 · 분류 행정구역별, 성별, 연령별, 혼인상태별 · 항목 12개 (계, 주택, 단독 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO21
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GAOO21
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
    name: 성별
    kind: sex
    n_codes: 3
    total_code: '0'
    codes:
    - {code: '0', name: 계, total: true}
    - {code: '1', name: 남자}
    - {code: '2', name: 여자}
  - level: 3
    name: 연령별
    kind: age
    n_codes: 18
    total_code: '000'
    codes:
    - {code: '000', name: 계, total: true}
    - {code: 090, name: 15세 미만}
    - {code: '100', name: 15 - 19세}
    - {code: '120', name: 20 - 24세}
    - {code: '130', name: 25 - 29세}
    - {code: '150', name: 30 - 34세}
    - {code: '160', name: 35 - 39세}
    - {code: '180', name: 40 - 44세}
    - {code: '190', name: 45 - 49세}
    - {code: '210', name: 50 - 54세}
    - {code: '230', name: 55 - 59세}
    - {code: '260', name: 60 - 64세}
    - {code: '280', name: 65 - 69세}
    - {code: '310', name: 70 - 74세}
    - {code: '330', name: 75 - 79세}
    - {code: '360', name: 80 - 84세}
    - {code: '370', name: 85세이상}
    - {code: '990', name: 연령미상}
  - level: 4
    name: 혼인상태별
    kind: other
    n_codes: 6
    total_code: '0'
    codes:
    - {code: '0', name: 계, total: true}
    - {code: '1', name: 미혼}
    - {code: '3', name: 유배우}
    - {code: '4', name: 이혼}
    - {code: '5', name: 사별}
    - {code: '8', name: 미상}
  items:
  - {id: T10, name: 계, unit: 가구, total: true}
  - {id: T20, name: 주택, unit: 가구}
  - {id: T21, name: 단독, unit: 가구}
  - {id: T22, name: 아파트, unit: 가구}
  - {id: T23, name: 연립, unit: 가구}
  - {id: T24, name: 다세대, unit: 가구}
  - {id: T25, name: 영업용 건물내 주택, unit: 가구}
  - {id: T30, name: 주택이외의 거처, unit: 가구}
  - {id: T31, name: 오피스텔, unit: 가구}
  - {id: T32, name: 호텔·여관 등, unit: 가구}
  - {id: T33, name: 기숙사회시설, unit: 가구}
  - {id: T34, name: 기타, unit: 가구}
---
# 행정구역/성/연령/혼인상태/거처의 종류별 1인 총조사가구

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO21

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-ac449e00.md) 예: 전국, 동부, 읍부, 면부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 성별 | sex | 3 | 0 | 0 계, 1 남자, 2 여자 |
| 3 | 연령별 | age | 18 | 000 | 000 계, 090 15세 미만, 100 15 - 19세, 120 20 - 24세, 130 25 - 29세, 150 30 - 34세, 160 35 - 39세, 180 40 - 44세, 190 45 - 49세, 210 50 - 54세, 230 55 - 59세, 260 60 - 64세, 280 65 - 69세, 310 70 - 74세, 330 75 - 79세, 360 80 - 84세, 370 85세이상, 990 연령미상 |
| 4 | 혼인상태별 | other | 6 | 0 | 0 계, 1 미혼, 3 유배우, 4 이혼, 5 사별, 8 미상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 계 | 가구 |  |  |
| T20 | 주택 | 가구 |  |  |
| T21 | 단독 | 가구 |  |  |
| T22 | 아파트 | 가구 |  |  |
| T23 | 연립 | 가구 |  |  |
| T24 | 다세대 | 가구 |  |  |
| T25 | 영업용 건물내 주택 | 가구 |  |  |
| T30 | 주택이외의 거처 | 가구 |  |  |
| T31 | 오피스텔 | 가구 |  |  |
| T32 | 호텔·여관 등 | 가구 |  |  |
| T33 | 기숙사회시설 | 가구 |  |  |
| T34 | 기타 | 가구 |  |  |

# 메모

<!-- human:start -->
<!-- human:end -->
