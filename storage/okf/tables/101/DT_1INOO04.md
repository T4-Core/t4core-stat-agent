---
type: Stat Table
title: 행정구역/성/연령/가구주와의 관계별 총조사인구
description: 인구총조사 · Y 2000 · 분류 행정구역별, 연령별, 가구주와관계별 · 항목 3개 (인구, 남자, 여자)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO04
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:10+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1INOO04
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
    n_codes: 90
    total_code: '00'
    classification: /classifications/age-7be39074.md
    examples: [계, 15세미만, 15 - 19세, 15세, 16세, 17세, 18세, 19세]
  - level: 3
    name: 가구주와관계별
    kind: other
    n_codes: 15
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '01', name: 가구주}
    - {code: '02', name: 가구주의 배우자}
    - {code: '03', name: 자녀}
    - {code: '04', name: 자녀의 배우자}
    - {code: '05', name: 가구주의 부모}
    - {code: '06', name: 배우자의부모}
    - {code: '07', name: 손자녀·그 배우자}
    - {code: 08, name: 증손자녀·그 배우자}
    - {code: 09, name: 조부모}
    - {code: '10', name: 형제자매·그 배우자}
    - {code: '11', name: 형제자매의 자녀·그 배우자}
    - {code: '12', name: 기타 친인척}
    - {code: '13', name: 기타 동거인}
    - {code: '14', name: 미상}
  items:
  - {id: T1, name: 인구, unit: 명}
  - {id: T2, name: 남자, unit: 명}
  - {id: T3, name: 여자, unit: 명}
---
# 행정구역/성/연령/가구주와의 관계별 총조사인구

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO04

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 행정구역별 | geo | 59 | 00 | [59개 — 분류 파일](/classifications/geo-ecd50e11.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 부산광역시, 읍부, 면부 |
| 2 | 연령별 | age | 90 | 00 | [90개 — 분류 파일](/classifications/age-7be39074.md) 예: 계, 15세미만, 15 - 19세, 15세, 16세, 17세, 18세, 19세 |
| 3 | 가구주와관계별 | other | 15 | 00 | 00 계, 01 가구주, 02 가구주의 배우자, 03 자녀, 04 자녀의 배우자, 05 가구주의 부모, 06 배우자의부모, 07 손자녀·그 배우자, 08 증손자녀·그 배우자, 09 조부모, 10 형제자매·그 배우자, 11 형제자매의 자녀·그 배우자, 12 기타 친인척, 13 기타 동거인, 14 미상 |

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
