---
type: Stat Table
title: 행정구역/연령/성별 총조사인구
description: 인구총조사 · Y 2000 · 분류 행정구역별, 연령별 · 항목 7개 (인구, 남자, 여자 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:10+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1INOO
  survey: 인구총조사
  periods:
    Y: ['2000']
  dims:
  - level: 1
    name: 행정구역별
    kind: geo
    n_codes: 3818
    total_code: '00'
    classification: /classifications/geo-a97654b0.md
    examples: [전국, 읍부, 면부, 동부, 서울특별시, 종로구, 청운동, 효자동]
  - level: 2
    name: 연령별
    kind: age
    n_codes: 110
    total_code: '00'
    classification: /classifications/age-44ccca08.md
    examples: [계, 0 - 4세, 0세, 1세, 2세, 3세, 4세, 5 - 9세]
  items:
  - {id: T10, name: 인구, unit: 명}
  - {id: T11, name: 남자, unit: 명}
  - {id: T12, name: 여자, unit: 명}
  - {id: T20, name: 구성비, unit: '%'}
  - {id: T21, name: 구성비(남자), unit: '%'}
  - {id: T22, name: 구성비(여자), unit: '%'}
  - {id: T30, name: 성비, unit: ''}
---
# 행정구역/연령/성별 총조사인구

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 3818 | 00 | [3818개 — 분류 파일](/classifications/geo-a97654b0.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 종로구, 청운동, 효자동 |
| 2 | 연령별 | age | 110 | 00 | [110개 — 분류 파일](/classifications/age-44ccca08.md) 예: 계, 0 - 4세, 0세, 1세, 2세, 3세, 4세, 5 - 9세 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 인구 | 명 |  |  |
| T11 | 남자 | 명 |  |  |
| T12 | 여자 | 명 |  |  |
| T20 | 구성비 | % |  |  |
| T21 | 구성비(남자) | % |  |  |
| T22 | 구성비(여자) | % |  |  |
| T30 | 성비 |  |  |  |

# 주석

- 외국인 제외
- 성비는 여자100명당 남자의 수

# 메모

<!-- human:start -->
<!-- human:end -->
