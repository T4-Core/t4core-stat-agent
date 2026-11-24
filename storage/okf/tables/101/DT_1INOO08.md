---
type: Stat Table
title: 시도/성/연령/혼인상태/교육정도별 총조사인구(15세 이상)
description: 인구총조사 · Y 2000 · 분류 시도별, 연령별, 혼인상태별, 교육정도별 · 항목 3개 (인구, 남자, 여자)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO08
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:10+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1INOO08
  survey: 인구총조사
  periods:
    Y: ['2000']
  dims:
  - level: 1
    name: 시도별
    kind: geo
    n_codes: 20
    total_code: '00'
    codes:
    - {code: '00', name: 전국, total: true}
    - {code: 0C, name: 읍부}
    - {code: 0D, name: 면부}
    - {code: 0E, name: 동부}
    - {code: '11', name: 서울특별시}
    - {code: '21', name: 부산광역시}
    - {code: '22', name: 대구광역시}
    - {code: '23', name: 인천광역시}
    - {code: '24', name: 광주광역시}
    - {code: '25', name: 대전광역시}
    - {code: '26', name: 울산광역시}
    - {code: '31', name: 경기도}
    - {code: '32', name: 강원도}
    - {code: '33', name: 충청북도}
    - {code: '34', name: 충청남도}
    - {code: '35', name: 전라북도}
    - {code: '36', name: 전라남도}
    - {code: '37', name: 경상북도}
    - {code: '38', name: 경상남도}
    - {code: '39', name: 제주도}
  - level: 2
    name: 연령별
    kind: age
    n_codes: 17
    total_code: '000'
    codes:
    - {code: '000', name: 계, total: true}
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
    n_codes: 6
    total_code: '0'
    codes:
    - {code: '0', name: 계, total: true}
    - {code: '1', name: 미혼}
    - {code: '3', name: 유배우}
    - {code: '4', name: 이혼}
    - {code: '5', name: 사별}
    - {code: '8', name: 미상}
  - level: 4
    name: 교육정도별
    kind: other
    n_codes: 32
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '10', name: 재학}
    - {code: '103', name: 초등학교, parent: '10'}
    - {code: '104', name: 중학교, parent: '10'}
    - {code: '105', name: 고등학교, parent: '10'}
    - {code: '106', name: 대학, parent: '10'}
    - {code: '107', name: 대학교, parent: '10'}
    - {code: '108', name: 대학원석사, parent: '10'}
    - {code: '109', name: 대학원박사, parent: '10'}
    - {code: '20', name: 졸업}
    - {code: '203', name: 초등학교, parent: '20'}
    - {code: '204', name: 중학교, parent: '20'}
    - {code: '205', name: 고등학교, parent: '20'}
    - {code: '206', name: 대학, parent: '20'}
    - {code: '207', name: 대학교, parent: '20'}
    - {code: '208', name: 대학원석사, parent: '20'}
    - {code: '209', name: 대학원박사, parent: '20'}
    - {code: '30', name: 중퇴}
    - {code: '303', name: 초등학교, parent: '30'}
    - {code: '304', name: 중학교, parent: '30'}
    - {code: '305', name: 고등학교, parent: '30'}
    - {code: '306', name: 대학, parent: '30'}
    - {code: '307', name: 대학교, parent: '30'}
    - {code: '308', name: 대학원석사, parent: '30'}
    - {code: '309', name: 대학원박사, parent: '30'}
    - {code: '40', name: 수료}
    - {code: '406', name: 대학, parent: '40'}
    - {code: '407', name: 대학교, parent: '40'}
    - {code: '408', name: 대학원석사, parent: '40'}
    - {code: '409', name: 대학원박사, parent: '40'}
    - {code: '50', name: 안다녔음}
    - {code: '99', name: 미상}
  items:
  - {id: T1, name: 인구, unit: 명}
  - {id: T2, name: 남자, unit: 명}
  - {id: T3, name: 여자, unit: 명}
---
# 시도/성/연령/혼인상태/교육정도별 총조사인구(15세 이상)

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO08

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 시도별 | geo | 20 | 00 | 00 전국, 0C 읍부, 0D 면부, 0E 동부, 11 서울특별시, 21 부산광역시, 22 대구광역시, 23 인천광역시, 24 광주광역시, 25 대전광역시, 26 울산광역시, 31 경기도, 32 강원도, 33 충청북도, 34 충청남도, 35 전라북도, 36 전라남도, 37 경상북도, 38 경상남도, 39 제주도 |
| 2 | 연령별 | age | 17 | 000 | 000 계, 100 15 - 19세, 120 20 - 24세, 130 25 - 29세, 150 30 - 34세, 160 35 - 39세, 180 40 - 44세, 190 45 - 49세, 210 50 - 54세, 230 55 - 59세, 260 60 - 64세, 280 65 - 69세, 310 70 - 74세, 330 75 - 79세, 360 80 - 84세, 370 85세이상, 990 연령미상 |
| 3 | 혼인상태별 | other | 6 | 0 | 0 계, 1 미혼, 3 유배우, 4 이혼, 5 사별, 8 미상 |
| 4 | 교육정도별 | other | 32 | 00 | 00 계, 10 재학, 103 초등학교, 104 중학교, 105 고등학교, 106 대학, 107 대학교, 108 대학원석사, 109 대학원박사, 20 졸업, 203 초등학교, 204 중학교, 205 고등학교, 206 대학, 207 대학교, 208 대학원석사, 209 대학원박사, 30 중퇴, 303 초등학교, 304 중학교, 305 고등학교, 306 대학, 307 대학교, 308 대학원석사, 309 대학원박사, 40 수료, 406 대학, 407 대학교, 408 대학원석사, 409 대학원박사, 50 안다녔음, 99 미상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T1 | 인구 | 명 |  |  |
| T2 | 남자 | 명 |  |  |
| T3 | 여자 | 명 |  |  |

# 주석

- 외국인 제외

# 메모

<!-- human:start -->
<!-- human:end -->
