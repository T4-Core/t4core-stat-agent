---
type: Stat Table
title: 시도/연령/성/취업상태별(60세 이상) 고령자인구
description: 인구총조사 · Y 1995 · 분류 시도별, 연령별, 취업상태별 · 항목 3개 (인구, 남자, 여자)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO950E
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:09+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1GO950E
  survey: 인구총조사
  periods:
    Y: ['1995']
  dims:
  - level: 1
    name: 시도별
    kind: geo
    n_codes: 55
    total_code: '00'
    classification: /classifications/geo-67927953.md
    examples: [전국, 읍부, 면부, 동부, 서울특별시, 부산광역시, 읍부, 면부]
  - level: 2
    name: 연령별
    kind: age
    n_codes: 7
    total_code: '000'
    codes:
    - {code: '000', name: 계, total: true}
    - {code: '260', name: 60 - 64세}
    - {code: '280', name: 65 - 69세}
    - {code: '300', name: 70 - 79세}
    - {code: '350', name: 80 - 89세}
    - {code: '400', name: 90 - 99세}
    - {code: '440', name: 100세이상}
  - level: 3
    name: 취업상태별
    kind: other
    n_codes: 7
    total_code: '00'
    codes:
    - {code: '00', name: 60세 이상 인구, total: true}
    - {code: '10', name: 일을한사람계}
    - {code: '11', name: 주로일하였음}
    - {code: '12', name: 가사를하면서틈틈히일하였음}
    - {code: '13', name: 학교(원)에다니면서틈틈히일하였음}
    - {code: '14', name: 다른활동을하면서틈틈히일하였음}
    - {code: '15', name: 사정에의해잠시쉼}
  items:
  - {id: T10, name: 인구, unit: 명}
  - {id: T11, name: 남자, unit: 명}
  - {id: T12, name: 여자, unit: 명}
---
# 시도/연령/성/취업상태별(60세 이상) 고령자인구

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 1995
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1GO950E

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 시도별 | geo | 55 | 00 | [55개 — 분류 파일](/classifications/geo-67927953.md) 예: 전국, 읍부, 면부, 동부, 서울특별시, 부산광역시, 읍부, 면부 |
| 2 | 연령별 | age | 7 | 000 | 000 계, 260 60 - 64세, 280 65 - 69세, 300 70 - 79세, 350 80 - 89세, 400 90 - 99세, 440 100세이상 |
| 3 | 취업상태별 | other | 7 | 00 | 00 60세 이상 인구, 10 일을한사람계, 11 주로일하였음, 12 가사를하면서틈틈히일하였음, 13 학교(원)에다니면서틈틈히일하였음, 14 다른활동을하면서틈틈히일하였음, 15 사정에의해잠시쉼 |

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
