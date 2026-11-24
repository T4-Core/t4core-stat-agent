---
type: Stat Table
title: 국적/성/교육정도별 외국인
description: 인구총조사 · Y 2000 · 분류 국적별, 교육정도별 · 항목 3개 (인구, 남자, 여자)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO13
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:10+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1INOO13
  survey: 인구총조사
  periods:
    Y: ['2000']
  dims:
  - level: 1
    name: 국적별
    kind: nationality
    n_codes: 21
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '01', name: 중국}
    - {code: '02', name: 중국(조선족)}
    - {code: '03', name: 중국(대만)}
    - {code: '04', name: 일본}
    - {code: '05', name: 필리핀}
    - {code: '06', name: 파키스탄}
    - {code: '07', name: 네팔}
    - {code: 08, name: 태국}
    - {code: 09, name: 말레이시아}
    - {code: '10', name: 인도네시아}
    - {code: '11', name: 방글라데시}
    - {code: '12', name: 인도}
    - {code: '13', name: 베트남}
    - {code: '14', name: 미국}
    - {code: '15', name: 캐나다}
    - {code: '16', name: 영국}
    - {code: '17', name: 프랑스}
    - {code: '18', name: 독일}
    - {code: '19', name: 호주}
    - {code: '20', name: 기타}
  - level: 2
    name: 교육정도별
    kind: other
    n_codes: 7
    total_code: '00'
    codes:
    - {code: '00', name: 계, total: true}
    - {code: '10', name: 초등학교}
    - {code: '20', name: 중학교}
    - {code: '30', name: 고등학교}
    - {code: '40', name: 대학이상}
    - {code: '50', name: 안다녔음}
    - {code: '90', name: 미상}
  items:
  - {id: T1, name: 인구, unit: 명}
  - {id: T2, name: 남자, unit: 명}
  - {id: T3, name: 여자, unit: 명}
  siblings:
  - {path: /tables/101/DT_1IN0517.md, rel: 지역 수준판}
---
# 국적/성/교육정도별 외국인

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO13

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 국적별 | nationality | 21 | 00 | 00 계, 01 중국, 02 중국(조선족), 03 중국(대만), 04 일본, 05 필리핀, 06 파키스탄, 07 네팔, 08 태국, 09 말레이시아, 10 인도네시아, 11 방글라데시, 12 인도, 13 베트남, 14 미국, 15 캐나다, 16 영국, 17 프랑스, 18 독일, 19 호주, 20 기타 |
| 2 | 교육정도별 | other | 7 | 00 | 00 계, 10 초등학교, 20 중학교, 30 고등학교, 40 대학이상, 50 안다녔음, 90 미상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T1 | 인구 | 명 |  |  |
| T2 | 남자 | 명 |  |  |
| T3 | 여자 | 명 |  |  |

# 형제 표

- [국적/성/교육정도별 외국인-전국](/tables/101/DT_1IN0517.md) — 지역 수준판

# 메모

<!-- human:start -->
<!-- human:end -->
