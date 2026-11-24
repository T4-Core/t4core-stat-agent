---
type: Stat Table
title: 시도/산업및직업/성/종사상지위(60세 이상) 고령자인구
description: 인구총조사 · Y 1995 · 분류 산업및직업별, 시도별, 종사상의 지위별 · 항목 3개 (인구, 남자, 여자)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO950H
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GO950H
  survey: 인구총조사
  periods:
    Y: ['1995']
  dims:
  - level: 1
    name: 산업및직업별
    kind: other
    n_codes: 30
    codes:
    - {code: '10', name: 산업계}
    - {code: 1A, name: 농업수렵업및임업}
    - {code: 1B, name: 어업}
    - {code: 1C, name: 광업}
    - {code: 1D, name: 제조업}
    - {code: 1E, name: 전기가스및수도사업}
    - {code: 1F, name: 건설업}
    - {code: 1G, name: 도소매및소비자용품수리업}
    - {code: 1H, name: 숙박및음식점업}
    - {code: 1I, name: 운수창고및통신업}
    - {code: 1J, name: 금융및보험업}
    - {code: 1K, name: 부동산및사업서비스업}
    - {code: 1L, name: 공공행정및국방및사회보장업}
    - {code: 1M, name: 교육서비스업}
    - {code: 1N, name: 보건및사회복지사업}
    - {code: 1O, name: 기타공공사회및개인서비스업}
    - {code: 1P, name: 가사서비스업}
    - {code: 1Q, name: 국제및기타외국기관}
    - {code: 1Z, name: 미상}
    - {code: '20', name: 직업계}
    - {code: '21', name: 입법공무원고위임직원 및 관리자}
    - {code: '22', name: 전문가}
    - {code: '23', name: 기술공 및 준전문가}
    - {code: '24', name: 사무직원}
    - {code: '25', name: 서비스근로자 및 상점과 시장판매 근로자}
    - {code: '26', name: 농업 및 어업숙련 근로자}
    - {code: '27', name: 기능원 및 관련 기능근로자}
    - {code: '28', name: 장치기계조작원 및 조립원}
    - {code: '29', name: 단순노무직 근로자}
    - {code: 2Z, name: 기타}
  - level: 2
    name: 시도별
    kind: geo
    n_codes: 55
    total_code: '00'
    classification: /classifications/geo-67927953.md
    examples: [전국, 읍부, 면부, 동부, 서울특별시, 부산광역시, 읍부, 면부]
  - level: 3
    name: 종사상의 지위별
    kind: other
    n_codes: 6
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '10', name: 임금봉급 근로자}
    - {code: '20', name: 고용원이 없는 자영자}
    - {code: '30', name: 고용원을 둔 사업주}
    - {code: '40', name: 무급 가족종사자}
    - {code: '90', name: 미상}
  items:
  - {id: T10, name: 인구, unit: 명}
  - {id: T11, name: 남자, unit: 명}
  - {id: T12, name: 여자, unit: 명}
---
# 시도/산업및직업/성/종사상지위(60세 이상) 고령자인구

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 1995
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO950H

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 산업및직업별 | other | 30 |  | 10 산업계, 1A 농업수렵업및임업, 1B 어업, 1C 광업, 1D 제조업, 1E 전기가스및수도사업, 1F 건설업, 1G 도소매및소비자용품수리업, 1H 숙박및음식점업, 1I 운수창고및통신업, 1J 금융및보험업, 1K 부동산및사업서비스업, 1L 공공행정및국방및사회보장업, 1M 교육서비스업, 1N 보건및사회복지사업, 1O 기타공공사회및개인서비스업, 1P 가사서비스업, 1Q 국제및기타외국기관, 1Z 미상, 20 직업계, 21 입법공무원고위임직원 및 관리자, 22 전문가, 23 기술공 및 준전문가, 24 사무직원, 25 서비스근로자 및 상점과 시장판매 근로자, 26 농업 및 어업숙련 근로자, 27 기능원 및 관련 기능근로자, 28 장치기계조작원 및 조립원, 29 단순노무직 근로자, 2Z 기타 |
| 2 | 시도별 | geo | 55 | 00 | [55개 — 분류 파일](/classifications/geo-67927953.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 부산광역시, 읍부, 면부 |
| 3 | 종사상의 지위별 | other | 6 | 00 | 00 계, 10 임금봉급 근로자, 20 고용원이 없는 자영자, 30 고용원을 둔 사업주, 40 무급 가족종사자, 90 미상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 인구 | 명 |  |  |
| T11 | 남자 | 명 |  |  |
| T12 | 여자 | 명 |  |  |

# 주석

- 외국인, 특별조사구 인구제외.
- 10% 표본조사 자료를 이용, 추정된 것으로 전수집계 결과와 다소 차이가 있을
- 수 있음.

# 메모

<!-- human:start -->
<!-- human:end -->
