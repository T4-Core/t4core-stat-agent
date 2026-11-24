# OKF 개념을 답변 주의사항으로 — 설계안 (모듈 6 · 에이전트 연결)

> **이 문서는 설계안이다. 이 패치는 Agent 모듈(`backend/agent/**`) 코드를 바꾸지 않는다.**
> 검색 쪽 OKF(별칭 → 값 채널)는 이미 동작한다. 이 문서는 같은 개념 파일을 **답변 문장의 주의사항**에도 쓰는 방법을 정한다.

## 1. 왜

검색이 맞는 표를 찾아도, 사용자의 말과 표의 정의가 다르면 답이 틀린 것처럼 읽힌다.

| 사용자 말 | 찾은 표·코드 | 사용자가 알아야 할 것 |
|---|---|---|
| 싱글맘 | 세대구성별 '모+미혼자녀' | 사별·이혼한 어머니도 들어 있다. '미혼모'와 같은 뜻이 아니다 |
| 미혼모가 낳은 아이 | '미혼모의 자녀' | KOSIS 주석: 18세 이하 자녀(내국인)의 친모이며 혼인상태가 미혼인 부모 |
| 결혼 후 아이를 낳은 비율 | '누적 혼인 경험자 중 출산 비율' | 산식: 당해연도까지 혼인 및 출산 경험자 / 당해연도까지 혼인 경험자 × 100 |
| 노인 | 연령 65세 이상 | 규칙 개념 — '노인'을 65세 이상으로 보고 계산했다 |

개념 파일에는 이 정보(정의 · `not` · 별칭 · `calc`)가 이미 있다. `drafts → assist → verify`로 늘어나는 중이다.

## 2. 지금 코드 (근거)

| 무엇 | 어디 | 비고 |
|---|---|---|
| 후보 표 → 걸린 개념 | `backend/rag/okf/catalog.py` `Catalog.concepts_for(tbl_ids, *texts)` | 질문·재작성에 제목·별칭·not·묶인 이름이 나온 개념. `{id, title, description, matched, not, calc, trust, binds}` |
| ViewSet 만들기 | `backend/rag/view/viewset.py` `build_viewset` | RAG 쪽 끝. `ViewSet` 은 `extra="allow"` |
| ViewSet → 모듈 2·3·6 | `backend/agent/modules.py` `run_modules` | `Module6Request(query_bundle, records, calc_results, …)` |
| 주의사항 | `backend/agent/answer_compose/caveats.py` `build_caveats` | 출처 4가지: `plan_warning` · `view_note` · `calc_note` · `view_missing` |
| 주의사항의 쓰임 | `write.py` 프롬프트 `[주의사항]` · `template.py` `※ …` 줄 · `placeholder.py` 허용 숫자 | 주의사항 문장 속 숫자는 답변에 써도 되는 숫자가 됨 |

## 3. 제안 — 흐름

```
build_viewset (RAG)                     run_modules (에이전트)                 모듈 6
  선택된 records 의 tbl_id               ViewSet.concepts 를 그대로              build_caveats
  + 원 질문 · 재작성                ─▶   Module6Request.concept_notes 로   ─▶    source="concept" 주의사항
  → Catalog.concepts_for                 (OKF 를 import 하지 않음)                (최대 2개 · 코드가 만든 문장)
  → ViewSet.concepts = [ConceptNote]
```

- **OKF 를 읽는 곳은 RAG 한 곳**으로 둔다. 에이전트는 받은 목록만 옮긴다. 에이전트가 OKF·빌드 해시를 알 필요가 없다.
- 개념 빌드가 바뀌어도 에이전트 코드는 그대로다(검색과 같은 `CURRENT` 를 씀).

## 4. 제안 — 스키마 (추가만, 기존 칸은 그대로)

```python
# backend/schemas/view.py (RAG)
class ConceptNote(BaseModel):
    concept_id: str                      # "/concepts/household/single-mother-with-children.md"
    title: str
    kind: Literal["not", "alias", "definition", "calc"]
    text: str                            # 코드가 만든 한 문장 (아래 5)
    tbl_ids: list[str]                   # 이 개념이 묶인 표 중 선택된 records 의 표
    trust: Literal["human-reviewed", "machine-confirmed"]
    matched: dict[str, str] = {}         # {"별칭": "싱글맘"} — 왜 걸렸는지 (QA·화면용)

class ViewSet(BaseModel):
    ...
    concepts: list[ConceptNote] = []     # 새 칸

# backend/schemas/answer.py (모듈 6)
class Module6Request(BaseModel):
    ...
    concept_notes: list[ConceptNote] = Field(default_factory=list, description="OKF 개념 주의사항 (ViewSet.concepts)")

class Caveat(BaseModel):
    source: Literal["view_note", "calc_note", "view_missing", "plan_warning", "concept"]
```

## 5. 무엇을 · 어떤 문장으로

문장은 **코드가 만든다**(HCX 아님). 개념 파일에 적힌 사실만 쓴다.

| kind | 언제 | 문장 (예) |
|---|---|---|
| `not` | 질문에 개념의 `not` 낱말이 나왔고, 그 개념의 표가 선택됨 | 질문의 '미혼모'는 표의 '모+미혼자녀'와 같은 뜻이 아닙니다 (사별·이혼한 어머니도 포함). |
| `alias` | 질문의 별칭으로 이 개념이 걸림 | 질문의 '싱글맘'을 표의 '모+미혼자녀'로 보고 찾았습니다. |
| `definition` | 개념 정의에 KOSIS 주석의 공식 설명이 있음 (assist 의 '공식 설명') | '미혼모의 자녀'는 18세 이하 자녀(내국인)의 친모이며 혼인상태가 미혼인 부모의 자녀입니다 (KOSIS 주석). |
| `calc` | 개념의 `calc` 가 있음 | '누적 혼인 경험자 중 출산 비율' = 당해연도까지 혼인 및 출산 경험자 ÷ 혼인 경험자 × 100. |

고르는 규칙
- **쓰는 개념**: `status` 가 stable 이고 `trust` 가 `human-reviewed` 또는 `machine-confirmed` 인 것만. draft · unverified 는 쓰지 않는다.
- **순서**: `not` → `alias` → `definition` → `calc`. 합쳐서 **최대 2개**. 같은 개념에서는 하나만.
- **중복**: 이미 있는 주의사항(못 맞춘 조건 등)과 같은 낱말을 다루면 뺀다.
- **표가 실제로 쓰였을 때만**: `used_record_ids`(계산이 쓴 View)의 표에 묶인 개념만. 검색 후보에만 있던 표의 개념은 쓰지 않는다.

## 6. 숫자 검사와의 관계

`placeholder.check` 는 주의사항 문장 속 숫자를 허용 숫자로 본다.
- 정의·산식의 숫자('18세 이하', '× 100')가 답변에 나와도 오류가 아니게 된다. 의도한 동작이다.
- 대신 주의사항 문장은 개념 파일에서만 만들고, 값(통계 수치)은 넣지 않는다. 통계 수치는 늘 `CalcResult` 에서만 나온다.

## 7. 끄고 켜기 · 단계

| 단계 | 설정 (`configs/pipeline.yaml`) | 동작 |
|---|---|---|
| 0 (지금) | — | 검색만 OKF 를 씀 |
| 1 기록 | `okf_caveats: log` | `ViewSet.concepts` 를 채우고 `notes` 에만 남김. 답변은 그대로. 걸리는 빈도·문장을 본다 |
| 2 화면 | `okf_caveats: on` | 모듈 6 주의사항에 들어감 (프롬프트 `[주의사항]` · 템플릿 `※`) |

1단계에서 볼 것
- 걸린 개념 수 / 질문 (너무 많이 걸리면 별칭이 넓다는 신호 — 개념을 고침).
- `not` 이 걸린 질문 목록 — 사용자가 정말 다른 뜻으로 물은 것인지.

## 8. 평가

- **검색 지표로는 안 보인다**(표 순위가 바뀌지 않음). 답변 쪽 점검표로 본다.
- 손으로 쓴 질문 10~20개: `not` 이 걸려야 하는 질문(미혼모 · 15세 이상 · 노인), 걸리면 안 되는 질문(별칭과 비슷하지만 다른 말).
- 확인: ① 주의사항이 붙었는가 ② 문장이 개념 파일과 같은가 ③ 답변 숫자 검사(`placeholder.check`)를 그대로 통과하는가 ④ 모듈 7(QA)이 주의사항을 오류로 보지 않는가.

## 9. 위험 · 열린 질문

- **틀린 개념이 답변에까지 나간다.** 검색 별칭은 순위만 흔들지만, 주의사항은 사용자에게 문장으로 보인다.
  그래서 `trust` 가 사람 확인 또는 기계 확인인 개념만 쓰고, 1단계(기록)부터 시작한다.
- `matched` 가 '묶인 이름'(표의 코드 이름 자체)인 경우: 사용자가 공식 용어로 물은 것이라 `alias` 문장은 군더더기다 → `not` · `definition` · `calc` 만.
- 하위 질문이 여럿일 때 어느 하위 질문의 개념인지: 처음에는 질문 전체에 한 번만 붙인다.
- Streamlit 화면에서 주의사항 출처 `concept` 를 다르게 보일지(아이콘·접기)는 화면 담당과 정한다.

## 10. 구현할 때 고칠 곳 (참고)

| 파일 | 할 일 |
|---|---|
| `backend/schemas/view.py` | `ConceptNote` · `ViewSet.concepts` |
| `backend/rag/view/viewset.py` | 선택된 records 의 `source.tbl_id` + `vb.original` · `vb.rewritten` → `Catalog.current(s).concepts_for(…)` → 5 의 규칙으로 `ConceptNote` |
| `backend/agent/modules.py` | `Module6Request(…, concept_notes=vs.get("concepts") or [])` 한 줄 |
| `backend/schemas/answer.py` | `Module6Request.concept_notes` · `Caveat.source` 에 `concept` |
| `backend/agent/answer_compose/caveats.py` | `concept_notes` 중 `used_record_ids` 의 표에 묶인 것 → `add("concept", concept_id, text)` |
| 시험 | `tests/` 의 모듈 6 가짜 `chat` 시험에 `concept_notes` 한 경우 · 끈 경우 |
