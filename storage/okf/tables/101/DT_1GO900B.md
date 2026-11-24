---
type: Stat Table
title: 시도/세대구성/점유형태별 고령자인구(65세이상)
description: 인구총조사 · Y 1990 · 분류 시도별, 세대구성별, 점유형태별 · 항목 2개 (고령자, 고령자가구)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO900B
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GO900B
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
    name: 세대구성별
    kind: sex
    n_codes: 19
    total_code: '00'
    codes:
    - {code: '00', name: 총계, total: true}
    - {code: '10', name: 1세대가구}
    - {code: '11', name: 부부}
    - {code: '19', name: 기타}
    - {code: '20', name: 2세대가구}
    - {code: '21', name: 부부 자녀}
    - {code: '22', name: 편부모 자녀}
    - {code: '24', name: 부부 양친}
    - {code: '25', name: 부부 편부모}
    - {code: '26', name: 부부 부부의 형제 또는 자매}
    - {code: '29', name: 기타}
    - {code: '30', name: 3세대가구}
    - {code: '31', name: 부부 자녀 양친}
    - {code: '32', name: 부부 자녀 편부모}
    - {code: '39', name: 기타}
    - {code: '40', name: 4세대이상가구}
    - {code: '50', name: 단독가구}
    - {code: '60', name: 비친족가구}
    - {code: '70', name: 미상}
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
    - {code: '5', name: 월세(사글세)}
    - {code: '6', name: 무상}
    - {code: '7', name: 미상}
  items:
  - {id: T1, name: 고령자, unit: 명}
  - {id: T2, name: 고령자가구, unit: 가구}
---
# 시도/세대구성/점유형태별 고령자인구(65세이상)

- 조사: 인구총조사
- 수록 기간: Y 1990
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO900B

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 시도별 | geo | 37 | 00 | 00 전국, 00A 시부, 00C 읍부, 00D 면부, 11 서울특별시, 21 부산직할시, 22 대구직할시, 23 인천직할시, 24 광주직할시, 25 대전직할시, 31 경기도, 31A 시부, 31B 군부, 32 강원도, 32A 시부, 32B 군부, 33 충청북도, 33A 시부, 33B 군부, 34 충청남도, 34A 시부, 34B 군부, 35 전라북도, 35A 시부, 35B 군부, 36 전라남도, 36A 시부, 36B 군부, 37 경상북도, 37A 시부, 37B 군부, 38 경상남도, 38A 시부, 38B 군부, 39 제주도, 39A 시부, 39B 군부 |
| 2 | 세대구성별 | sex | 19 | 00 | 00 총계, 10 1세대가구, 11 부부, 19 기타, 20 2세대가구, 21 부부 자녀, 22 편부모 자녀, 24 부부 양친, 25 부부 편부모, 26 부부 부부의 형제 또는 자매, 29 기타, 30 3세대가구, 31 부부 자녀 양친, 32 부부 자녀 편부모, 39 기타, 40 4세대이상가구, 50 단독가구, 60 비친족가구, 70 미상 |
| 3 | 점유형태별 | other | 7 | 0 | 0 계, 1 자가, 2 전세, 3 보증부월세, 5 월세(사글세), 6 무상, 7 미상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T1 | 고령자 | 명 |  |  |
| T2 | 고령자가구 | 가구 |  |  |

# 주석

- 외국인 제외
- 특별조사구 인구 제외

# 메모

<!-- human:start -->
<!-- human:end -->
