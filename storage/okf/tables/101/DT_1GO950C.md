---
type: Stat Table
title: 시도/점유형태/거처의종류별 고령자 및 고령자거주가구(60세이상)
description: 인구총조사 · Y 1995 · 분류 시도별, 점유형태별, 거처의 종류별 · 항목 4개 (고령자, 고령자 남자, 고령자 여자 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO950C
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GO950C
  survey: 인구총조사
  periods:
    Y: ['1995']
  dims:
  - level: 1
    name: 시도별
    kind: geo
    n_codes: 55
    total_code: '00'
    classification: /classifications/geo-a95fe93a.md
    examples: [전국, 읍부, 면부, 동부, 서울특별시, 부산광역시, 읍부, 면부]
  - level: 2
    name: 점유형태별
    kind: other
    n_codes: 7
    total_code: '0'
    codes:
    - {code: '0', name: 계, total: true}
    - {code: '1', name: 자가}
    - {code: '2', name: 전세}
    - {code: '3', name: 보증부월세}
    - {code: '4', name: 사글세}
    - {code: '5', name: 무보증월세}
    - {code: '7', name: 무상}
  - level: 3
    name: 거처의 종류별
    kind: other
    n_codes: 11
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '10', name: 주택}
    - {code: '11', name: 단독주택}
    - {code: '12', name: 아파트}
    - {code: '14', name: 연립주택}
    - {code: '15', name: 다세대주택}
    - {code: '16', name: 비주거용 건물 내 주택}
    - {code: '20', name: 주택이외의 거처}
    - {code: '21', name: 오피스텔}
    - {code: '22', name: 호텔여관등 숙박업소}
    - {code: '29', name: 기타}
  items:
  - {id: T10, name: 고령자, unit: 명}
  - {id: T11, name: 고령자 남자, unit: 명}
  - {id: T12, name: 고령자 여자, unit: 명}
  - {id: T20, name: 고령자 가구, unit: 가구}
---
# 시도/점유형태/거처의종류별 고령자 및 고령자거주가구(60세이상)

- 조사: 인구총조사
- 수록 기간: Y 1995
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO950C

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 시도별 | geo | 55 | 00 | [55개 — 분류 파일](/classifications/geo-a95fe93a.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 부산광역시, 읍부, 면부 |
| 2 | 점유형태별 | other | 7 | 0 | 0 계, 1 자가, 2 전세, 3 보증부월세, 4 사글세, 5 무보증월세, 7 무상 |
| 3 | 거처의 종류별 | other | 11 | 00 | 00 계, 10 주택, 11 단독주택, 12 아파트, 14 연립주택, 15 다세대주택, 16 비주거용 건물 내 주택, 20 주택이외의 거처, 21 오피스텔, 22 호텔여관등 숙박업소, 29 기타 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 고령자 | 명 |  |  |
| T11 | 고령자 남자 | 명 |  |  |
| T12 | 고령자 여자 | 명 |  |  |
| T20 | 고령자 가구 | 가구 |  |  |

# 주석

- 외국인, 특별조사구 인구제외.
- 집단가구 제외.

# 메모

<!-- human:start -->
<!-- human:end -->
