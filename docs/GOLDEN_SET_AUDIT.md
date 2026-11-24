# 골든셋 정답 표시 검토 — 무엇이 틀렸고 어떻게 고치나

> 2026-11-23 hard heldout(34문항) compare 결과(`hard_okf2`)와 생성 코드(`synthetic_gold_pipeline/`)를 보고 정리했다.

## 1. 먼저: MRR 이 떨어진 것이 아니다

같은 heldout 34문항끼리 비교하면 오히려 조금 올랐다. 이전 hard 실행의 수치는 dev 를 포함한 144문항이라 비교 대상이 다르다.

| 실행 | 문항 | O mrr | P mrr | hit@10 |
|---|---|---|---|---|
| hard_C (heldout 만 다시 셈) | 34 | 0.785 | 0.608 | 1.0 |
| hard_okf2 (okf on) | 34 | 0.790 | 0.627 | 1.0 |
| hard_C 전체 (dev 포함) | 144 | 0.653 (전체) | | 0.958 |

hit@10 이 1.0 인데 mrr 이 0.7 대인 것은, 정답이 **2~8위**에 있는 문항이 많다는 뜻이다. 그 문항들을 하나씩 보면 대부분 검색이 틀린 것이 아니라 **정답 표시가 좁거나 틀린** 경우다.

## 2. 정답 표시가 틀리는 네 가지 (heldout 의 2위 이하 14문항)

| 유형 | 예 | 왜 생기나 (생성 코드) | 문항 |
|---|---|---|---|
| **총괄 표** | 1985년 안동군 '주택 총계' → 정답 '주택의편익시설별 주택'(1985년 한 해 표). 1위 '총조사 주택총괄'(1975~2010)에도 같은 값이 있음 | 정답은 '생성에 쓴 표 하나'. `alt_gold` 는 같은 값을 다른 표에서 찾지만 **항목 이름**으로 후보를 고른다. 정답 항목이 '계' 뿐이면 '주택수' 와 이름이 달라 못 찾음 (`--loose-items` 는 기본 꺼짐) | 8 (그중 4는 아래 모집단과 겹침) |
| **모집단(15세 이상)** | '해당 시점의 인구 천 명당' → 정답 인구 표가 '…인구(15세이상)'. 질문은 전체 인구를 물음 | 생성기 검사(`reverse_qa_agent.validate`)는 **분류(dim)** 의 조건만 질문에 있는지 본다. '(15세이상)' 은 표 이름에만 있어 검사를 지나침 | 5 |
| **성별로 나뉜 표** | '진안군의 한국 국적을 취득한 자' → 정답 '…기타(남)'. 1위 '…기타(계)' 가 질문에 맞음 | 위와 같음 — '(남)' 이 표 이름에만 있음 | 2 |
| **P 가 표를 가르는 말을 잃음** | O '당해연도 혼인 비율' → P '결혼 비율'. 검색은 '누적 혼인 비율' 1위 (용어 사전이 '결혼 비율' 을 '누적 혼인' 으로 바꿈) | 검수(`quality_verifier`)의 `paraphrase_equivalence` 가 형제 표와 구분되는지를 모르고 봄 | 3 |

총괄 표와 모집단 유형은 한 레코드(주택 수 ÷ 인구 천 명당) 안에 같이 들어 있는 경우가 많다. 2위 이하 14문항 모두 표 파일로 보면 이 네 가지 중 하나 이상에 해당한다 (총괄 표·형제 표는 값 확인 전이라 추정).

## 3. 고친 것

### 3-1. 이미 있는 셋 — 다시 만들지 않고 검토 (HCX 없음)

```powershell
# ① 같은 값 대체 정답 다시 (정답 항목이 '계' 뿐이면 같은 조사의 총괄 표를 값으로 확인 — 자동)
python -m backend.rag.search.tuning.alt_gold --golden synthetic_gold_pipeline\outputs\datasets\synthetic_gold_dataset.jsonl --restart

# ② 정답 표시 검토 → 골든셋 옆 gold_audit.jsonl · gold_audit.md
python -m backend.rag.search.tuning.gold_audit --golden synthetic_gold_pipeline\outputs\datasets\synthetic_gold_dataset.jsonl

# ③ 같은 질의 분석으로 다시 재기 (HCX 안 부름 — --from-run 이 날짜·캐시를 이어받음)
python -m backend.rag.search.tuning.compare --from-run hard_okf2 --audit synthetic_gold_pipeline\outputs\datasets\gold_audit.jsonl --okf off on --name hard_audit
```

`gold_audit` 이 보는 것 (`backend/rag/search/tuning/gold_audit.py`)

| 검사 | 기준 | 처리 |
|---|---|---|
| `SEX` | 정답 표가 '(남)·(여)' 인데 질문에 성별 말이 없음 | 같은 무리의 (계) 표를 대체 정답으로 — **기본 반영** |
| `UNIVERSE` | 정답 표가 '(N세이상)' 인데 질문에 'N세' 가 없음 | 그 변형을 평가에서 뺌 — **기본 반영** (맞는 표를 골라도 값이 달라 대체 정답을 정할 수 없음) |
| `P_DRIFT` | O 에 있던 '형제 표와 가르는 주제 말'이 P 에 없고, P 가 형제 쪽 말도 직접 쓰지 않음 | 형제 표를 P 의 대체 정답으로 — **검토 제안**: jsonl 의 `"human": {"P": "accept"}` 를 적어야 반영 |

- 사람 판단은 `"human": {"O"|"P": "accept" | "exclude" | "strict"}` 에 적는다. 다시 돌려도 남는다.
- `compare --audit` 는 **엄격·완화 지표를 바꾸지 않고** '검토 반영' 지표를 따로 보여 준다 (report.md '검토 반영' 절, per_query 의 `rank_aud` · `audit_flags` · `audit_excluded`).
- `P_DRIFT` 를 자동으로 쓰지 않는 이유: 낱말이 없다고 뜻이 같은 것은 아니다. '결혼 후 아이를 낳은 비율' 에는 '출산' 이 없지만 출산 비율을 묻는다.

미리 본 효과 (업로드된 `hard_okf2` per_query 의 순위·상위 5개로 어림, 실제 값은 ③ 으로)

| heldout | 완화 (지금) | 검토 반영 (기본) | + P_DRIFT accept |
|---|---|---|---|
| O hit@1 · mrr (n) | 0.765 · 0.829 (17) | 0.867 · 0.897 (15) | 같음 |
| P hit@1 · mrr (n) | 0.471 · 0.640 (17) | 0.643 · 0.774 (14) | 0.714 · 0.821 (14) |

①(총괄 표)은 이 어림에 들어 있지 않다. ① 까지 반영하면 주택 문항의 순위도 바뀔 수 있다.

### 3-2. 앞으로 만들 셋 — 생성 때 막기

| 고친 곳 | 내용 |
|---|---|
| `reverse_qa_agent.table_qualifiers` · `condition_labels` | 표 이름의 '(남)·(여)' 와 '(N세이상)' 을 **필수 조건**에 넣음 → O·P 둘 다 없으면 생성 검사에서 떨어짐 (기존 '필수 분류 조건 누락' 과 같은 길) |
| `reverse_qa_agent.sibling_hints` → `facts.distinguish_from` | 같은 조사에서 이름이 거의 같은 형제 표와 '정답 표에만 있는 말'을 생성기·검수기에 보여 줌 |
| 생성 프롬프트 규칙 9·11 | 표 이름의 성별·모집단을 두 질문에 쓰기 · P 도 형제 표와 가르는 말을 일상어로라도 남기기 |
| 검수 `paraphrase_equivalence` | 형제 표와 가르는 말을 모두 잃으면 false · 표 이름의 성별·모집단이 P 에서 빠져도 false |
| `alt_gold` | 정답 항목이 '계' 뿐이면 같은 조사·같은 좌표·같은 값의 총괄 표를 자동으로 대체 정답 (`why: total_item`) |

새로 만든 셋도 `alt_gold` → `gold_audit` → `compare --audit` 순서로 확인한다.

## 4. 그 밖에 고친 것

- `compare --from-run` 이 이전 실행의 `--today` 를 이어받는다. 질의 분석 캐시 키에 날짜가 들어 있어, 다른 날 다시 쓰면 캐시를 못 찾고 HCX 를 다시 불렀다.

## 5. 아직 남은 것

- '총괄 표' 유형은 값으로만 확인한다(`alt_gold`, CSV 값 사전 필요). 이 저장소의 시험 환경에는 원본 CSV 가 없어 실제 셋으로는 돌려 보지 못했다.
- `P_DRIFT` 제안은 사람이 본다. 레코드가 많아지면 HCX 로 'P 가 형제 표도 똑같이 묻는가' 를 판정하게 할 수 있다(assist 와 같은 방식).
- 평가셋을 키우는 방향은 사람이 쓴 일상어 질문(손으로 만든 `tests/retrieval_golden.jsonl` 형식)이 가장 믿을 만하다.
