---
type: Stat Table
title: 국적/성/직업(대분류)별 외국인
description: 인구총조사 · Y 2000 · 분류 국적별, 직업별 · 항목 3개 (인구, 남자, 여자)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO12
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:10+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1INOO12
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
    name: 직업별
    kind: other
    n_codes: 12
    total_code: '0'
    codes:
    - {code: '0', name: 계, total: true}
    - {code: '1', name: 의회의원고위임직원 및 관리자}
    - {code: '2', name: 전문가}
    - {code: '3', name: 기술공 및 준전문가}
    - {code: '4', name: 사무 종사자}
    - {code: '5', name: 서비스 종사자}
    - {code: '6', name: 판매 종사자}
    - {code: '7', name: 농업임업 및 어업숙련종사자}
    - {code: '8', name: 기능원 및 관련 기능 종사자}
    - {code: '9', name: 장치기계조작 및 조립 종사자}
    - {code: A, name: 단순노무 종사자}
    - {code: B, name: 일하지 않음}
  items:
  - {id: T1, name: 인구, unit: 명}
  - {id: T2, name: 남자, unit: 명}
  - {id: T3, name: 여자, unit: 명}
  siblings:
  - {path: /tables/101/DT_1IN0516.md, rel: 지역 수준판}
---
# 국적/성/직업(대분류)별 외국인

- 조사: 인구총조사 · 작성: 국가데이터처 조사관리국 인구총조사과
- 수록 기간: Y 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOO12

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 국적별 | nationality | 21 | 00 | 00 계, 01 중국, 02 중국(조선족), 03 중국(대만), 04 일본, 05 필리핀, 06 파키스탄, 07 네팔, 08 태국, 09 말레이시아, 10 인도네시아, 11 방글라데시, 12 인도, 13 베트남, 14 미국, 15 캐나다, 16 영국, 17 프랑스, 18 독일, 19 호주, 20 기타 |
| 2 | 직업별 | other | 12 | 0 | 0 계, 1 의회의원고위임직원 및 관리자, 2 전문가, 3 기술공 및 준전문가, 4 사무 종사자, 5 서비스 종사자, 6 판매 종사자, 7 농업임업 및 어업숙련종사자, 8 기능원 및 관련 기능 종사자, 9 장치기계조작 및 조립 종사자, A 단순노무 종사자, B 일하지 않음 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T1 | 인구 | 명 |  |  |
| T2 | 남자 | 명 |  |  |
| T3 | 여자 | 명 |  |  |

# 형제 표

- [국적/성/직업(대분류)별 외국인-전국](/tables/101/DT_1IN0516.md) — 지역 수준판

# 메모

<!-- human:start -->
<!-- human:end -->
