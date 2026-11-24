---
type: Stat Table
title: 총조사인구 총괄(시도/성/연령별)
description: 인구총조사 · IR 1925~2010 (18개) · 분류 행정구역별, 연령별 · 항목 4개 (인구, 남자, 여자 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1IN0001_ENG
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1IN0001_ENG
  survey: 인구총조사
  periods:
    IR: ['1925', '1930', '1935', '1940', '1944', '1949', '1955', '1960', '1966', '1970', '1975', '1980', '1985', '1990', '1995', '2000', '2005', '2010']
  dims:
  - level: 1
    name: 행정구역별
    kind: geo
    n_codes: 27
    total_code: '00'
    codes:
    - {code: '00', name: 전국, total: true}
    - {code: 0A, name: 시부}
    - {code: 0B, name: 군부}
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
    - {code: '61', name: 황해도}
    - {code: '62', name: 평안북도}
    - {code: '63', name: 평안남도}
    - {code: '64', name: 함경북도}
    - {code: '65', name: 함경남도}
  - level: 2
    name: 연령별
    kind: age
    n_codes: 27
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '05', name: 0 - 4세, parent: '96'}
    - {code: '10', name: 5 - 9세, parent: '96'}
    - {code: '15', name: 10 - 14세, parent: '96'}
    - {code: '20', name: 15 - 19세, parent: '97'}
    - {code: '25', name: 20 - 24세, parent: '97'}
    - {code: '30', name: 25 - 29세, parent: '97'}
    - {code: '35', name: 30 - 34세, parent: '97'}
    - {code: '40', name: 35 - 39세, parent: '97'}
    - {code: '45', name: 40 - 44세, parent: '97'}
    - {code: '50', name: 45 - 49세, parent: '97'}
    - {code: '55', name: 50 - 54세, parent: '97'}
    - {code: '60', name: 55 - 59세, parent: '97'}
    - {code: '65', name: 60 - 64세, parent: '97'}
    - {code: '70', name: 65 - 69세, parent: '98'}
    - {code: '75', name: 70 - 74세, parent: '98'}
    - {code: '77', name: 75세이상, parent: '98'}
    - {code: '80', name: 75 - 79세, parent: '77'}
    - {code: '84', name: 80세이상, parent: '77'}
    - {code: '85', name: 80 - 84세, parent: '84'}
    - {code: '90', name: 85세이상, parent: '84'}
    - {code: '95', name: 연령미상}
    - {code: '96', name: 15세미만}
    - {code: '97', name: 15 - 64세}
    - {code: '98', name: 65세이상}
    - {code: '99', name: 평균연령}
    - {code: 9A, name: 연령중위수}
  items:
  - {id: T10, name: 인구, unit: 명}
  - {id: T11, name: 남자, unit: 명}
  - {id: T12, name: 여자, unit: 명}
  - {id: T30, name: 성비, unit: ''}
  symbols:
    '-': {count: 163, meaning: '- 외국인 제외(단, 1960년은 외국인 포함)'}
---
# 총조사인구 총괄(시도/성/연령별)

- 조사: 인구총조사 · 작성: 조사관리국 인구총조사과
- 수록 기간: IR 1925~2010 (18개)
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1IN0001_ENG

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 27 | 00 | 00 전국, 0A 시부, 0B 군부, 0C 읍부, 0D 면부, 0E 동부, 11 서울특별시, 21 부산광역시, 22 대구광역시, 23 인천광역시, 24 광주광역시, 25 대전광역시, 26 울산광역시, 31 경기도, 32 강원도, 33 충청북도, 34 충청남도, 35 전라북도, 36 전라남도, 37 경상북도, 38 경상남도, 39 제주도, 61 황해도, 62 평안북도, 63 평안남도, 64 함경북도, 65 함경남도 |
| 2 | 연령별 | age | 27 | 00 | 00 계, 05 0 - 4세, 10 5 - 9세, 15 10 - 14세, 20 15 - 19세, 25 20 - 24세, 30 25 - 29세, 35 30 - 34세, 40 35 - 39세, 45 40 - 44세, 50 45 - 49세, 55 50 - 54세, 60 55 - 59세, 65 60 - 64세, 70 65 - 69세, 75 70 - 74세, 77 75세이상, 80 75 - 79세, 84 80세이상, 85 80 - 84세, 90 85세이상, 95 연령미상, 96 15세미만, 97 15 - 64세, 98 65세이상, 99 평균연령, 9A 연령중위수 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 인구 | 명 |  |  |
| T11 | 남자 | 명 |  |  |
| T12 | 여자 | 명 |  |  |
| T30 | 성비 |  |  |  |

# 부호

- `-` 163칸 — - 외국인 제외(단, 1960년은 외국인 포함)

# 주석

- - 외국인 제외(단, 1960년은 외국인 포함)

# 메모

<!-- human:start -->
<!-- human:end -->
