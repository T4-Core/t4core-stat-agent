---
type: Stat Table
title: 시도/점유형태/성/거처의 종류별 고령자인구(65세이상)
description: 인구총조사 · Y 1990 · 분류 시도별, 점유형태별, 거처의 종류별 · 항목 4개 (고령자, 고령자 남자, 고령자 여자 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO900D
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GO900D
  survey: 인구총조사
  periods:
    Y: ['1990']
  dims:
  - level: 1
    name: 시도별
    kind: geo
    n_codes: 37
    total_code: '00'
    codes:
    - {code: '00', name: 전국, total: true}
    - {code: 00A, name: 시부, parent: '00'}
    - {code: 00C, name: 읍부, parent: '00'}
    - {code: 00D, name: 면부, parent: '00'}
    - {code: '11', name: 서울특별시}
    - {code: '21', name: 부산직할시}
    - {code: '22', name: 대구직할시}
    - {code: '23', name: 인천직할시}
    - {code: '24', name: 광주직할시}
    - {code: '25', name: 대전직할시}
    - {code: '31', name: 경기도}
    - {code: 31A, name: 시부, parent: '31'}
    - {code: 31B, name: 군부, parent: '31'}
    - {code: '32', name: 강원도}
    - {code: 32A, name: 시부, parent: '32'}
    - {code: 32B, name: 군부, parent: '32'}
    - {code: '33', name: 충청북도}
    - {code: 33A, name: 시부, parent: '33'}
    - {code: 33B, name: 군부, parent: '33'}
    - {code: '34', name: 충청남도}
    - {code: 34A, name: 시부, parent: '34'}
    - {code: 34B, name: 군부, parent: '34'}
    - {code: '35', name: 전라북도}
    - {code: 35A, name: 시부, parent: '35'}
    - {code: 35B, name: 군부, parent: '35'}
    - {code: '36', name: 전라남도}
    - {code: 36A, name: 시부, parent: '36'}
    - {code: 36B, name: 군부, parent: '36'}
    - {code: '37', name: 경상북도}
    - {code: 37A, name: 시부, parent: '37'}
    - {code: 37B, name: 군부, parent: '37'}
    - {code: '38', name: 경상남도}
    - {code: 38A, name: 시부, parent: '38'}
    - {code: 38B, name: 군부, parent: '38'}
    - {code: '39', name: 제주도}
    - {code: 39A, name: 시부, parent: '39'}
    - {code: 39B, name: 군부, parent: '39'}
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
    - {code: '5', name: 월세(사글세)}
    - {code: '6', name: 무상}
    - {code: '7', name: 미상}
  - level: 3
    name: 거처의 종류별
    kind: other
    n_codes: 10
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '10', name: 주택}
    - {code: '11', name: 단독주택}
    - {code: '12', name: 아파트}
    - {code: '14', name: 연립 및 다세대 주택}
    - {code: '16', name: 비주거용 건물 내 주택}
    - {code: '20', name: 주택이외의 거처}
    - {code: '22', name: 호텔여관등 숙박업소}
    - {code: '23', name: 기숙사 및 특수사회시설}
    - {code: '29', name: 기타}
  items:
  - {id: T10, name: 고령자, unit: 명}
  - {id: T11, name: 고령자 남자, unit: 명}
  - {id: T12, name: 고령자 여자, unit: 명}
  - {id: T20, name: 고령자 가구, unit: 가구}
---
# 시도/점유형태/성/거처의 종류별 고령자인구(65세이상)

- 조사: 인구총조사
- 수록 기간: Y 1990
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO900D

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 시도별 | geo | 37 | 00 | 00 전국, 00A 시부, 00C 읍부, 00D 면부, 11 서울특별시, 21 부산직할시, 22 대구직할시, 23 인천직할시, 24 광주직할시, 25 대전직할시, 31 경기도, 31A 시부, 31B 군부, 32 강원도, 32A 시부, 32B 군부, 33 충청북도, 33A 시부, 33B 군부, 34 충청남도, 34A 시부, 34B 군부, 35 전라북도, 35A 시부, 35B 군부, 36 전라남도, 36A 시부, 36B 군부, 37 경상북도, 37A 시부, 37B 군부, 38 경상남도, 38A 시부, 38B 군부, 39 제주도, 39A 시부, 39B 군부 |
| 2 | 점유형태별 | other | 7 | 0 | 0 계, 1 자가, 2 전세, 3 보증부월세, 5 월세(사글세), 6 무상, 7 미상 |
| 3 | 거처의 종류별 | other | 10 | 00 | 00 계, 10 주택, 11 단독주택, 12 아파트, 14 연립 및 다세대 주택, 16 비주거용 건물 내 주택, 20 주택이외의 거처, 22 호텔여관등 숙박업소, 23 기숙사 및 특수사회시설, 29 기타 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 고령자 | 명 |  |  |
| T11 | 고령자 남자 | 명 |  |  |
| T12 | 고령자 여자 | 명 |  |  |
| T20 | 고령자 가구 | 가구 |  |  |

# 주석

- 외국인 제외
- 특별조사구 인구 제외

# 메모

<!-- human:start -->
<!-- human:end -->
