---
type: Stat Table
title: 성씨ㆍ본관별 인구 - 시군구
description: 인구총조사 · IR 2015 · 분류 성씨 본관별, 행정구역별(시군구) · 항목 1개 (인구)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1IN15SB
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1IN15SB
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
    name: 행정구역별(시군구)
    kind: geo
    n_codes: 282
    total_code: '00'
    classification: /classifications/geo-374b2faa.md
    examples: [전국, 서울특별시, 종로구, 중구, 용산구, 성동구, 광진구, 동대문구]
  items:
  - {id: T00, name: 인구, unit: 명}
  symbols:
    X: {count: 7273, meaning: 비밀보호를 위해 공표하지 않음}
---
# 성씨ㆍ본관별 인구 - 시군구

- 조사: 인구총조사
- 수록 기간: IR 2015
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1IN15SB

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 성씨 본관별 | other | 1166 | 0000 | [1166개 — 분류 파일](/classifications/other-02b3709c.md) 예: 계, 가(賈), 소주, 기타, 간(簡), 가평, 기타, 갈(葛) |
| 2 | 행정구역별(시군구) | geo | 282 | 00 | [282개 — 분류 파일](/classifications/geo-374b2faa.md) 예: 전국, 서울특별시, 종로구, 중구, 용산구, 성동구, 광진구, 동대문구 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T00 | 인구 | 명 |  |  |

# 부호

- `X` 7273칸 — 비밀보호를 위해 공표하지 않음

# 주석

- 주1) 개인정보 보호와 자료 노출 위험성을 최소하기 위하여 5미만 자료는 x로 표기함
- 주2) 공표 주기 : 15년

# 메모

<!-- human:start -->
<!-- human:end -->
