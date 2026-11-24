---
type: Stat Table
title: 행정구역/주택의 종류/연건평/건축년도별 총조사주택
description: 주택총조사 · Y 2000 · 분류 행정구역별, 주택의종류별, 연건평별 · 항목 13개 (계, 2000년, 1999년 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JUOO05
tags: [주택총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:11+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1JUOO05
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
    name: 주택의종류별
    kind: other
    n_codes: 6
    total_code: '00'
    codes:
    - {code: '00', name: 총계, total: true}
    - {code: '11', name: 단독주택}
    - {code: '12', name: 아파트}
    - {code: '14', name: 연립주택}
    - {code: '15', name: 다세대주택}
    - {code: '16', name: 영업용 건물내 주택}
  - level: 3
    name: 연건평별
    kind: other
    n_codes: 10
    total_code: '00'
    codes:
    - {code: '00', name: 총계, total: true}
    - {code: '06', name: 7평미만}
    - {code: '07', name: 7-9평}
    - {code: 09, name: 9-14평}
    - {code: '14', name: 14-19평}
    - {code: '19', name: 19-29평}
    - {code: '29', name: 29-39평}
    - {code: '39', name: 39-49평}
    - {code: '49', name: 49-69평}
    - {code: '55', name: 69평이상}
  items:
  - {id: T01, name: 계, unit: 호, total: true}
  - {id: T02, name: 2000년, unit: 호}
  - {id: T03, name: 1999년, unit: 호}
  - {id: T04, name: 1998년, unit: 호}
  - {id: T05, name: 1997년, unit: 호}
  - {id: T06, name: 1996년, unit: 호}
  - {id: T07, name: 1995년, unit: 호}
  - {id: T08, name: 1990 - 1994년, unit: 호}
  - {id: T09, name: 1985 - 1989년, unit: 호}
  - {id: T10, name: 1980 - 1984년, unit: 호}
  - {id: T11, name: 1970 - 1979년, unit: 호}
  - {id: T12, name: 1960 - 1969년, unit: 호}
  - {id: T13, name: 1959년 이전, unit: 호}
---
# 행정구역/주택의 종류/연건평/건축년도별 총조사주택

- 조사: 주택총조사 · 작성: 통계청 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JUOO05

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-b97f7033.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 주택의종류별 | other | 6 | 00 | 00 총계, 11 단독주택, 12 아파트, 14 연립주택, 15 다세대주택, 16 영업용 건물내 주택 |
| 3 | 연건평별 | other | 10 | 00 | 00 총계, 06 7평미만, 07 7-9평, 09 9-14평, 14 14-19평, 19 19-29평, 29 29-39평, 39 39-49평, 49 49-69평, 55 69평이상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T01 | 계 | 호 |  |  |
| T02 | 2000년 | 호 |  |  |
| T03 | 1999년 | 호 |  |  |
| T04 | 1998년 | 호 |  |  |
| T05 | 1997년 | 호 |  |  |
| T06 | 1996년 | 호 |  |  |
| T07 | 1995년 | 호 |  |  |
| T08 | 1990 - 1994년 | 호 |  |  |
| T09 | 1985 - 1989년 | 호 |  |  |
| T10 | 1980 - 1984년 | 호 |  |  |
| T11 | 1970 - 1979년 | 호 |  |  |
| T12 | 1960 - 1969년 | 호 |  |  |
| T13 | 1959년 이전 | 호 |  |  |

# 메모

<!-- human:start -->
<!-- human:end -->
