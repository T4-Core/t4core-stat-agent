---
type: Stat Table
title: 성 및 연령별 추계인구(1세별, 5세별) / 전국
description: 장래인구추계 · Y 1960~2072 (113개) · 분류 가정별, 성별, 연령별 · 항목 1개 (추계인구)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1BPA001
tags: [장래인구추계]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:08+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1BPA001
  survey: 장래인구추계
  periods:
    Y: {from: '1960', to: '2072', n: 113}
  dims:
  - level: 1
    name: 가정별
    kind: other
    n_codes: 3
    codes:
    - {code: '1', name: '중위 추계(기본 추계: 출산율-중위 / 기대수명-중위 / 국제순이동-중위)'}
    - {code: '2', name: '고위 추계(최대인구 추계: 출산율-고위 / 기대수명-고위 / 국제순이동-고위)'}
    - {code: '3', name: '저위 추계(최소인구 추계: 출산율-저위 / 기대수명-저위 / 국제순이동-저위)'}
  - level: 2
    name: 성별
    kind: sex
    n_codes: 3
    total_code: '0'
    codes:
    - {code: '0', name: 전체, total: true}
    - {code: '1', name: 남자}
    - {code: '2', name: 여자}
  - level: 3
    name: 연령별
    kind: age
    n_codes: 123
    total_code: '000'
    classification: /classifications/age-bd980faa.md
    examples: [계, 0 - 4세, 0세, 1세, 2세, 3세, 4세, 5 - 9세]
  items:
  - {id: T10, name: 추계인구, unit: ''}
---
# 성 및 연령별 추계인구(1세별, 5세별) / 전국

- 조사: 장래인구추계
- 수록 기간: Y 1960~2072 (113개)
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1BPA001

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 가정별 | other | 3 |  | 1 중위 추계(기본 추계: 출산율-중위 / 기대수명-중위 / 국제순이동-중위), 2 고위 추계(최대인구 추계: 출산율-고위 / 기대수명-고위 / 국제순이동-고위), 3 저위 추계(최소인구 추계: 출산율-저위 / 기대수명-저위 / 국제순이동-저위) |
| 2 | 성별 | sex | 3 | 0 | 0 전체, 1 남자, 2 여자 |
| 3 | 연령별 | age | 123 | 000 | [123개 — 분류 파일](/classifications/age-bd980faa.md) 예: 계, 0 - 4세, 0세, 1세, 2세, 3세, 4세, 5 - 9세 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 추계인구 |  |  |  |

# 주석

- 주1) 2023년 12월에 공표한 장래인구추계 자료임.
- 주2) 매년 7월 1일 시점 자료임.
- 주3) 작성대상 인구는 국적과 상관없이 대한민국에 상주하는 인구임.(외국인 포함)
- 주4) 1960~2022년까지는 확정인구이며, 2023년 이후는 다음 인구추계시 변경될 수 있음.
- 주5) 중위추계(기본추계)는 인구변동요인별(출생, 사망, 국제이동) 중위가정을 조합한 결과,
- 고위추계(최대인구 추계)는 인구변동요인별(출생, 사망, 국제이동) 고위가정을 조합한 결과,
- 저위추계(최소인구 추계)는 인구변동요인별(출생, 사망, 국제이동) 저위가정을 조합한 결과임.
- 주6) 단위 : 명

# 메모

<!-- human:start -->
<!-- human:end -->
