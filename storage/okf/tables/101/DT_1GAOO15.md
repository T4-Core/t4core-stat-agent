---
type: Stat Table
title: 행정구역/거처의 종류/가구원수,사용방수,연면적별 총조사가구(일반가구)
description: 인구총조사 · Y 2000 · 분류 행정구역별, 거처종류별 · 항목 6개 (가구, 가구원수, 가구당 평균인원수 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO15
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GAOO15
  survey: 인구총조사
  periods:
    Y: ['2000']
  dims:
  - level: 1
    name: 행정구역별
    kind: geo
    n_codes: 314
    total_code: '00'
    classification: /classifications/geo-ac449e00.md
    examples: [전국, 동부, 읍부, 면부, 서울특별시, 종로구, 중구, 용산구]
  - level: 2
    name: 거처종류별
    kind: other
    n_codes: 8
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '10', name: 주택}
    - {code: '11', name: 단독주택}
    - {code: '12', name: 아파트}
    - {code: '14', name: 연립주택}
    - {code: '15', name: 다세대주택}
    - {code: '16', name: 영업용 건물내 주택}
    - {code: '20', name: 주택이외의 거처}
  items:
  - {id: T1, name: 가구, unit: 가구}
  - {id: T2, name: 가구원수, unit: 명}
  - {id: T3, name: 가구당 평균인원수, unit: 명}
  - {id: T4, name: 가구당 평균사용방수, unit: 개}
  - {id: T5, name: 가구당 연면적, unit: 평}
  - {id: T6, name: 1인당 연면적, unit: 평}
---
# 행정구역/거처의 종류/가구원수,사용방수,연면적별 총조사가구(일반가구)

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GAOO15

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 314 | 00 | [314개 — 분류 파일](/classifications/geo-ac449e00.md) 예: 전국, 동부, 읍부, 면부, 서울특별시, 종로구, 중구, 용산구 |
| 2 | 거처종류별 | other | 8 | 00 | 00 계, 10 주택, 11 단독주택, 12 아파트, 14 연립주택, 15 다세대주택, 16 영업용 건물내 주택, 20 주택이외의 거처 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T1 | 가구 | 가구 |  |  |
| T2 | 가구원수 | 명 |  |  |
| T3 | 가구당 평균인원수 | 명 |  |  |
| T4 | 가구당 평균사용방수 | 개 |  |  |
| T5 | 가구당 연면적 | 평 |  |  |
| T6 | 1인당 연면적 | 평 |  |  |

# 메모

<!-- human:start -->
<!-- human:end -->
