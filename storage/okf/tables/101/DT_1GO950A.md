---
type: Stat Table
title: 시도/세대구성/점유형태별 고령자 및 고령자가구(60세 이상)
description: 인구총조사 · Y 1995 · 분류 시도별, 세대구성별, 점유형태별 · 항목 4개 (고령자, 고령자 남자, 고령자 여자 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO950A
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GO950A
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
    name: 세대구성별
    kind: sex
    n_codes: 20
    total_code: '00'
    codes:
    - {code: '00', name: 총계, total: true}
    - {code: '10', name: 1세대가구}
    - {code: '11', name: 부부}
    - {code: '19', name: 기타}
    - {code: '20', name: 2세대가구}
    - {code: '21', name: 부부 자녀}
    - {code: '22', name: 편부 자녀}
    - {code: '23', name: 편모 자녀}
    - {code: '24', name: 부부 양친}
    - {code: '25', name: 부부 편부모}
    - {code: '26', name: 부부 자녀 부부의형제자매}
    - {code: '27', name: 조부모 손자녀}
    - {code: '29', name: 기타}
    - {code: '30', name: 3세대가구}
    - {code: '31', name: 부부 자녀 양친}
    - {code: '32', name: 부부 자녀 편부모}
    - {code: '39', name: 기타}
    - {code: '40', name: 4세대이상가구}
    - {code: '50', name: 1인가구}
    - {code: '60', name: 비친족가구}
  - level: 3
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
  items:
  - {id: T10, name: 고령자, unit: 명}
  - {id: T11, name: 고령자 남자, unit: 명}
  - {id: T12, name: 고령자 여자, unit: 명}
  - {id: T20, name: 고령자 가구, unit: 가구}
---
# 시도/세대구성/점유형태별 고령자 및 고령자가구(60세 이상)

- 조사: 인구총조사
- 수록 기간: Y 1995
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO950A

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 시도별 | geo | 55 | 00 | [55개 — 분류 파일](/classifications/geo-a95fe93a.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 부산광역시, 읍부, 면부 |
| 2 | 세대구성별 | sex | 20 | 00 | 00 총계, 10 1세대가구, 11 부부, 19 기타, 20 2세대가구, 21 부부 자녀, 22 편부 자녀, 23 편모 자녀, 24 부부 양친, 25 부부 편부모, 26 부부 자녀 부부의형제자매, 27 조부모 손자녀, 29 기타, 30 3세대가구, 31 부부 자녀 양친, 32 부부 자녀 편부모, 39 기타, 40 4세대이상가구, 50 1인가구, 60 비친족가구 |
| 3 | 점유형태별 | other | 7 | 0 | 0 계, 1 자가, 2 전세, 3 보증부월세, 4 사글세, 5 무보증월세, 7 무상 |

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
