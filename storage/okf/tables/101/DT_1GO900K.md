---
type: Stat Table
title: 시도/직업/성/종사상지위 고령자인구(65세이상)
description: 인구총조사 · Y 1990 · 분류 시도별, 직업별, 종사상의 지위별 · 항목 3개 (계, 남자, 여자)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO900K
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GO900K
  survey: 인구총조사
  periods:
    Y: ['1990']
  dims:
  - level: 1
    name: 시도별
    kind: geo
    n_codes: 36
    total_code: '00'
    codes:
    - {code: '00', name: 전국, total: true}
    - {code: 00A, name: 시부, parent: '00'}
    - {code: 00B, name: 군부, parent: '00'}
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
    name: 직업별
    kind: other
    n_codes: 9
    total_code: '0'
    codes:
    - {code: '0', name: 계, total: true}
    - {code: '1', name: 전문기술 및 관련직종사자}
    - {code: '2', name: 행정및관리직종사자}
    - {code: '3', name: 사무및관련직종사자}
    - {code: '4', name: 판매종사자}
    - {code: '5', name: 서비스직 종사자}
    - {code: '6', name: 농업축산업임업수산업 및 수렵업종사자}
    - {code: '7', name: 생산및관련종사자및운수장비운전사및단순노무자}
    - {code: '9', name: 분류불능자}
  - level: 3
    name: 종사상의 지위별
    kind: other
    n_codes: 5
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '10', name: 고용원을 둔 사업주}
    - {code: '11', name: 고용원이 없는 자영자}
    - {code: '12', name: 무급 가족종사자}
    - {code: '13', name: 임금봉급 근로자}
  items:
  - {id: T1, name: 계, unit: 명, total: true}
  - {id: T2, name: 남자, unit: 명}
  - {id: T3, name: 여자, unit: 명}
---
# 시도/직업/성/종사상지위 고령자인구(65세이상)

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 1990
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO900K

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 시도별 | geo | 36 | 00 | 00 전국, 00A 시부, 00B 군부, 11 서울특별시, 21 부산직할시, 22 대구직할시, 23 인천직할시, 24 광주직할시, 25 대전직할시, 31 경기도, 31A 시부, 31B 군부, 32 강원도, 32A 시부, 32B 군부, 33 충청북도, 33A 시부, 33B 군부, 34 충청남도, 34A 시부, 34B 군부, 35 전라북도, 35A 시부, 35B 군부, 36 전라남도, 36A 시부, 36B 군부, 37 경상북도, 37A 시부, 37B 군부, 38 경상남도, 38A 시부, 38B 군부, 39 제주도, 39A 시부, 39B 군부 |
| 2 | 직업별 | other | 9 | 0 | 0 계, 1 전문기술 및 관련직종사자, 2 행정및관리직종사자, 3 사무및관련직종사자, 4 판매종사자, 5 서비스직 종사자, 6 농업축산업임업수산업 및 수렵업종사자, 7 생산및관련종사자및운수장비운전사및단순노무자, 9 분류불능자 |
| 3 | 종사상의 지위별 | other | 5 | 00 | 00 계, 10 고용원을 둔 사업주, 11 고용원이 없는 자영자, 12 무급 가족종사자, 13 임금봉급 근로자 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T1 | 계 | 명 |  |  |
| T2 | 남자 | 명 |  |  |
| T3 | 여자 | 명 |  |  |

# 주석

- 외국인 제외.
- 특별조사구 인구 제외.
- 표본조사 항목인 '취업상태'에 관한 자료는 10% 표본조사를 이용하여 추정된
- 것으로 전수집계결과와 다소 차이가 있을수 있음.

# 메모

<!-- human:start -->
<!-- human:end -->
