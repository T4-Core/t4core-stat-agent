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
| `catalog.json` | 표 요약 (`Catalog.table`). `definitions` = 표 파일 '# 주석' 중 정의·집계 대상·산식 줄 (최대 3, 빌드 2부터) |
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

## 검색 연결 (`backend/rag/search/okf_terms.py`)

검색기는 만들어질 때 지금 빌드(`CURRENT`)의 개념을 읽는다. 승인된 별칭과, 그 개념이 표에 묶인 정보를 쓴다. `dim_kind` 규칙 개념은 모든 연령 표에 해당해 신호가 되지 않으므로 뺀다.

- **값 채널 (기본 켜짐):** 별칭을 그 표의 값 표현으로 넣는다(가중치 `search.yaml okf.value_weight`, 기본 0.9).
  - 질문에 '싱글맘'이 나오면 '모+미혼자녀' 코드가 있는 표들이 점수를 받는다.
  - 정규 이름('모+미혼자녀')도 '연결된 값'으로 친다. 그래서 그 표는 '안 쓰는 분류' 감점을 받지 않는다.
  - 드문 표현이라, 같은 조사의 다른 표는 기존 조건 누락 규칙(`cond_miss`)으로 뒤로 간다.
- **dense 문서 `okf` (선택):** 표 설명문 끝에 `일상어: 싱글맘, 한부모 엄마 (모+미혼자녀)` 줄을 붙인다.
  - 별칭이 없는 표는 설명문 그대로라 임베딩 캐시를 다시 쓴다.
  - 켜는 법: `search.yaml dense_docs: okf`, 또는 compare `--dense-docs rule okf`.
- **빌드가 바뀌면** 검색기 캐시 키(`get_search`)가 달라져서 새로 만들어진다.
- **끄기:**
  - `search.yaml okf.enabled: false` — 검색만 끈다.
  - `pipeline.yaml okf_use: false` — 사전과 검색 모두 끈다.

```powershell
# 같은 질의 분석으로 OKF 켬·끔 비교 (첫 값이 기준 → report.md 'dense 비교' 에 질문별 득실·부호 검정)
python -m backend.rag.search.tuning.compare --golden <셋> --alt <alt> --dense hcx --okf off on --name okf_ab
# dense 문서까지
python -m backend.rag.search.tuning.compare --golden <셋> --dense hcx --dense-docs rule okf --okf on --name okf_dense
```

`--okf` 는 검색 쪽만 켜고 끈다. 질의 분석(정규 어휘 사전의 별칭 → 조건 보충)은 두 구성이 같은 캐시를 쓴다.

테스트는 내 PC 의 실제 빌드를 읽지 않는다(`tests/conftest.py` 가 빈 폴더로 바꿈).

### LLM 재정렬에 OKF 정보 (`search.yaml llm_rerank.okf`, 기본 꺼짐)

RRF 는 순위만 합쳐서, 이미 위에 있는 표들 사이의 순서(형제 표·같은 값의 표)를 별칭으로는 못 바꾼다.
그래서 재정렬하는 LLM 에게 표 이름만으로는 안 보이는 근거를 카드에 붙여 준다 (`okf_terms.rerank_notes`).

- **정의:** `catalog.json definitions` — KOSIS 주석 중 개념·집계 대상·산식.
  예: 당해연도 혼인 비율 `초혼 경험자 / 인구 x 100` ↔ 누적 혼인 비율, 장기국제이동 `1년 초과` ↔ 국제이동 `90일 초과`.
  골든셋에서 뽑은 것이 아니라서, 이 효과는 dev·heldout 모두에서 볼 수 있다.
- **개념:** 질문에 제목·별칭·`not`·묶인 이름이 나온 개념(초안·폐기 제외) 중 그 후보 표에 묶인 것.
  별칭이면 `질문의 'X' = 이 개념`, `not` 이면 `주의: … 같은 뜻이 아님`. 개념은 dev 에서 캐냈으므로 이 효과는 heldout 에서만 본다.
- **`keep_if_unsure`:** LLM 이 `sure: false`(근거 없음)라 하면 원래 순서를 둔다. 값이 같은 표들 사이에서 근거 없이 순서만 바뀌는 것을 막는다.

```powershell
# 빌드 2 (정의 포함)로 다시 빌드 — 해시가 바뀜
python -m backend.rag.okf build --gate <compare 실행>
# 질의 분석·검색 캐시를 이어받아 재정렬 방법만 나란히 (HCX: 질문 × 방법 수 만큼 호출 — 먼저 --limit 20)
python -m backend.rag.search.tuning.compare --from-run <실행> --split heldout --audit <gold_audit.jsonl> --okf on --llm-variants base okf okf-keep --name rr_okf
```

report.md '방법 비교' 절: `search+llm+okf` 는 `search` 와 `search+llm` 둘 다를 기준으로 득실·부호 검정을 낸다 (OKF 가 더한 몫만 보려면 후자).
재정렬 결과는 실행 폴더 `llm_rerank_cache.jsonl` 에 남고, `--from-run` 이 이어받아 같은 질문·후보·카드면 다시 부르지 않는다.

### 구분 줄 · 추론 (`search.yaml llm_rerank.traits` · `llm_rerank.thinking`, 기본 꺼짐)

11/24 실험(hard 144 · easy 170)에서 OKF 줄이 바꾼 질문은 hard 7개(좋아짐 4·나빠짐 3) · easy 6개(3·3)뿐이었다.
남은 1위 실패는 대부분 2~5위의 '비슷한 표'(총괄표↔상세표, 비율 표↔건수 표, 같은 말 다른 집계 기준, (계)/(남)/(여) 형제)라서
그 차이를 카드에 직접 적는다.

- **구분 줄 (`traits: true`, `search/traits.py`):** 후보끼리 다른 성질만 `구분:` 한 줄로 — 총괄표 · 비율 직접 제공(항목 이름) ·
  성별 분할/분류 · 연령 분류 · 주기. 모든 후보가 같은 성질은 쓰지 않는다.
  - `형제 차이:` 같은 형제 무리가 후보에 둘 이상이면 제목에서 그 표에만 있는 말 (`이 표만 '여'`, `'2008~2015'`).
  - `집계 기준:` OKF 빌드의 표 정의. 표에 정의가 없으면 같은 조사의 다른 표 2개 이상이 공유하는 정의(`조사 공통`).
  - 표 메타데이터에서 만들므로(골든셋을 보지 않음) dev·heldout 모두로 평가해도 된다.
- **추론 (`thinking: low|medium|high`):** HCX-007 추론을 켠다. HCX 문서상 추론은 구조화 출력과 함께 못 쓴다 →
  JSON 형식을 프롬프트에 적고 응답 글에서 뽑는다 (`backend/core/llm.py chat(thinking=…)`).
  - `maxCompletionTokens` 에 추론 토큰이 포함된다 → effort 별 문서 기본값(5120 · 10240 · 20480)으로 올림 (`think_tokens` 로 바꿈).
  - 시간 제한 180초, 시간 초과 재시도 1회 (일반 호출은 60초 · 8회). 실패·빈 답이면 추론 없이 한 번 더 (메모 `추론 실패(…) → 일반`).
  - 추론 글은 `llm_rerank_cache.jsonl` 의 `why` 에 남는다 — 왜 그 순서인지 사람이 볼 수 있다 (사용자에게 그대로 보이지 말 것).
  - 질의 분석·골든셋 생성은 구조화 출력이 필요해서 그대로 추론 없이 둔다.
- **keep 버그 수정:** `keep_if_unsure` 에서 LLM 이 불확실이라 하면 엔진이 형제 규칙을 다시 돌리지 않는다.
  전에는 top_n 뒤에 끼운 형제가 이 단계에서 정답 자리를 차지해, keep 이 search 보다 나빠지는 질문이 있었다 (hard 5 · easy 5).

```powershell
# 비싼 추론은 먼저 '1위를 놓쳤지만 10위 안' 질문만 (이 부분집합의 지표는 전체 지표로 읽지 않는다)
python -m backend.rag.search.tuning.compare --from-run <실행> --only-missed <실행> --llm-variants base traits traits+think --name rr_think_missed
# 전체: 조각을 + 로 이음 (base · okf · traits · keep · think), 추론 수준은 --llm-thinking
python -m backend.rag.search.tuning.compare --from-run <실행> --llm-variants base traits okf+traits okf+traits+keep --name rr_traits
```

## 개념 초안 모으기 (`python -m backend.rag.okf drafts`)

compare 결과에서 "일상어(P)라서 못 찾은" 문항을 골라 개념 초안을 만든다. 같은 레코드의 O(공식 용어) 질문과 비교해서 고른다.

```powershell
python -m backend.rag.okf drafts --runs storage\runs\search_compare\<hard 실행> storage\runs\search_compare\<easy 실행>
#   → storage/runs/okf_drafts/<시각>/drafts.md (사람이 읽음) · drafts.json
python -m backend.rag.okf drafts --runs … --write          # 개념마다 concepts/_inbox/draft-*.md (status: draft) + 표에서 정의
python -m backend.rag.okf drafts --runs … --write --hcx    # + HCX 제안 (정의 다듬기 · 별칭 판정 · 헷갈리는 말)
python -m backend.rag.okf assist [경로 …] [--no-hcx]        # 이미 있는 _inbox 초안에 같은 것 (경로 없으면 전부)
python -m backend.rag.okf verify /concepts/_inbox/draft-….md --to population/birth [--alias 표현 …]
#   고친 뒤 → stable + 승인 + concepts/population/birth.md 로 옮김
python -m backend.rag.okf lint ; python -m backend.rag.okf build
```

**1. 문항 고르기**
- P 가 1위를 놓쳤고(대체 정답 포함 순위) O 보다 순위가 나쁜 레코드만 고른다.
- 둘 다 못 찾은 문항은 어휘 문제가 아니라서 뺀다.
- 기본은 dev 레코드만 쓴다(`--split`). heldout 으로 평가하기 위해서다.

**2. 분류** — O 에만 있는 내용어(Kiwi 형태소)가 정답 표의 무엇과 맞는지 본다.

- 코드·항목 이름이 O 에 통째로 있으면 그것만 묶는다. '미혼모의 자녀' 가 O 에 있으면 '자녀' 가 같은 '미혼부의 자녀' 는 묶지 않는다.
- 이름의 일부만 맞으면 코드 짝으로 보지 않는다. '거주지' 하나로 '1년 전 거주지_전국' 을 묶지 않고, 분류·표 이름 쪽으로 넘어간다.

| 결과 | 기준 | 다음 일 |
|---|---|---|
| 어휘 | 코드·항목 1~2개와 맞음 (표 30개 이하에만 있는 이름) | 개념 초안 |
| 어휘(표) | 드문 표 이름 형태소 (표 5개 이하) | 표 단위 개념 초안 |
| 용어 | 여러 코드에 두루 맞거나 흔한 이름 ('주택' · '여자') | `configs/colloquial.yaml` 후보 |
| 표를 못 정함 의심 | 지역이 아닌 분류 이름('체류기간별' · '연령별')만 O 에 있음 | 골든셋 검토 — P 로 바꾸며 표를 정하는 말이 빠짐 |
| 기타 | 아무것도 안 맞음 | 시점·분기·조건 등 다른 문제 |

**3. 일상어 후보**
- P 에만 있는 내용어 1~2개로 만든다.
- 다음은 뺀다.
  - 흔한 말: P 질문 8% 넘게 나오는 형태소 + 기본 목록
  - 지역 이름
  - O 나 정답 표 이름에 이미 있는 말
  - 성별·합계 표현('남성' · '남녀' · '나라') 과 '살' · '거주'
  - `configs/colloquial.yaml` 이 많은 표에 있는 용어로만 바꾸는 말 ('남성' → 남자)
- 동사로 끝나면 어절 끝까지 넣는다 ('아이를 낳' → '아이를 낳은').
- 같은 폴더에 `analysis_cache.jsonl` 이 있으면 C 모드 `[어휘 후보]` 기록도 쓴다. 벡터 후보가 짝의 이름과 같으면 "벡터 후보 일치" 로 표시한다.
- `colloquial.yaml` 이 같은 말을 짝과 같은 쪽으로 바꾸면 `colloquial → 출생`, 다른 말로도 바꾸면 `⚠ colloquial 은 '출생' 로도 바꿈` 으로 표시한다.
  '낳은 아이 → 미혼모의 자녀' 처럼 경고가 붙은 별칭은 다른 표의 질문까지 끌어갈 수 있으니 더 좁은 말('미혼모가 낳은 아이')로 고친다.

**묶을 표 넓히기** — 코드·항목 짝은 같은 이름의 항목(또는 같은 분류의 같은 코드)이 있는 모든 표에 묶는다.
- 예: '출생' 항목이 있는 표 9개.
- 정답 표에만 묶으면 검색 점수가 골든셋 정답 표에만 붙어 골든셋에 맞춘 개념이 된다.
- 표 30개를 넘으면 넓히지 않는다(용어 쪽). 표 이름 짝은 그 표만. `--gold-only` 로 끈다.
- 보고서의 '묶일 표' 는 `정답 표 외 N개 (같은 이름)` 로 보인다.

**4. 쓰기 (`--write`)**
- 맞는 개념이 이미 있으면 그 파일에 미승인 별칭(`by: draft:compare`, 근거 레코드)을 더한다.
- 없으면 `_inbox/draft-<표>-<코드>.md` (status: draft) 를 만든다.
- 다시 돌리면 아직 draft 인 초안에 새로 찾은 묶을 표를 더한다(본문 '# 표' 목록도). 승인된 개념은 건드리지 않는다.
- 승인 전에는 아무 데도 쓰이지 않는다.
- 사람이 틀린 후보를 지우고 정의·경계를 채운 뒤 `verify --to <영역>/<영어-이름>` 하면 stable + 승인 + 제자리로 옮겨진다.
  그다음 build 하면 사전과 검색에 들어간다. 이미 있는 이름이면 옮기지 않는다.
- `verify` 결과와 `lint` 는 승인된 개념에 초안 흔적이 남으면 경고한다.
  - 정의가 아직 '(초안) …'
  - `_inbox` 에 남아 있음
  - 승인 안 된 초안 별칭이 남음

**5. 정의 채우기 (`okf/assist.py`)** — 사람이 정의를 처음부터 쓰지 않게 한다. 아무것도 승인하지 않는다.

① 사실 정의 (늘 · 비용 없음)
- 묶인 표 파일에서만 만든다: 조사 · 항목/코드/표 · 단위 · 같은 이름이 있는 표 수 · 나누는 분류.
  예: `인구동향조사 통계표의 항목 '출생' (단위 명). 같은 이름이 있는 표 9개 (…). 나누는 분류: 모의 연령, 성, ….`
- KOSIS 주석 중 이 개념을 설명하는 줄을 '공식 설명' 으로 붙인다(최대 3줄, 표 ID 와 함께).
  - 이름의 낱말이 있고 단서('개념' · '정의' · '말함' · '의미' · '대상' · '집계' · '포함' · '제외')나 산식(`… / … x 100`)이 있는 줄.
  - 표 전체 개념은 이름이 없어도 되지만 강한 단서나 산식이 있어야 한다.
  - 공표 · 잠정 · 명칭변경 같은 행정 줄은 뺀다.
- description · 본문 '# 정의' · '# 헷갈리는 말' · '# 표' 를 다시 쓴다. 아직 draft 이고, 정의를 사람이 고치지 않았을 때만
  (`x-t4-draft.text` 와 같거나 '(초안)' 으로 시작). '# 헷갈리는 말' 에 사람이 본문으로만 적은 줄이 있으면 그대로 둔다.

② HCX 보조 (`--hcx` · `assist`) — 결과는 모두 제안이다.
- 정의를 한두 문장으로 다듬는다. 주어진 사실·주석만 쓰게 하고, 근거에 없는 숫자가 나오면 버리고 ① 을 쓴다.
  본문에는 다듬은 문장 아래 '근거(표 정보)' 와 '공식 설명' 이 남는다.
- 별칭마다 예문(P 질문) 속 뜻을 판정해 별칭의 `review` 에 적는다: `same` · `narrow` · `broad`(다른 항목·표도 가리킴) · `wrong`.
  - broad·wrong 이면 예문 안에 그대로 있는 더 정확한 표현을 새 미승인 별칭으로 더한다('낳은 아이' → '미혼모가 낳은 아이').
- 헷갈리는 말: 같은 표의 다른 항목·코드와 별칭이 `colloquial.yaml` 로 바뀌는 말 중에서만 골라 `not` 에 더한다.
- HCX 가 안 되면 ① 까지만 한다. 판정이 끝난 초안은 다시 부르지 않는다(`--force` 로 다시).

`verify` 는 `--alias` 로 고르지 않으면 판정이 broad·wrong 인 별칭을 빼고 승인한다. 뺀 것은 결과의 `skipped_aliases` 에 나온다.
맞다고 보면 `--alias` 로 직접 고른다. 사람이 하는 일은 파일을 훑어 틀린 줄을 지우고 `verify --to …` 하는 것뿐이다.

binds 는 코드·항목 말고 표 전체(`{table, name: 표 이름}`)에도 걸 수 있다(검사는 표 이름이 바뀌었는지만 본다).

## 빌드 전 검사 (`python -m backend.rag.okf build --gate <compare 실행>`)

새 빌드를 `CURRENT` 로 바꾸기 전에, 이전 compare 실행의 질문으로 **지금 빌드와 새 빌드를 나란히** 검색해 본다 (`okf/gate.py`).

```powershell
python -m backend.rag.okf build --gate hard_okf2                   # 그 실행의 골든셋·split·alt·audit·날짜·질의 분석 캐시
python -m backend.rag.okf build --gate hard_okf2 --gate-max-loss 1  # hit@5 순손실 1문항까지 허용
```

- 질의 분석은 그 실행의 캐시만 쓴다. HCX 를 부르지 않고, 캐시에 없는 질문은 건너뛴다.
- 빌드만 바꿔 검색한다(`OKF_BUILD_OVERRIDE`). 검사하는 동안에도 `CURRENT` 는 그대로다.
- 같은 질문끼리 hit@5(alt 가 있으면 완화 hit@5)와 mrr 를 비교한다.
  - **불합격**: 잃은 질문 수 − 얻은 질문 수 > `--gate-max-loss`(기본 0), 또는 mrr 하락 > `--gate-mrr-drop`(기본 0.01).
  - 불합격이면 새 빌드 폴더는 남고 `CURRENT` 는 그대로다. 결과는 `<빌드>/gate.json` 에 남는다.
  - 잃은 질문마다 그 질문에 걸린 **새 별칭**을 보여 준다 — 고칠 개념을 바로 찾게.
  - 그래도 쓰려면 `python -m backend.rag.okf use <해시>`.
- 한계: 질의 분석이 캐시라서, 별칭이 질의 분석(어휘 사전 `aliases.json`)에 주는 영향은 재지 않는다. 검색 쪽(값 채널 · dense 문서)만 잰다.

## 아직 하지 않은 것

- 에이전트와 모듈 6 에서 `concepts_for` 를 불러 주의사항을 붙이는 연결 — 설계안: [OKF_CAVEATS_DESIGN.md](OKF_CAVEATS_DESIGN.md).
- `configs/colloquial.yaml`(정규식 → 검색어)은 표·코드에 묶이지 않는 검색 확장이라 옮기지 않았다. drafts 의 '용어 후보'가 그 파일의 후보다.
