---
type: Stat Table
title: 행정구역/성/연령/혼인상태/세대구성별 총조사인구
description: 인구총조사 · Y 2000 · 분류 행정구역별, 연령별, 혼인상태별, 세대구성별 · 항목 3개 (인구, 남자, 여자)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO07
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:10+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1INOO07
  survey: 인구총조사
  periods:
    Y: ['2000']
  dims:
  - level: 1
    name: 행정구역별
    kind: geo
    n_codes: 59
    total_code: '00'
    classification: /classifications/geo-ecd50e11.md
    examples: [전국, 읍부, 면부, 동부, 서울특별시, 부산광역시, 읍부, 면부]
  - level: 2
    name: 연령별
    kind: age
    n_codes: 18
    total_code: '000'
    codes:
    - {code: '000', name: 계, total: true}
    - {code: 090, name: 15세 미만}
    - {code: '100', name: 15 - 19세}
    - {code: '120', name: 20 - 24세}
    - {code: '130', name: 25 - 29세}
    - {code: '150', name: 30 - 34세}
    - {code: '160', name: 35 - 39세}
    - {code: '180', name: 40 - 44세}
    - {code: '190', name: 45 - 49세}
    - {code: '210', name: 50 - 54세}
    - {code: '230', name: 55 - 59세}
    - {code: '260', name: 60 - 64세}
    - {code: '280', name: 65 - 69세}
    - {code: '310', name: 70 - 74세}
    - {code: '330', name: 75 - 79세}
    - {code: '360', name: 80 - 84세}
    - {code: '370', name: 85세이상}
    - {code: '990', name: 연령미상}
  - level: 3
    name: 혼인상태별
    kind: other
    n_codes: 5
    total_code: '0'
    codes:
    - {code: '0', name: 계, total: true}
    - {code: '1', name: 미혼}
    - {code: '2', name: 유배우}
    - {code: '3', name: 사별·이혼}
    - {code: '6', name: 미상}
  - level: 4
    name: 세대구성별
    kind: sex
    n_codes: 24
    total_code: '00'
    codes:
    - {code: '00', name: 총계, total: true}
    - {code: '10', name: 1세대가구}
    - {code: '11', name: 부부}
    - {code: '12', name: 부부+형제자매}
    - {code: '13', name: 부부+기타 친인척}
    - {code: '14', name: 가구주+형제자매}
    - {code: '15', name: 가구주+기타 친인척}
    - {code: '19', name: 기타 1세대 가구}
    - {code: '20', name: 2세대가구}
    - {code: '21', name: 부부+자녀}
    - {code: '22', name: 편부+자녀}
    - {code: '23', name: 편모+자녀}
    - {code: '24', name: 부부+양친}
    - {code: '25', name: 부부+편부모}
    - {code: '26', name: 부부+자녀+부부의형제자매}
    - {code: '27', name: 조부모+손자녀}
    - {code: '29', name: 기타 2세대 가구}
    - {code: '30', name: 3세대가구}
    - {code: '31', name: 부부+자녀+양친}
    - {code: '32', name: 부부+자녀+편부모}
    - {code: '39', name: 기타 3세대 가구}
    - {code: '40', name: 4세대이상가구}
    - {code: '50', name: 1인가구}
    - {code: '60', name: 비친족가구}
  items:
  - {id: T1, name: 인구, unit: 명}
  - {id: T2, name: 남자, unit: 명}
  - {id: T3, name: 여자, unit: 명}
---
# 행정구역/성/연령/혼인상태/세대구성별 총조사인구

- 조사: 인구총조사
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO07

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 59 | 00 | [59개 — 분류 파일](/classifications/geo-ecd50e11.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 부산광역시, 읍부, 면부 |
| 2 | 연령별 | age | 18 | 000 | 000 계, 090 15세 미만, 100 15 - 19세, 120 20 - 24세, 130 25 - 29세, 150 30 - 34세, 160 35 - 39세, 180 40 - 44세, 190 45 - 49세, 210 50 - 54세, 230 55 - 59세, 260 60 - 64세, 280 65 - 69세, 310 70 - 74세, 330 75 - 79세, 360 80 - 84세, 370 85세이상, 990 연령미상 |
| 3 | 혼인상태별 | other | 5 | 0 | 0 계, 1 미혼, 2 유배우, 3 사별·이혼, 6 미상 |
| 4 | 세대구성별 | sex | 24 | 00 | 00 총계, 10 1세대가구, 11 부부, 12 부부+형제자매, 13 부부+기타 친인척, 14 가구주+형제자매, 15 가구주+기타 친인척, 19 기타 1세대 가구, 20 2세대가구, 21 부부+자녀, 22 편부+자녀, 23 편모+자녀, 24 부부+양친, 25 부부+편부모, 26 부부+자녀+부부의형제자매, 27 조부모+손자녀, 29 기타 2세대 가구, 30 3세대가구, 31 부부+자녀+양친, 32 부부+자녀+편부모, 39 기타 3세대 가구, 40 4세대이상가구, 50 1인가구, 60 비친족가구 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T1 | 인구 | 명 |  |  |
| T2 | 남자 | 명 |  |  |
| T3 | 여자 | 명 |  |  |

# 주석

- 주) 특별조사구, 집단가구 및 외국인 제외

# 메모

<!-- human:start -->
<!-- human:end -->
