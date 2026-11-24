---
type: Stat Table
title: 시도/산업/성/종사상지위 고령자인구(60세이상)
description: 인구총조사 · Y 1990 · 분류 시도별, 산업별, 종사상의 지위별 · 항목 3개 (계, 남자, 여자)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO900H
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GO900H
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
    name: 산업별
    kind: other
    n_codes: 11
    total_code: '0'
    codes:
    - {code: '0', name: 계, total: true}
    - {code: '1', name: 농업수렵업임업 및 어업}
    - {code: '2', name: 광업}
    - {code: '3', name: 제조업}
    - {code: '4', name: 전기가스및수도사업}
    - {code: '5', name: 건설업}
    - {code: '6', name: 도소매및소비자용품수리업숙박및음식점업}
    - {code: '7', name: 운수창고및통신업}
    - {code: '8', name: 금융및보험업부동산및사업서비스업}
    - {code: '9', name: 사회및개인서비스업}
    - {code: Z, name: 분류불능산업}
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
# 시도/산업/성/종사상지위 고령자인구(60세이상)

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 1990
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO900H

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 시도별 | geo | 36 | 00 | 00 전국, 00A 시부, 00B 군부, 11 서울특별시, 21 부산직할시, 22 대구직할시, 23 인천직할시, 24 광주직할시, 25 대전직할시, 31 경기도, 31A 시부, 31B 군부, 32 강원도, 32A 시부, 32B 군부, 33 충청북도, 33A 시부, 33B 군부, 34 충청남도, 34A 시부, 34B 군부, 35 전라북도, 35A 시부, 35B 군부, 36 전라남도, 36A 시부, 36B 군부, 37 경상북도, 37A 시부, 37B 군부, 38 경상남도, 38A 시부, 38B 군부, 39 제주도, 39A 시부, 39B 군부 |
| 2 | 산업별 | other | 11 | 0 | 0 계, 1 농업수렵업임업 및 어업, 2 광업, 3 제조업, 4 전기가스및수도사업, 5 건설업, 6 도소매및소비자용품수리업숙박및음식점업, 7 운수창고및통신업, 8 금융및보험업부동산및사업서비스업, 9 사회및개인서비스업, Z 분류불능산업 |
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
- 표본조사 항목인 '취업상태'에 관한 자료는 10% 표본조사 자료를 이용하여
- 추정된 것으로 전수집계결과와 다소 차이가 있을 수 있음.

# 메모

<!-- human:start -->
<!-- human:end -->
