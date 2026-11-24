---
type: Stat Table
title: 행정구역/거처의 종류/가구형태별 총조사가구(일반가구)
description: 인구총조사 · Y 2000 · 분류 행정구역별, 거처종류별 · 항목 11개 (20세 미만 가구주가구, 부자가구, 모자가구 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO14
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GAOO14
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
  items:
  - {id: T10, name: 20세 미만 가구주가구, unit: 가구}
  - {id: T20, name: 부자가구, unit: 가구}
  - {id: T30, name: 모자가구, unit: 가구}
  - {id: T40, name: 고령자 단독가구(60세 이상), unit: 가구}
  - {id: T41, name: 고령자 단독가구(60세 이상)-남자, unit: 가구}
  - {id: T42, name: 고령자 단독가구(60세 이상)-여자, unit: 가구}
  - {id: T50, name: 고령자 단독가구(65세 이상), unit: 가구}
  - {id: T51, name: 고령자 단독가구(65세 이상)-남자, unit: 가구}
  - {id: T52, name: 고령자 단독가구(65세 이상)-여자, unit: 가구}
  - {id: T61, name: 고령자 부부가구(60세 이상), unit: 가구}
  - {id: T62, name: 고령자 부부가구(65세 이상), unit: 가구}
---
# 행정구역/거처의 종류/가구형태별 총조사가구(일반가구)

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO14

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-26aa1a1a.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 거처종류별 | other | 8 | 00 | 00 계, 10 주택, 11 단독주택, 12 아파트, 14 연립주택, 15 다세대주택, 16 영업용 건물내 주택, 20 주택이외의 거처 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 20세 미만 가구주가구 | 가구 |  |  |
| T20 | 부자가구 | 가구 |  |  |
| T30 | 모자가구 | 가구 |  |  |
| T40 | 고령자 단독가구(60세 이상) | 가구 |  |  |
| T41 | 고령자 단독가구(60세 이상)-남자 | 가구 |  |  |
| T42 | 고령자 단독가구(60세 이상)-여자 | 가구 |  |  |
| T50 | 고령자 단독가구(65세 이상) | 가구 |  |  |
| T51 | 고령자 단독가구(65세 이상)-남자 | 가구 |  |  |
| T52 | 고령자 단독가구(65세 이상)-여자 | 가구 |  |  |
| T61 | 고령자 부부가구(60세 이상) | 가구 |  |  |
| T62 | 고령자 부부가구(65세 이상) | 가구 |  |  |

# 주석

- 부자가구는 부(사별 또는 이혼) + 미혼인 20세 미만 자녀가구를 의미함
- 모자가구는 모(사별 또는 이혼) + 미혼인 20세 미만 자녀가구를 의미함

# 메모

<!-- human:start -->
<!-- human:end -->
