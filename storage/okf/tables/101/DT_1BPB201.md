---
type: Stat Table
title: 장래 생명표/시도
description: 장래인구추계 · Y 2022~2052 (8개) · 분류 가정별, 시도별, 성별, 연령별 · 항목 4개 (사망확률, 생존수(명), 정지인구(명) …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1BPB201
tags: [장래인구추계]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:08+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1BPB201
  survey: 장래인구추계
  periods:
    Y: ['2022', '2025', '2030', '2035', '2040', '2045', '2050', '2052']
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
    name: 시도별
    kind: geo
    n_codes: 18
    total_code: '00'
    codes:
    - {code: '00', name: 전국, total: true}
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
    n_codes: 22
    codes:
    - {code: '0401', name: 0세}
    - {code: 04A, name: 1-4세}
    - {code: '050', name: 5-9세}
    - {code: '070', name: 10-14세}
    - {code: '100', name: 15-19세}
    - {code: '120', name: 20-24세}
    - {code: '130', name: 25-29세}
    - {code: '150', name: 30-34세}
    - {code: '160', name: 35-39세}
    - {code: '180', name: 40-44세}
    - {code: '190', name: 45-49세}
    - {code: '210', name: 50-54세}
    - {code: '230', name: 55-59세}
    - {code: '260', name: 60-64세}
    - {code: '280', name: 65-69세}
    - {code: '310', name: 70-74세}
    - {code: '330', name: 75-79세}
    - {code: '360', name: 80-84세}
    - {code: '380', name: 85-89세}
    - {code: '410', name: 90-94세}
    - {code: '430', name: 95-99세}
    - {code: '440', name: 100세 이상}
  items:
  - {id: T10, name: 사망확률, unit: ''}
  - {id: T20, name: 생존수(명), unit: ''}
  - {id: T30, name: 정지인구(명), unit: ''}
  - {id: T40, name: 기대여명(년), unit: ''}
---
# 장래 생명표/시도

- 조사: 장래인구추계
- 수록 기간: Y 2022~2052 (8개)
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1BPB201

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 가정별 | other | 3 |  | 1 중위, 2 고위, 3 저위 |
| 2 | 시도별 | geo | 18 | 00 | 00 전국, 11 서울특별시, 21 부산광역시, 22 대구광역시, 23 인천광역시, 24 광주광역시, 25 대전광역시, 26 울산광역시, 29 세종특별자치시, 31 경기도, 32 강원도, 33 충청북도, 34 충청남도, 35 전라북도, 36 전라남도, 37 경상북도, 38 경상남도, 39 제주특별자치도 |
| 3 | 성별 | sex | 2 |  | 1 남자, 2 여자 |
| 4 | 연령별 | age | 22 |  | 0401 0세, 04A 1-4세, 050 5-9세, 070 10-14세, 100 15-19세, 120 20-24세, 130 25-29세, 150 30-34세, 160 35-39세, 180 40-44세, 190 45-49세, 210 50-54세, 230 55-59세, 260 60-64세, 280 65-69세, 310 70-74세, 330 75-79세, 360 80-84세, 380 85-89세, 410 90-94세, 430 95-99세, 440 100세 이상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 사망확률 |  |  |  |
| T20 | 생존수(명) |  |  |  |
| T30 | 정지인구(명) |  |  |  |
| T40 | 기대여명(년) |  |  |  |

# 주석

- 주1) 2024년 5월에 공표한 장래인구추계 시도편 자료임.
- 주2) 추계에 사용되는 모형에의 적용을 위해 보정된 사망률을 기초자료로 사용하였음

# 메모

<!-- human:start -->
<!-- human:end -->
