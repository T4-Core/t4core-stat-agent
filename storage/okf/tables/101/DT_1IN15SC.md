---
type: Stat Table
title: 성별 및 성씨ㆍ본관별 인구 - 시도
description: 인구총조사 · IR 2015 · 분류 성씨 본관별, 행정구역별(시도) · 항목 3개 (인구(내국인), 남자, 여자)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1IN15SC
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1IN15SC
  survey: 인구총조사
  periods:
    IR: ['2015']
  dims:
  - level: 1
    name: 성씨 본관별
    kind: other
    n_codes: 1166
    total_code: '0000'
    classification: /classifications/other-02b3709c.md
    examples: [계, 가(賈), 소주, 기타, 간(簡), 가평, 기타, 갈(葛)]
  - level: 2
    name: 행정구역별(시도)
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
    - {code: '32', name: 강원특별자치도}
    - {code: '33', name: 충청북도}
    - {code: '34', name: 충청남도}
    - {code: '35', name: 전북특별자치도}
    - {code: '36', name: 전라남도}
    - {code: '37', name: 경상북도}
    - {code: '38', name: 경상남도}
    - {code: '39', name: 제주특별자치도}
  items:
  - {id: T00, name: 인구(내국인), unit: 명}
  - {id: T10, name: 남자, unit: 명}
  - {id: T20, name: 여자, unit: 명}
  symbols:
    X: {count: 1975, meaning: 비밀보호를 위해 공표하지 않음}
---
# 성별 및 성씨ㆍ본관별 인구 - 시도

- 조사: 인구총조사
- 수록 기간: IR 2015
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1IN15SC

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 성씨 본관별 | other | 1166 | 0000 | [1166개 — 분류 파일](/classifications/other-02b3709c.md) 예: 계, 가(賈), 소주, 기타, 간(簡), 가평, 기타, 갈(葛) |
| 2 | 행정구역별(시도) | geo | 18 | 00 | 00 전국, 11 서울특별시, 21 부산광역시, 22 대구광역시, 23 인천광역시, 24 광주광역시, 25 대전광역시, 26 울산광역시, 29 세종특별자치시, 31 경기도, 32 강원특별자치도, 33 충청북도, 34 충청남도, 35 전북특별자치도, 36 전라남도, 37 경상북도, 38 경상남도, 39 제주특별자치도 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T00 | 인구(내국인) | 명 |  |  |
| T10 | 남자 | 명 |  |  |
| T20 | 여자 | 명 |  |  |

# 부호

- `X` 1975칸 — 비밀보호를 위해 공표하지 않음

# 주석

- 주1) 개인정보 보호와 자료 노출 위험성을 최소하기 위하여 5미만 자료는 x로 표기함
- 주2) 공표 주기 : 15년

# 메모

<!-- human:start -->
<!-- human:end -->
