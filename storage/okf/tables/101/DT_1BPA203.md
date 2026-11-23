---
type: Stat Table
title: 장래 성 및 연령별 사망률 / 전국
description: 장래인구추계 · Y 2022~2072 (51개) · 분류 가정별, 성별, 연령별 · 항목 1개 (사망률)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1BPA203
tags: [장래인구추계]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:08+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1BPA203
  survey: 장래인구추계
  periods:
    Y: {from: '2022', to: '2072', n: 51}
  dims:
  - level: 1
    name: 가정별
    kind: other
    n_codes: 3
    codes:
    - {code: '1', name: 중위}
    - {code: '2', name: 고위}
    - {code: '3', name: 저위}
  - level: 2
    name: 성별
    kind: sex
    n_codes: 2
    codes:
    - {code: '1', name: 남자}
    - {code: '2', name: 여자}
  - level: 3
    name: 연령별
    kind: age
    n_codes: 101
    classification: /classifications/age-f2ad3004.md
    examples: [0세, 1세, 2세, 3세, 4세, 5세, 6세, 7세]
  items:
  - {id: T10, name: 사망률, unit: ''}
---
# 장래 성 및 연령별 사망률 / 전국

- 조사: 장래인구추계
- 수록 기간: Y 2022~2072 (51개)
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1BPA203

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 가정별 | other | 3 |  | 1 중위, 2 고위, 3 저위 |
| 2 | 성별 | sex | 2 |  | 1 남자, 2 여자 |
| 3 | 연령별 | age | 101 |  | [101개 — 분류 파일](/classifications/age-f2ad3004.md) 예: 0세, 1세, 2세, 3세, 4세, 5세, 6세, 7세 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 사망률 |  |  |  |

# 주석

- 주1) 2023년 12월에 공표한 장래인구추계 자료임

# 메모

<!-- human:start -->
<!-- human:end -->
