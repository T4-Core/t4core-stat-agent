---
type: Stat Table
title: 장래 연령별 출산율/시도
description: 장래인구추계 · Y 2022~2052 (8개) · 분류 가정별, 시도별, 연령별 · 항목 1개 (연령별 출산율)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1BPB101
tags: [장래인구추계]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:08+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1BPB101
  survey: 장래인구추계
  periods:
    Y: ['2022', '2025', '2030', '2035', '2040', '2045', '2050', '2052']
  dims:
  - level: 1
    name: 가정별
    kind: other
    n_codes: 3
    codes:
    - {code: '1', name: 중위}
    - {code: '2', name: 고위}
    - {code: '3', name: 저위}
  - level: 2
    name: 시도별
    kind: geo
    n_codes: 18
    total_code: '00'
    codes:
    - {code: '00', name: 전국, total: true}
    - {code: '11', name: 서울특별시}
    - {code: '21', name: 부산광역시}
    - {code: '22', name: 대구광역시}
    - {code: '23', name: 인천광역시}
    - {code: '24', name: 광주광역시}
    - {code: '25', name: 대전광역시}
    - {code: '26', name: 울산광역시}
    - {code: '29', name: 세종특별자치시}
    - {code: '31', name: 경기도}
    - {code: '32', name: 강원도}
    - {code: '33', name: 충청북도}
    - {code: '34', name: 충청남도}
    - {code: '35', name: 전라북도}
    - {code: '36', name: 전라남도}
    - {code: '37', name: 경상북도}
    - {code: '38', name: 경상남도}
    - {code: '39', name: 제주특별자치도}
  - level: 3
    name: 연령별
    kind: age
    n_codes: 36
    total_code: '000'
    codes:
    - {code: '000', name: TFR, total: true}
    - {code: '1001', name: 15세}
    - {code: '1002', name: 16세}
    - {code: '1003', name: 17세}
    - {code: '1004', name: 18세}
    - {code: '1005', name: 19세}
    - {code: '1201', name: 20세}
    - {code: '1202', name: 21세}
    - {code: '1203', name: 22세}
    - {code: '1204', name: 23세}
    - {code: '1205', name: 24세}
    - {code: '1301', name: 25세}
    - {code: '1302', name: 26세}
    - {code: '1303', name: 27세}
    - {code: '1304', name: 28세}
    - {code: '1305', name: 29세}
    - {code: '1501', name: 30세}
    - {code: '1502', name: 31세}
    - {code: '1503', name: 32세}
    - {code: '1504', name: 33세}
    - {code: '1505', name: 34세}
    - {code: '1601', name: 35세}
    - {code: '1602', name: 36세}
    - {code: '1603', name: 37세}
    - {code: '1604', name: 38세}
    - {code: '1605', name: 39세}
    - {code: '1801', name: 40세}
    - {code: '1802', name: 41세}
    - {code: '1803', name: 42세}
    - {code: '1804', name: 43세}
    - {code: '1805', name: 44세}
    - {code: '1901', name: 45세}
    - {code: '1902', name: 46세}
    - {code: '1903', name: 47세}
    - {code: '1904', name: 48세}
    - {code: '1905', name: 49세}
  items:
  - {id: T10, name: 연령별 출산율, unit: ''}
---
# 장래 연령별 출산율/시도

- 조사: 장래인구추계
- 수록 기간: Y 2022~2052 (8개)
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1BPB101

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 가정별 | other | 3 |  | 1 중위, 2 고위, 3 저위 |
| 2 | 시도별 | geo | 18 | 00 | 00 전국, 11 서울특별시, 21 부산광역시, 22 대구광역시, 23 인천광역시, 24 광주광역시, 25 대전광역시, 26 울산광역시, 29 세종특별자치시, 31 경기도, 32 강원도, 33 충청북도, 34 충청남도, 35 전라북도, 36 전라남도, 37 경상북도, 38 경상남도, 39 제주특별자치도 |
| 3 | 연령별 | age | 36 | 000 | 000 TFR, 1001 15세, 1002 16세, 1003 17세, 1004 18세, 1005 19세, 1201 20세, 1202 21세, 1203 22세, 1204 23세, 1205 24세, 1301 25세, 1302 26세, 1303 27세, 1304 28세, 1305 29세, 1501 30세, 1502 31세, 1503 32세, 1504 33세, 1505 34세, 1601 35세, 1602 36세, 1603 37세, 1604 38세, 1605 39세, 1801 40세, 1802 41세, 1803 42세, 1804 43세, 1805 44세, 1901 45세, 1902 46세, 1903 47세, 1904 48세, 1905 49세 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 연령별 출산율 |  |  |  |

# 주석

- 주) 2024년 5월에 공표한 장래인구추계 시도편 자료임.

# 메모

<!-- human:start -->
<!-- human:end -->
