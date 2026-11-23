# OKF 지식 카탈로그 형식 (OKF v0.3)

`storage/okf/` 는 KOSIS 표·분류·개념 지식의 **단일 원천**이다. 정규 어휘 사전, 별칭, 코드북, 표 요약은 모두 이 번들에서 다시 만들어지는 파생물이다(`storage/okf_build/`).
코드: `backend/rag/okf/` · 테스트: `tests/test_okf.py`

OKF v0.3 규칙 중 이 번들이 따르는 것:
- `type` 만 필수다. 프론트매터가 없는 `.md`(README 등)는 건너뛴다.
- 번들 정보는 루트 `index.md` 프론트매터(`okf_version: "0.3"`, `title`, `description`, `license`)에 둔다.
- 사용자 정의 키는 `x-<producer>-<name>` 형식이다. 이 번들은 `x-t4-*` 를 쓴다.
- 폐기는 `status: deprecated` + `superseded_by` 로 한다.
- 링크는 종류 없는 관계다. 관계의 종류(형제 표, 개념 → 코드)는 `x-t4-*` 에 둔다.
- 신뢰 등급은 `generated` · `verified` 로 정한다. human-reviewed 는 `human:` 행위자만 얻는다.

## 번들 구조

```
storage/okf/                              git 에 커밋 (.gitignore 예외)
  index.md                                번들 정보 + 목록 (자동)
  log.md                                  변경 기록 (날짜별, 최신 먼저)
  tables/index.md · tables/<기관>/index.md   목록 (자동)
  tables/<기관>/<tbl_id>.md               type: Stat Table      자동 생성 (프로필의 함수)
  classifications/<kind>-<해시8>.md       type: Classification  코드가 50개 넘는 차원 (자동)
  concepts/<영역>/<영문-slug>.md          type: Stat Concept    사람이 관리 — 분류 코드 하나(또는 항목 하나) = 개념 하나
  concepts/_inbox/…                       자동으로 생긴 개념 (승인·옮기기에서). 채운 뒤 알맞은 폴더로
storage/okf_build/<해시>/                 파생물 (git 제외)
storage/okf_build/CURRENT                 지금 쓰는 빌드
```

파일 이름은 영문 slug, 제목(`title`)은 한글로 한다. Windows·git 에서 한글 경로 문제를 피하기 위해서다.

## 표 파일 — `type: Stat Table` (자동, 편집하지 않음)

```yaml
type: Stat Table
title: 세대구성 및 가구원수별 가구(일반가구) - 시군구
description: 인구총조사 · A 2015~2025 (11개) · 분류 행정구역별(시군구), 세대구성별 · 항목 9개 (…)
resource: https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1JC1516
tags: [인구총조사]
generated: {by: 'process:okf-tables/1', at: '…'}     # 내용이 바뀐 때만 새로 (git diff = 실제 변경)
x-t4-table:
  org_id: '101'
  tbl_id: DT_1JC1516
  survey: 인구총조사
  periods: {A: ['2015', …]}                         # 30개 넘으면 {from, to, n}
  dims:
  - {level: 1, name: 행정구역별(시군구), kind: geo, n_codes: 329, total_code: '00',
     classification: /classifications/geo-e15dea57.md, examples: [전국, …]}      # 50개 넘는 차원 → 분류 파일 + 예시
  - level: 2
    name: 세대구성별
    kind: other                                     # geo · sex · age · nationality · other
    n_codes: 26
    total_code: '00'
    codes:
    - {code: '203', name: 모+미혼자녀, parent: '20'}
  items:
  - {id: T10, name: 일반가구, unit: 가구, role: count, additive: true}
  - {id: T30, name: 평균 가구원 수, unit: 명, role: mean, additive: false}
  symbols: {X: {count: 1520, meaning: 비밀보호}}
  siblings:
  - {path: /tables/101/DT_1JC1515.md, rel: 지역 수준판}   # 성별판 · 지역 수준판 · 연도판 (search/siblings.py 규칙)
```

본문은 개요, `# Schema`(분류·항목 표), 부호, 주석, 형제 표, `# 메모` 순서다.

다시 생성해도 보존되는 것:
- `# 메모` 아래 `<!-- human:start -->…<!-- human:end -->` 구간
- 생성기가 모르는 키: `verified`, `superseded_by`, `x-<다른 producer>-*`

표 파일은 프로필만으로 만든다. 그래서 개념을 고쳐도 표 파일은 바뀌지 않는다(역링크는 빌드가 계산).

프로필에서 사라진 표는 지우지 않고 `status: deprecated` 로 둔다. 새 표가 있으면 사람이 `superseded_by: /tables/…` 를 적는다. 그러면 개념의 binds 가 그 경로를 따라간다(검사는 경고로 알림).

## 개념 파일 — `type: Stat Concept` (사람이 관리)

```yaml
type: Stat Concept
title: 모+미혼자녀
description: 한부모(어머니)와 미혼 자녀로 된 가구. 어머니의 혼인 상태는 묻지 않음
tags: [세대구성]
status: stable                                      # draft = 아무 별칭도 쓰지 않음 · deprecated (+ superseded_by)
generated: {by: 'human:toast', at: '…'}
verified: [{by: 'human:toast', at: '…'}]
x-t4-concept:
  aliases:
  - {text: 싱글맘}                                   # by 없음 = 개념 작성자가 쓴 별칭 → 사용
  - {text: 모자가정, by: vector+hcx, at: '…', verified: {by: 'human:toast', at: '…'}}   # 제안 + 사람 승인 → 사용
  - {text: 엄마 혼자 사는 집, by: vector+hcx}          # 승인 전 → 쓰지 않음 (검사에서 info)
  not:
  - {text: 미혼모, why: 어머니의 혼인 상태(미혼)까지 정함 — 모+미혼자녀의 일부}
  binds:
  - {table: /tables/101/DT_1JC1516.md, dim: 세대구성별, code: '203', name: 모+미혼자녀}
  # - {table: /tables/…, item: T30, name: 평균 가구원 수}      항목에 묶을 때
  # - {dim_kind: age, from: 65}                               표 대신 규칙으로 (연령 차원이 있는 모든 표)
  calc:
  - 식구 합계 = Σ(가구원수 N × N인 가구 수). 평균 가구원 수 × 가구 수는 반올림 오차가 큼
```

본문은 `# 정의`, `# 헷갈리는 말`, `# 표`(표 링크)로 쓴다.

**별칭을 쓰는 조건** (`lint.alias_active`): 개념이 draft·deprecated 가 아니어야 하고, 둘 중 하나를 만족해야 한다.
- `by` 가 없는 별칭 (개념 작성자가 쓴 것)
- `by` 가 있는 별칭(기계 제안)이면서 `verified` 에 `human:` 이 있는 것

`not` 은 세 곳에 쓴다.
- 벡터 후보 확인
- 별칭 충돌 검사
- 질문에 그 말이 나오면 개념을 붙여 주의사항으로 (`catalog.concepts_for`)

## 검사 (`python -m backend.rag.okf lint`, 빌드 전에 자동)

| 등급 | 규칙 |
|---|---|
| error (빌드 중단) | 프론트매터 YAML 오류 · 프론트매터는 있는데 `type` 없음 · binds 의 표·분류·코드·항목 없음 · `superseded_by` 가 없는 경로 · 같은 개념에서 별칭 = not · 모르는 `dim_kind` |
| warn | 코드·항목은 있는데 이름이 다름 (개편 의심) · 폐기된 표에 묶임 (superseded_by 를 따라가 확인) · 별칭이 개념 여러 개에 걸림 · 별칭이 다른 개념의 not 과 같음 · binds 없음 · 본문 링크 깨짐 |
| info | 승인 안 된 별칭 수 · 합계 코드에 묶임 · 프론트매터 없는 파일(README) · 프로필 없이 큰 차원 코드 확인 못 함 |

코드가 많은 차원의 코드는 프로필로 만든 코드북으로 확인한다. 그래서 `--profiles` 가 있어야 한다(기본 `VIEW_OUT_DIR/profiles`).

## 빌드 (`python -m backend.rag.okf build`)

순서:
1. 검사를 돌린다. 오류가 있으면 멈추고 CURRENT 는 그대로 둔다.
2. 입력 해시를 만든다(번들 md + 프로필 + CSV 값 사전).
3. `okf_build/<해시>.tmp-<pid>/` 에 파생물을 전부 쓴다.
4. 폴더 이름을 `<해시>` 로 바꾼다.
5. `CURRENT` 를 임시 파일 + `os.replace` 로 교체한다. Windows 에서도 원자적이라, 인덱스가 하나씩 갱신되는 동안 섞이는 일이 없다.
6. 최근 3개 빌드만 남긴다.

같은 입력이면 다시 만들지 않는다. 되돌리기는 `python -m backend.rag.okf use <해시>` 다.

| 파생물 | 내용 · 쓰는 곳 |
|---|---|
| `vocab.json` | 정규 어휘 사전 (프로필 + CSV 값 사전). `query_analyzer/vocab.get_vocab` 이 OKF 빌드를 먼저 읽음 |
| `aliases.json` | 개념의 사용 가능 별칭 → 정규 이름 (vocab_aliases.csv 대신) |
| `vocab_vectors.<임베더>.npz` | `--embed` 로. 벡터 후보(`vocab_suggest.py`)가 vocab.json 옆에서 찾음 |
| `catalog.json` | 표 요약 (`Catalog.table`) |
| `codebooks.json` | 큰 차원의 코드 전체 (`Catalog.has_code`) |
| `concepts.json` · `backlinks.json` | 개념 + 표 → 개념 역링크 (`Catalog.concepts_for`) |
| `manifest.json` | 해시 · 개수 · 검사 결과 |

`settings.okf_use: false` 면 예전대로 동작한다. 그때는 `CSV_INDEX_DIR/vocab.json` 과 `vocab_aliases.csv` 를 쓴다.

## 실행 중 조회 (`backend/rag/okf/catalog.py`)

```python
cat = Catalog.current(settings)            # 빌드가 없으면 None
cat.table("DT_1JC1516")
cat.has_code("DT_1JC1516", "행정구역별(시군구)", code="29010")     # 큰 차원도
cat.concepts_for(["DT_1JC1516"], question, rewritten)
```

`concepts_for` 는 후보 표를 링크한 개념(+ dim_kind 규칙 개념) 중에서, 질문·재작성에 제목·별칭·not·묶인 이름이 나온 것만 돌려준다. 역링크 전부를 붙이지 않는다. 에이전트 컨텍스트와 답변 주의사항에 쓴다.

## 작업 순서

```powershell
python -m backend.rag.okf tables                 # 프로필 → 표·분류 파일 (처음엔 1,092개 생성, 이후엔 바뀐 것만)
python -m backend.rag.okf migrate aliases        # vocab_aliases.csv → 개념 파일 (싱글맘 → 모+미혼자녀 …)
python -m backend.rag.okf migrate learned        # 학습 사전의 승인된 짝 → 개념 별칭 (있으면)
python -m backend.rag.okf lint
python -m backend.rag.okf build --embed hcx      # 파생물 + 벡터 → CURRENT
python -m backend.rag.okf show DT_1JC1516 --text "2020년 세종 싱글맘 가정 식구"
git add storage/okf && git commit                # 표 파일까지 커밋 (개편 때 diff 로 검토)

# 운영 중: 벡터+HCX 가 쌓은 '승인 대기' → 사람 승인 → 다시 빌드
python -m backend.rag.okf pending
python -m backend.rag.okf approve 모자가정 [--value 모+미혼자녀] [--by toast]
python -m backend.rag.okf build
```

## 아직 하지 않은 것

- 검색 인덱스 텍스트(dense 카드·어휘 채널)에 링크된 개념의 별칭을 넣는 일. 지금은 질의 모듈(정규 어휘 사전)만 OKF 를 읽는다.
- 에이전트·모듈 6 에서 `concepts_for` 를 불러 주의사항을 붙이는 연결.
- 교체 전 golden compare 로 성능 확인(떨어지면 교체 막기).
- `configs/colloquial.yaml`(정규식 → 검색어)은 표·코드에 묶이지 않는 검색 확장이라 옮기지 않았다.
