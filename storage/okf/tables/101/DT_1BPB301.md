---
type: Stat Table
title: 장래 성 및 연령별 순이동률/시도
description: 장래인구추계 · Y 2022~2052 (8개) · 분류 시나리오별, 시도별, 성별, 연령별 · 항목 1개 (순이동률)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1BPB301
tags: [장래인구추계]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:08+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1BPB301
  survey: 장래인구추계
  periods:
    Y: ['2022', '2025', '2030', '2035', '2040', '2045', '2050', '2052']
  dims:
  - level: 1
    name: 시나리오별
    kind: other
    n_codes: 3
    codes:
    - {code: '1', name: '중위 추계(기본 추계: 출산율-중위 / 기대수명-중위 / 국제이동-중위 / 국내이동-중위)'}
    - {code: '2', name: '고위 추계(최대인구 추계: 출산율-고위 / 기대수명-고위 / 국제이동-고위 / 국내이동-중위)'}
    - {code: '3', name: '저위 추계(최소인구 추계: 출산율-저위 / 기대수명-저위 / 국제이동-저위 / 국내이동-중위)'}
  - level: 2
    name: 시도별
    kind: geo
    n_codes: 17
    codes:
    - {code: '11', name: 서울특별시}
    - {code: '21', name: 부산광역시}
    - {code: '22', name: 대구광역시}
    - {code: '23', name: 인천광역시}
    - {code: '24', name: 광주광역시}
    - {code: '25', name: 대전광역시}
    - {code: '26', name: 울산광역시}
    - {code: '29', name: 세종특별자치시}
    - {code: '31', name: 경기도}
    - {code: '32', name: 강원도}
    - {code: '33', name: 충청북도}
    - {code: '34', name: 충청남도}
    - {code: '35', name: 전라북도}
    - {code: '36', name: 전라남도}
    - {code: '37', name: 경상북도}
    - {code: '38', name: 경상남도}
    - {code: '39', name: 제주특별자치도}
  - level: 3
    name: 성별
    kind: sex
    n_codes: 2
    codes:
    - {code: '1', name: 남자}
    - {code: '2', name: 여자}
  - level: 4
    name: 연령별
    kind: age
    n_codes: 100
    classification: /classifications/age-85808f92.md
    examples: [0세, 1세, 2세, 3세, 4세, 5세, 6세, 7세]
  items:
  - {id: T10, name: 순이동률, unit: ''}
---
# 장래 성 및 연령별 순이동률/시도

- 조사: 장래인구추계
- 수록 기간: Y 2022~2052 (8개)
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1BPB301

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 시나리오별 | other | 3 |  | 1 중위 추계(기본 추계: 출산율-중위 / 기대수명-중위 / 국제이동-중위 / 국내이동-중위), 2 고위 추계(최대인구 추계: 출산율-고위 / 기대수명-고위 / 국제이동-고위 / 국내이동-중위), 3 저위 추계(최소인구 추계: 출산율-저위 / 기대수명-저위 / 국제이동-저위 / 국내이동-중위) |
| 2 | 시도별 | geo | 17 |  | 11 서울특별시, 21 부산광역시, 22 대구광역시, 23 인천광역시, 24 광주광역시, 25 대전광역시, 26 울산광역시, 29 세종특별자치시, 31 경기도, 32 강원도, 33 충청북도, 34 충청남도, 35 전라북도, 36 전라남도, 37 경상북도, 38 경상남도, 39 제주특별자치도 |
| 3 | 성별 | sex | 2 |  | 1 남자, 2 여자 |
| 4 | 연령별 | age | 100 |  | [100개 — 분류 파일](/classifications/age-85808f92.md) 예: 0세, 1세, 2세, 3세, 4세, 5세, 6세, 7세 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 순이동률 |  |  |  |

# 주석

- 주1) 2024년 5월에 공표한 장래인구추계 시도편 자료임.
- 주2) 국내 및 국제이동 추정치임.

# 메모

<!-- human:start -->
<!-- human:end -->
