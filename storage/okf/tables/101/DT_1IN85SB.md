---
type: Stat Table
title: 행정구역(구시군)/성씨·본관별 가구 및 인구
description: 인구총조사 · IR 1985 · 분류 성씨본관별, 행정구역(구시군)별 · 항목 2개 (가구, 인구)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1IN85SB
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '2026-11-23T11:43:10+09:00'}
x-t4-table:
  org_id: '101'
  tbl_id: DT_1IN85SB
  survey: 인구총조사
  periods:
    IR: ['1985']
  dims:
  - level: 1
    name: 성씨본관별
    kind: other
    n_codes: 4129
    total_code: '000'
    classification: /classifications/other-c52fc374.md
    examples: [계, 가(賈), 소주(소성), 기타, 미상, 간(簡), 가평, 경주]
  - level: 2
    name: 행정구역(구시군)별
    kind: geo
    n_codes: 246
    total_code: '00'
    classification: /classifications/geo-dd2a6103.md
    examples: [전국, 서울특별시, 종로구, 중구, 용산구, 성동구, 동대문구, 성북구]
  items:
  - {id: T1, name: 가구, unit: 가구}
  - {id: T2, name: 인구, unit: 명}
  siblings:
  - {path: /tables/101/DT_1INOOSB.md, rel: 같은 무리}
---
# 행정구역(구시군)/성씨·본관별 가구 및 인구

- 조사: 인구총조사 · 작성: 통계청 조사관리국 인구총조사과
- 수록 기간: IR 1985
- KOSIS: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1IN85SB

# Schema

## 분류

| 단계 | 분류 | 종류 | 코드 수 | 합계 코드 | 코드 |
|---|---|---|---|---|---|
| 1 | 성씨본관별 | other | 4129 | 000 | [4129개 — 분류 파일](/classifications/other-c52fc374.md) 예: 계, 가(賈), 소주(소성), 기타, 미상, 간(簡), 가평, 경주 |
| 2 | 행정구역(구시군)별 | geo | 246 | 00 | [246개 — 분류 파일](/classifications/geo-dd2a6103.md) 예: 전국, 서울특별시, 종로구, 중구, 용산구, 성동구, 동대문구, 성북구 |

## 항목

| ID | 이름 | 단위 | 성격 | 더할 수 있음 |
|---|---|---|---|---|
| T1 | 가구 | 가구 |  |  |
| T2 | 인구 | 명 |  |  |

# 주석

- 1) 가구, 인구 : 외국인 가구 및 인구는 제외하였으며, 가구수는 가구주의
- 성씨·본관을 기준으로 집계하였음.
- 2) 성씨·본관의 "기타"는 조사표상의 기입내용이 불명확한 경우이고,"미상"은
- 조사표상에 기재되지 않은 것임.
- 3) 梁, 呂, 廉, 柳, 李씨 등은 한글 맞춤법에 따라 양, 여, 염, 유, 이씨로
- 표기하였음
- 4) 공표 주기 : 15년
- (**)<b><a href="http://www.nso.go.kr/hanja/hanja.hwp">
- 한자 미표기 성씨 안내(hanja.hwp)</a></b>
- 클릭하면, 해당 한자를 볼 수 있습니다.

# 형제 표

- [행정구역(구시군)/성씨·본관별 가구 및 인구](/tables/101/DT_1INOOSB.md) — 같은 무리

# 메모

<!-- human:start -->
<!-- human:end -->
