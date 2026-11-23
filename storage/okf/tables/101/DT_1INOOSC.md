---
type: Stat Table
title: 행정구역(시도)/성씨·본관별 가구 및 인구
description: 인구총조사 · IR 2000 · 분류 성씨본관별, 행정구역별 · 항목 4개 (가구, 인구, 남자 …)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOOSC
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:10+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1INOOSC
  survey: 인구총조사
  periods:
    IR: ['2000']
  dims:
  - level: 1
    name: 성씨본관별
    kind: other
    n_codes: 4939
    total_code: '000'
    classification: /classifications/other-b56017b0.md
    examples: [계, 가(賈), 소주(소성), 양주, 초락, 태원, 해평, 기타]
  - level: 2
    name: 행정구역별
    kind: geo
    n_codes: 20
    total_code: '00'
    codes:
    - {code: '00', name: 전국, total: true}
    - {code: '03', name: 동부}
    - {code: '04', name: 읍부}
    - {code: '05', name: 면부}
    - {code: '11', name: 서울특별시}
    - {code: '21', name: 부산광역시}
    - {code: '22', name: 대구광역시}
    - {code: '23', name: 인천광역시}
    - {code: '24', name: 광주광역시}
    - {code: '25', name: 대전광역시}
    - {code: '26', name: 울산광역시}
    - {code: '31', name: 경기도}
    - {code: '32', name: 강원도}
    - {code: '33', name: 충청북도}
    - {code: '34', name: 충청남도}
    - {code: '35', name: 전라북도}
    - {code: '36', name: 전라남도}
    - {code: '37', name: 경상북도}
    - {code: '38', name: 경상남도}
    - {code: '39', name: 제주도}
  items:
  - {id: T10, name: 가구, unit: 가구}
  - {id: T20, name: 인구, unit: 명}
  - {id: T21, name: 남자, unit: 명}
  - {id: T22, name: 여자, unit: 명}
---
# 행정구역(시도)/성씨·본관별 가구 및 인구

- 조사: 인구총조사 · 작성: 통계청 조사관리국 인구총조사과
- 수록 기간: IR 2000
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1INOOSC

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 성씨본관별 | other | 4939 | 000 | [4939개 — 분류 파일](/classifications/other-b56017b0.md) 예: 계, 가(賈), 소주(소성), 양주, 초락, 태원, 해평, 기타 |
| 2 | 행정구역별 | geo | 20 | 00 | 00 전국, 03 동부, 04 읍부, 05 면부, 11 서울특별시, 21 부산광역시, 22 대구광역시, 23 인천광역시, 24 광주광역시, 25 대전광역시, 26 울산광역시, 31 경기도, 32 강원도, 33 충청북도, 34 충청남도, 35 전라북도, 36 전라남도, 37 경상북도, 38 경상남도, 39 제주도 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T10 | 가구 | 가구 |  |  |
| T20 | 인구 | 명 |  |  |
| T21 | 남자 | 명 |  |  |
| T22 | 여자 | 명 |  |  |

# 주석

- 1) 가구, 인구 : 외국인 가구 및 인구는 제외하였으며, 가구수는 가구주의
- 성씨·본관을 기준으로 집계하였음.
- 2) 성씨·본관의 "기타"는 조사표상의 기입내용이 불명확한 경우이고,"미상"은
- 조사표상에 기재되지 않은 것임.
- - 성씨의 "기타"에는 혼인 등으로 인한 귀화인의 성씨가 포함되었음
- 3) 梁, 呂, 廉, 柳, 李씨 등은 한글 맞춤법에 따라 양, 여, 염, 유, 이씨로
- 분류 집계하였음
- 4)<b><a href="http://www.nso.go.kr/hanja/bon.hwp">유사본관(bon.hwp)</a>
- 클릭하면, 해당 내용을 볼 수 있습니다.
- 5) 공표 주기 : 15년
- (**)<b><a href="http://www.nso.go.kr/hanja/hanja.hwp">
- 한자 미표기 성씨 안내(hanja.hwp)</a></b>
- 클릭하면, 해당 한자를 볼 수 있습니다.

# 메모

<!-- human:start -->
<!-- human:end -->
