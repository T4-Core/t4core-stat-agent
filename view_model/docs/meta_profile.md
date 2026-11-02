# meta_profile.py — ⓪ 메타 프로필 (표 탐색 범위)

## 한눈에 보기

| | |
|---|---|
| **하는 일** | 카탈로그 전체(992개 표)의 **메타 JSON 만** 읽어서, 표마다 "어떤 조건으로 답할 수 있는 표인가"를 요약한다 |
| **왜** | 표를 미리 정하면 정답을 알려주고 고르게 하는 것과 같다. **표를 찾는 것 자체가 View 모듈의 일**이므로 탐색 범위는 전체여야 한다 |
| **입력** | `kosis_data/catalog.csv` (`selected == True`), `kosis_data/meta/<기관_표>.json` — 원본 CSV 는 읽지 않음 |
| **출력** | `output/meta_profiles.jsonl` (한 줄 = 표 하나, 992줄) |
| **실행** | API `POST /meta/profiles/build` · CLI `cd view_model && ../.venv/Scripts/python.exe -m services.meta_profile` (약 10초) |
| **코드 위치** | 로직 `services/meta_profile.py` (`build_all()`), API `routers/meta.py` |
| **다음 단계** | ③ `resolve.py` 가 이 파일에서 후보를 찾고 점수를 매긴다 → 고른 표만 `normalize.ensure_normalized()` 로 정규화 |

```
[메타 프로필 + 지연 정규화]

카탈로그 992개 ─▶ meta_profile.py ─▶ meta_profiles.jsonl        (전부, 가볍게, 10초)
                                          │
                                          ▼
                        resolve.py: 후보 검색 → 조건 점수 → 규칙   (992개 전체에서 고름)
                                          │ 고른 표
                                          ▼
                        normalize.ensure_normalized(tbl_id)       (그 표만, 캐시 있으면 재사용)
                                          │
                                          ▼
                        실제 parquet 프로필로 조건 재확인 → build_view
```

---

## 1. 정규화 프로필과 무엇이 다른가

| | 메타 프로필 (`meta_profiles.jsonl`) | 정규화 프로필 (`profiles/*.json`) |
|---|---|---|
| 범위 | 992개 전부 | 고른 표만 |
| 근거 | 메타 JSON (정의된 코드·시점) | 실제 parquet (실제로 있는 값) |
| 비용 | 표당 수 ms | 표당 수 초~수 분 (740MB 표는 1분 이상) |
| 쓰는 곳 | 표 고르기 (후보·점수) | 고른 뒤 조건 재확인, View 생성 |
| 분류 판정 규칙 | **같음** (`normalize.build_level_dims` 재사용) | 같음 |

메타는 "정의"라서 실제 데이터와 다를 수 있다. 예: `DT_1B040A3` 메타 주기에는 `월 2011.01~2026.09`가 있지만 수집된 원본에는 월 자료가 없다 (`ys_work/NOTES.md`의 월 누락 이슈).
그래서 **메타 프로필로 고르고, 고른 표는 실제 프로필로 다시 확인**하는 2단계로 한다.

---

## 2. 코드 구성

| 함수 | 하는 일 |
|---|---|
| `se_std(se)` | 메타 시점 구분(`년`·`5년`·`분기`…) → 표준 코드. `normalize.se_case_sql` 과 같은 규칙의 파이썬판 |
| `meta_periods(meta)` | 메타 `PRD` → `[{se, se_raw, start, end, year_from, year_to}]` |
| `level_summary(info, rows)` | `normalize.build_level_dims` 결과(코드별 행)에서 표 고르기에 필요한 것만 요약 |
| `cat(v)` | 카탈로그 빈 칸(NaN) → `None` (NaN 은 JSON 표준이 아님) |
| `table_profile(row)` | 표 하나의 메타 프로필 |
| `load_meta_profiles()` | 다른 엔드포인트가 이 파일을 읽을 때 쓰는 함수 |

**새 규칙은 없다.** 분류 종류(`kind`)·합계·지역 표준명·연령 범위는 모두 `normalize.py` 의 함수를 그대로 부른다. 그래서 메타 프로필과 정규화 프로필의 판정이 어긋나지 않는다.
**점수나 판단도 하지 않는다.** 사실만 기록하고 판단은 `resolve.py` 가 한다.

---

## 3. 출력 형식 (한 줄 = 표 하나)

| 키 | 내용 | 예 (`DT_1B040A3`) |
|---|---|---|
| `table_key`, `org_id`, `tbl_id`, `tbl_nm` | 표 식별자·이름 | `101_DT_1B040A3`, 행정구역(시군구)별, 성별 인구수 |
| `category`, `section`, `path`, `survey_nm`, `survey_type` | 조사·메뉴 위치 | 주민등록인구현황 |
| `send_de`, `also_in` | 갱신일, 다른 메뉴에도 있는지 | 2026-10-02 |
| `meta_ok` | 메타에 코드 목록이 있는지 | true |
| `raw` | 원본 CSV 존재·크기(MB) — 지연 정규화 비용 가늠용 | `{exists: true, mb: 4.1}` |
| `periods[]` | 메타상 주기별 범위 | `월 2011~2026`, `년 1992~2025` |
| `levels[]` | 분류마다 `kind`, `obj_nm`, `n_codes`, `total`, `default`, `names`(코드 이름 최대 300개) | 행정구역(시군구)별, regions, 418개 |
| ↳ 지역 분류 | `geo_types`(유형별 코드 수), `sido`(시도 표준명 목록) | 전국 1, 시도 19, 시군구 381 … |
| ↳ 연령 분류 | `ages`(코드별 숫자 범위), `age_min`, `age_max` | |
| ↳ 시나리오 | `scenarios` (중위/고위/저위 …) | |
| `items[]`, `units` | 항목(itm_id·이름·단위), 단위 목록 | 총인구수·남자인구수·여자인구수, 명 |
| `notes` | 표 주석 앞 5개 (실측/추계·기준 판단에 참고) | "연말기준, 주민등록에 의한 집계, 외국인 제외" |
| `profile_from` | `"meta"` (정규화 프로필과 구분) | |

---

## 4. 실행 결과 (2026-11-02)

| 항목 | 값 |
|---|---|
| 표 | 992개, 실패 0 |
| 원본 CSV 없음 | 3개 (고르더라도 정규화 불가 → resolve 에서 감점·제외) |
| 분류 종류 (분류 개수) | regions 701, other 598, sex 414, ages 353, nationality 161, scenario 21, cohort 21 |
| 지역 분류가 있는 표 | 701 (그중 시도 표준명이 잡힌 표 695) |
| 메타 주기 | `년`→Y 442, `5년`→F 433, `2년`→F 87, 부정기 29, 월 29, 분기 15 |
| 메타 단위 없음 | 492개 표 |

### 결과 해석 — resolve 가 알아야 할 것

1. **`5년`·`2년` 주기(F)가 520개**: 인구총조사 같은 다년주기 표. 메타에는 `F` 지만 원본 CSV 에는 `A`(연간)로 들어 있어서 정규화 후에는 `Y` 가 된다.
   → resolve 는 **주기 코드가 아니라 연도 범위(`year_from/to`)로** 시점 조건을 비교해야 한다.
2. **단위 없음 492개**: 메타 항목의 `UNIT_NM` 이 비어 있고 단위가 **항목 이름 안에** 있다 (`총인구(명)`, `총인구_성비`).
   정규화 때는 원본 CSV 의 단위를 쓰므로 문제없고, 메타 단계에서만 비어 보인다.
   → resolve 는 단위 조건이 필요하면 항목 이름의 괄호 `(명)`·`(%)` 도 본다.
3. **메타 시점 ≠ 실제 시점**: 메타에 월 주기가 있어도 원본에 없을 수 있다 → 고른 뒤 정규화 프로필로 재확인.

---

## 5. 변경 기록

| 날짜 | 내용 |
|---|---|
| 2026-11-02 | 작성. 표 7개를 미리 정하던 방식(정답 누출)을 버리고 카탈로그 전체를 탐색 범위로. 카탈로그 빈 칸 NaN → null 수정 |
| 2026-11-02 | `services/` 로 이동, 생성 로직을 `build_all()`(요약 반환)로 분리해 API(`POST /meta/profiles/build`)와 CLI 가 같이 씀. 조회 API `GET /meta/profiles`, `/meta/profiles/{tbl_id}` 추가 |
