---
type: Stat Table
title: 장래 기대수명 / 전국
description: 장래인구추계 · Y 1970~2072 (103개) · 분류 가정별, 성별 · 항목 1개 (기대수명)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1BPA201
tags: [장래인구추계]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:08+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1BPA201
  survey: 장래인구추계
  periods:
    Y: {from: '1970', to: '2072', n: 103}
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
    n_codes: 4
    total_code: '0'
    codes:
    - {code: '0', name: 전체, total: true}
    - {code: '1', name: 남자(A)}
    - {code: '2', name: 여자(B)}
    - {code: '3', name: 차이(B-A)}
  items:
  - {id: T10, name: 기대수명, unit: ''}
---
# 장래 기대수명 / 전국

- 조사: 장래인구추계
- 수록 기간: Y 1970~2072 (103개)
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1BPA201

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 가정별 | other | 3 |  | 1 중위, 2 고위, 3 저위 |
| 2 | 성별 | sex | 4 | 0 | 0 전체, 1 남자(A), 2 여자(B), 3 차이(B-A) |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 기대수명 |  |  |  |

# 주석

- 주) 2023년 12월에 공표한 장래인구추계 자료임.
- 2022년까지는 인구동태통계에 의한 기대수명 실적치이며, 2023년부터는 장래 사망력 가정에 의한 기대수명임.

# 메모

<!-- human:start -->
<!-- human:end -->
