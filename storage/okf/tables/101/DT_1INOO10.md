---
type: Stat Table
title: 국적/성/연령별 외국인
description: 인구총조사 · Y 2000 · 분류 국적별, 연령별 · 항목 3개 (인구, 남자, 여자)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO10
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:10+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1INOO10
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
    name: 연령별
    kind: age
    n_codes: 19
    total_code: '000'
    codes:
    - {code: '000', name: 계, total: true}
    - {code: '520', name: 0세}
    - {code: '040', name: 1 - 4세}
    - {code: '050', name: 5 - 9세}
    - {code: '070', name: 10 - 14세}
    - {code: '100', name: 15 - 19세}
    - {code: '120', name: 20 - 24세}
    - {code: '130', name: 25 - 29세}
    - {code: '150', name: 30 - 34세}
    - {code: '160', name: 35 - 39세}
    - {code: '180', name: 40 - 44세}
    - {code: '190', name: 45 - 49세}
    - {code: '210', name: 50 - 54세}
    - {code: '230', name: 55 - 59세}
    - {code: '260', name: 60 - 64세}
    - {code: '280', name: 65 - 69세}
    - {code: '310', name: 70 - 74세}
    - {code: '320', name: 75세이상}
    - {code: '990', name: 연령미상}
  items:
  - {id: T1, name: 인구, unit: 명}
  - {id: T2, name: 남자, unit: 명}
  - {id: T3, name: 여자, unit: 명}
  siblings:
  - {path: /tables/101/DT_1IN0514.md, rel: 지역 수준판}
  - {path: /tables/101/DT_1IN3012.md, rel: 같은 무리}
  - {path: /tables/101/DT_1IN3513.md, rel: 같은 무리}
---
# 국적/성/연령별 외국인

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO10

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 국적별 | nationality | 21 | 00 | 00 계, 01 중국, 02 중국(조선족), 03 중국(대만), 04 일본, 05 필리핀, 06 파키스탄, 07 네팔, 08 태국, 09 말레이시아, 10 인도네시아, 11 방글라데시, 12 인도, 13 베트남, 14 미국, 15 캐나다, 16 영국, 17 프랑스, 18 독일, 19 호주, 20 기타 |
| 2 | 연령별 | age | 19 | 000 | 000 계, 520 0세, 040 1 - 4세, 050 5 - 9세, 070 10 - 14세, 100 15 - 19세, 120 20 - 24세, 130 25 - 29세, 150 30 - 34세, 160 35 - 39세, 180 40 - 44세, 190 45 - 49세, 210 50 - 54세, 230 55 - 59세, 260 60 - 64세, 280 65 - 69세, 310 70 - 74세, 320 75세이상, 990 연령미상 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T1 | 인구 | 명 |  |  |
| T2 | 남자 | 명 |  |  |
| T3 | 여자 | 명 |  |  |

# 형제 표

- [국적/성/연령별 외국인-전국](/tables/101/DT_1IN0514.md) — 지역 수준판
- [국적/성/연령별 외국인](/tables/101/DT_1IN3012.md) — 같은 무리
- [국적/성/연령별 외국인](/tables/101/DT_1IN3513.md) — 같은 무리

# 메모

<!-- human:start -->
<!-- human:end -->
