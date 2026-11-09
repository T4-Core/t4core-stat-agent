> **[이동됨]** 이 문서는 예전 폴더(`view_model/` · `Rewritten_fastapi/`) 기준입니다. 코드는 `backend/` 아래로 옮겨졌고 엔드포인트는 통합 Swagger(`uvicorn backend.main:app`, `/api/v1/...`)에 있습니다. 경로 대응표는 저장소 루트의 `MIGRATION.md`.

# 사용자 질문 재작성 모듈 (rewriter)

KOSIS 통계 검색 전에 **사용자 질문을 검색하기 좋은 문장으로 바꾸는 모듈**입니다.
질문을 슬롯(시점·지역·대상·지표 …)으로 나누고, 코드로 검증한 뒤, 다시 문장으로 조립해 **QueryBundle** 로 검색 모듈에 넘깁니다.

```
"2025년 전국에서 혼자 사는 가구는 몇 가구로 집계됐지?"
        ↓
 {
  "original": "2025년 전국에서 혼자 사는 가구는 몇 가구로 집계됐지?",
  "rewritten": "2025년 전국 1인가구 가구수",
  "sub_questions": [],
  "intent": "값 조회",
  "filters": {
   "시점": [
    "2025년"
   ],
   "지역": [
    "전국"
   ],
   "대상": [
    "1인가구"
   ],
   "지표": [
    "가구수"
   ]
  },
  "sub_filters": null
 }
```

노트북 `notebook/user_question_rewrite_v2.ipynb` 의 단계를 `.py` 모듈로 나눈 것입니다.

---

## 1. 처리 흐름(.ipynb 파일에서)

| 단계 | 하는 일 | 방식 | 모듈 |
|:---:|---|:---:|---|
| 2-1 | 일상어 → KOSIS 통계 용어 (`혼자 사는 가구` → `1인가구`) | 코드 | `terms.py` |
| 2-2 | 확실한 값 추출 (연도·지역명·성별·연령 등, 정규식·목록) | 코드 | `extract.py` |
| 2-3 | 뜻을 해석해야 하는 슬롯 채우기 | **HCX 1회** | `slots.py` |
| 2-4 | HCX 결과를 2-2 값과 대조해 검증·보정 | 코드 | `validate.py` |
| 3 | 슬롯 → 검색용 문장 (템플릿) | 코드 | `sentence.py` |
| 4 | 최종 결과 QueryBundle 만들기·저장 | 코드 | `bundle.py` |
| 5 | 단계별 중간 결과 정리 (대시보드용) | 코드 | `trace.py` |

> HCX 는 질문 하나당 **2-3 단계에서 1번만** 호출합니다. 나머지는 모두 코드입니다.

**슬롯 12개 + 의도**

| 구분 | 슬롯 |
|---|---|
| 언제·어디 | 시점, 지역, 전출지, 전입지 |
| 누구 | 국적, 대상, 성별, 연령 |
| 무엇 | 조건, 이동, 지표, 비교축 |
| 의도 | 값 조회 / 추이 / 비교 / 순위 / 구성비 / 증감 / 증감률 / 합계 / 범위 밖 (v3, 9종) |

---

## 2. 폴더 구성

```
├── rewriter/          재작성 모듈 (핵심 코드)
├── scripts/           한 번에 돌리는 실행 스크립트
├── data/              평가 질문 80개 · 정답 참고 · 정답 라벨(개인채점용)
├── outputs/           QueryBundle 결과
├── dashboard/         단계별 중간 결과 대시보드
├── labeling/          정답 라벨 검토 화면(개인 채점용)
├── notebook/          원본 ipynb파일 (기록용 복사본)
├── tests/             테스트 (HCX 호출 없음)
├── kosis_rag_qa.py    베이스 코드 복사본 (수정 금지)
├── requirements.txt
├── .env.example
└── .gitignore
```

### `rewriter/` — 재작성 모듈

| 파일 | 내용 | 주요 이름 |
|---|---|---|
| `__init__.py` | 밖에서 쓰는 함수 모음 | `rewrite_query`, `run_pipeline`, `QueryBundle` |
| `config.py` | 경로, `.env` 읽기, HCX 호출 함수 연결, 연결 확인 | `settings()`, `check_hcx()`, `chat` |
| `terms.py` | 통계 용어 사전 `{대표 용어: [일상어 …]}` 과 찾기 | `TERM_DICT`, `lookup_terms()`, `to_canonical()` |
| `extract.py` | 코드로 확실한 값 뽑기 | `rule_extract()` |
| `slots.py` | HCX 프롬프트·예시, 슬롯 추출 호출 | `SLOT_KEYS`, `SLOT_SYS`, `SLOT_FEW_SHOT`, `call_slots()` |
| `validate.py` | 슬롯 검증·보정 (고친 내역은 log 로 남김) | `validate_slots()` |
| `sentence.py` | 슬롯 → 문장 템플릿 | `slots_to_sentence()`, `build_sentences()` |
| `bundle.py` | QueryBundle 정의·생성·저장·불러오기 | `make_bundle()`, `rewrite_query()`, `save_bundles()`, `load_bundles()` |
| `trace.py` | 대시보드용 중간 결과 만들기·저장 | `build_trace()`, `save_trace()` |

### `scripts/` — 실행 스크립트

| 파일 | 하는 일 | HCX |
|---|---|:---:|
| `run_eval.py` | 평가 질문 80개 전체 재작성 → `outputs/`, `dashboard/` 에 저장 | 질문 수만큼 |
| `make_gold_draft.py` | 지금 결과 + 정답 참고 파일로 정답 라벨 **초안** 생성 → `data/`, `labeling/` | 없음 |

### `data/` — 입력 · 정답

| 파일 | 내용 |
|---|---|
| `kosis_rag_eval_80_queries.csv` | 평가 질문 80개. **재작성 입력으로는 `question` 열만** 씀 (나머지 열은 집계용) |
| `kosis_rag_eval_80_answers_references.csv` | 질문별 정답 참고 (기대 의도·필터·하위 질문, answerability 등) |
| `rewrite_gold_80.draft.json` | 정답 라벨 초안 (`make_gold_draft.py` 가 만듦, 사람이 검토 전) |

### `outputs/` · `dashboard/` · `labeling/` — 결과와 확인 화면

| 파일 | 내용 |
|---|---|
| `outputs/query_bundles.json` | 80개 질문의 QueryBundle |
| `dashboard/rewrite_pipeline_dashboard.html` | 질문을 고르면 2-1 → 4 단계 중간 결과를 차례로 보여 주는 화면 |
| `dashboard/rewrite_trace.json` · `.js` | 대시보드가 읽는 중간 결과 (`.js` 는 서버 없이 열기 위한 같은 내용) |
| `labeling/label_editor.html` | 정답 라벨 검토 화면 |
| `labeling/gold_draft.js` | 검토 화면이 읽는 초안 (`rewrite_gold_80.draft.json` 과 같은 내용) |

> HTML 화면은 모두 **브라우저로 바로 열면** 됩니다 (서버 불필요).

### 그 밖의 파일

| 파일 | 내용 |
|---|---|
| `kosis_rag_qa.py` | 팀 베이스 코드 **복사본**. HCX 호출 함수 `chat()` 를 여기서 가져다 씀. **수정 금지** |
| `notebook/user_question_rewrite_v2.ipynb` | 모듈로 나누기 전 원본 노트북 (기록용) |
| `tests/test_steps.py` | 단계별 함수 테스트 (용어 사전, 코드 추출, 검증, 문장, QueryBundle) |
| `tests/test_against_saved.py` | 저장된 80개 결과(`rewrite_trace.json`)와 같은 결과가 나오는지 확인 |
| `tests/conftest.py` | 테스트 공통 설정 |
| `requirements.txt` | 필요 패키지 |
| `.env.example` | `.env` 에 넣을 키 이름 (값 없음) |
| `.gitignore` | `.env`, 캐시 파일 등 git 제외 목록 |

---

## 3. 준비

```bash
pip install -r requirements.txt        # uv 환경이면: uv pip install -r requirements.txt
```

`.env.example` 을 참고해 `.env` 를 만듭니다. **`.env` 는 git 에 올리지 않습니다.**
이 폴더나 **상위 폴더 어디에 두어도** 가까운 것부터 찾아 읽습니다.

```
HCX_API_KEY=nv-...
HCX_BASE_URL=https://clovastudio.stream.ntruss.com
HCX_MODEL=HCX-007
HCX_APP_TYPE=testapp
```

---

## 4. 사용법

### 코드에서 질문 하나 재작성

```python
from rewriter import rewrite_query

b = rewrite_query("2025년 전국에서 혼자 사는 가구는 몇 가구로 집계됐지?")
b.rewritten   # '2025년 전국 1인가구 가구수'
b.filters     # {'시점': ['2025년'], '지역': ['전국'], '대상': ['1인가구'], '지표': ['가구수']}
```

`today` 인자로 '작년', '최근 5년' 같은 상대 시점의 기준일을 정할 수 있습니다 (비우면 오늘).

**QueryBundle 필드**

| 필드 | 내용 |
|---|---|
| `original` | 사용자 원 질문 |
| `rewritten` | 재작성된 검색용 문장 (슬롯이 모두 비면 원 질문) |
| `sub_questions` | 복합 질문을 나눈 하위 질문 (없으면 `[]`) |
| `intent` | v3 의도 9종 중 하나 (원 질문 의도가 여러 개면 첫 번째. 전체·하위 질문 의도는 `POST /api/v1/rag/query-rewrite` 응답의 `intents`·`sub_intents`) |
| `filters` | 슬롯 (값 있는 것만, 키는 한글 슬롯 이름) |
| `sub_filters` | 하위 질문별 슬롯 (`sub_questions` 와 순서 같음, 없으면 `None`) |

### 평가 질문 80개 전체 재작성 + 대시보드

```bash
python scripts/run_eval.py                         # 80개 전체 (HCX 80회, 동시 4개)
python scripts/run_eval.py --n 5 --today 2026-11-02
```

| 옵션 | 내용 |
|---|---|
| `--n` | 앞에서부터 쓸 질문 수 (기본: 전체) |
| `--today` | 상대 시점 기준일 `YYYY-MM-DD` |
| `--workers` | 동시 HCX 호출 수 (429 오류가 많으면 줄임) |
| `--bundles`, `--trace-dir` | 다른 곳에 저장 (기본은 기존 파일을 **덮어씀**) |

끝나면 `dashboard/rewrite_pipeline_dashboard.html` 을 열어 결과를 봅니다.

---

## 5. 정답 라벨 (평가 기준)

- **모수**: 평가 질문 80개 전체, 기준일 **2026-11-02** 고정
- `answerability` 가 OUT_OF_SCOPE · UNANSWERABLE 인 7개는 정답 = **슬롯이 비어야 함**
- 채점 규칙: 시점·지역·성별·연령 등은 **정확히 일치**, 대상·지표는 **허용 값 중 하나면 맞음** (`A|B` = A 또는 B)

```bash
python scripts/make_gold_draft.py      # 초안 만들기 (HCX 호출 없음)
```

1. `labeling/label_editor.html` 을 엽니다. 왼쪽에서 질문을 고르고, 지금 결과를 보며 정답 칸을 고칩니다
   - 노란 칸 = 지금 결과와 다른 정답, ⚠ = 확인이 필요해 보이는 질문
   - 상태: ○ 검토 전 (회색) · ✓ 완료 (초록) · ⏸ 보류 (보라)
2. 검토 내용은 브라우저에 자동 저장됩니다. 끝나면 **JSON 내려받기** → `data/rewrite_gold_80.json` 으로 저장
3. 이어서 할 때는 같은 브라우저로 열거나 **JSON 불러오기** 로 내려받은 파일을 엽니다

---

## 6. 테스트 (HCX 호출 없음)

```bash
python -m pytest -q
```

모듈을 고쳐서 결과가 일부러 바뀌었다면, `scripts/run_eval.py` 로 `rewrite_trace.json` 을 다시 만든 뒤 테스트합니다.
