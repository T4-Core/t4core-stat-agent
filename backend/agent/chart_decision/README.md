# 2번 모듈: 차트 유형 판단 (chart_decision)

질의 변환 결과(**QueryBundle**)와 검색 결과(**Views**)를 받아, 하위질문마다 **어떤 차트로(chart_type), 어떤 값을(measure)** 그릴지 정한다.
수치 계산은 하지 않는다. 계산은 3번 모듈, 차트 그리기는 5번 모듈이 한다.

```text
QueryBundle + Views ──▶ [2번 차트 유형 판단] ──▶ chart_plan + filtered_views ──▶ 3번 계산 ──▶ 5번 차트 생성
```

## 가장 간단한 사용 (import 1줄 + 함수 1번)

다른 모듈 개발자는 **import 한 줄과 함수 한 번**으로 2번 모듈을 실행할 수 있다.
그래프를 직접 만들거나 세부 단계를 하나씩 부를 필요가 없다. 함수 하나가 입력 정리부터 최종 결과(`chart_plan`)까지 모두 실행한다.

```python
from backend.agent.chart_decision import run_chart_decision

out = run_chart_decision("QueryBundle.json", "Views.json")   # 파일 경로 또는 dict
out["chart_plan"]       # 최종 결과 → 3번 모듈로
out["filtered_views"]   # 걸러진 View → 3번 모듈로
out["errors"]           # 문제가 없으면 []
```

터미널에서 파일 하나로 실행:

```bash
python -m backend.agent.chart_decision.chart_decision_module QueryBundle.json Views.json      # chart_plan JSON 출력
python -m backend.agent.chart_decision.chart_decision_module QueryBundle.json Views.json --out result.json --steps --no-llm
```

- 저장소 최상위 폴더(`t4core-stat-agent/`)에서 실행한다 (다른 곳이면 2-3 참고).
- 준비(패키지 설치, `.env`)는 2장, 입력·출력 모양은 4·5장을 본다.

---

## 1. 폴더 구조

```text
backend/agent/chart_decision/
├── README.md                          # 이 문서
├── requirements.txt                   # 필요한 패키지
├── __init__.py                        # run_chart_decision 내보내기 (from backend.agent.chart_decision import run_chart_decision)
├── state.py                           # Generator 그래프 State
├── graph.py                           # Generator 그래프 (2번 서브그래프 + 3번·5번 자리)
├── studio_input.json                  # LangGraph Studio 입력 예시
├── test_module_chart_decision.ipynb   # 모듈 실행 확인용 노트북
└── chart_decision_module/             # 2번 모듈
    ├── __init__.py                    # run_chart_decision, decide_charts 등 함수 내보내기
    ├── __main__.py                    # python -m backend.agent.chart_decision.chart_decision_module 으로 실행할 때
    ├── chart_type_run.py              # ★ 입구: run_chart_decision() 함수 하나로 2번 모듈 실행
    ├── chart_type_graph.py            # 2번 모듈 LangGraph 서브그래프 (build_chart_decision_graph)
    ├── chart_type_nodes.py            # 서브그래프 노드 (세부 단계 하나 = 노드 하나)
    ├── chart_type_state.py            # 서브그래프 State·입력·출력
    ├── chart_type_pipeline.py         # 같은 일을 함수 하나로 (decide_charts)
    ├── chart_type_loader.py           # 입력 읽기·정리
    ├── chart_type_matcher.py          # ① 하위질문 ↔ View 짝짓기
    ├── chart_type_view_filter.py      # ①-1 View 필터링
    ├── chart_type_measure.py          # ② measure 판단 (규칙 → LLM)
    ├── chart_type_profiler.py         # ③ 데이터 모양 파악
    ├── chart_type_chart_picker.py     # ④⑤ chart_type 소거법, requirements
    ├── chart_type_reason.py           # ⑥ reason
    ├── chart_type_rules.py            # 규칙·사전 (키워드, 차트 후보, 조건)
    └── chart_type_llm.py              # HCX 호출
```

---

## 2. 준비

### 2-1. 패키지 설치

저장소 최상위 폴더에서 실행한다.

```bash
uv pip install -r backend/agent/chart_decision/requirements.txt     # uv를 쓰는 경우 (프로젝트 .venv)
pip install -r backend/agent/chart_decision/requirements.txt        # pip가 있는 경우
```

| 패키지 | 버전 | 용도 |
| --- | --- | --- |
| langgraph | 1.2.20 | 그래프 실행 |
| requests | 2.34.2 | HCX 호출 |
| python-dotenv | 1.2.4 | `.env` 읽기 |

확인한 파이썬 버전: 3.12

### 2-2. `.env` (HCX 키)

measure를 규칙으로 정하지 못한 질문만 HCX(LLM)를 부른다. 저장소 최상위 `.env`에 아래 값이 있어야 한다.
`.env`는 실행 위치에서 위쪽으로, 그다음 모듈 파일 위치에서 위쪽으로 찾는다.

```text
HCX_API_KEY=nv-...
HCX_BASE_URL=https://clovastudio.stream.ntruss.com
HCX_MODEL=HCX-007
HCX_APP_TYPE=testapp        # 없으면 testapp
```

- `.env`가 없어도 멈추지 않는다. LLM이 필요한 질문만 measure가 `None`으로 남고 `measure_info`에 실패 이유가 적힌다.

### 2-3. import 경로

모듈 안은 **상대 import**를 쓴다. 그래서 `backend.agent.chart_decision` **패키지 경로로** 불러야 한다.

- 저장소 최상위 폴더(`t4core-stat-agent/`)가 import 경로에 있어야 한다. 그 폴더에서 실행하면 따로 할 일이 없다.
- 다른 곳에서 실행하면 저장소 최상위 폴더를 경로에 추가한다.

```python
import sys
sys.path.insert(0, r"C:\dev\t4core-stat-agent")   # 저장소 최상위 폴더 (backend 폴더의 "부모")
```

- py 파일 하나를 경로로 직접 실행(`python backend/agent/chart_decision/graph.py`)하면 상대 import 때문에 동작하지 않는다. 항상 `-m 패키지경로`나 import로 실행한다.

---

## 3. 사용법

아래 예시는 저장소 최상위 폴더에서, `QueryBundle.json`, `Views.json` 파일을 읽어 실행한다고 가정한다.

### 3-0. 입구 함수 `run_chart_decision` (가장 간단)

```python
from backend.agent.chart_decision import run_chart_decision

out = run_chart_decision("QueryBundle.json", "Views.json")                  # 파일 경로
# query_bundle, view_input: 앞 모듈에서 받은 값 또는 json.load로 읽은 값
out = run_chart_decision(query_bundle, view_input)                          # dict (리스트로 감싼 QueryBundle도 됨)
out = run_chart_decision(query_bundle, view_input, use_llm=False)           # LLM 없이
out = run_chart_decision(query_bundle, view_input, show_steps=True)         # 노드별 바뀐 값도 함께
for s in out["steps"]:
    print(s["node"], list(s["update"]))
```

| 인자 | 기본값 | 내용 |
| --- | --- | --- |
| `query_bundle` | (필수) | 질의 변환 결과. dict, `[dict]` 리스트, 또는 JSON 파일 경로 |
| `view_input` | (필수) | 검색 결과 Views. dict 또는 JSON 파일 경로 |
| `use_llm` | `True` | `False`면 LLM을 부르지 않음 (규칙으로 못 정한 measure는 `None`) |
| `show_steps` | `False` | `True`면 `out["steps"]`에 노드별 바뀐 값 목록 (`{"node", "update"}`) |

- 반환: `{"chart_plan", "filtered_views", "errors"}` (+ `show_steps=True`면 `"steps"`)
- 처음 부를 때 그래프를 한 번 만들고, 그 뒤로는 다시 쓴다.
- 안에서 3-1의 LangGraph 서브그래프를 그대로 실행한다. 결과는 3-1과 같다.

### 3-1. LangGraph 서브그래프로 실행

```python
import json
from backend.agent.chart_decision.chart_decision_module.chart_type_graph import build_chart_decision_graph

with open("QueryBundle.json", encoding="utf-8") as f:
    query_bundle = json.load(f)
with open("Views.json", encoding="utf-8") as f:
    view_input = json.load(f)

chart_decision = build_chart_decision_graph()          # 2번 모듈 (컴파일된 LangGraph)
out = chart_decision.invoke({"query_bundle": query_bundle, "view_input": view_input})

chart_plan = out["chart_plan"]            # 최종 결과 → 3번 모듈로
filtered_views = out["filtered_views"]    # 하위질문 조건으로 걸러진 View → 3번 모듈로
errors = out["errors"]                    # 건너뛴 하위질문·입력 문제 (없으면 [])

print(json.dumps(chart_plan, ensure_ascii=False, indent=2))
```

- `invoke` 한 번이면 세부 단계(노드)가 모두 차례로 실행된다.
  `load_input → match → filter → measure_rule → (measure_llm) → profile → chart_select → (chart_llm) → requirements → reason`
- 괄호 안 노드는 규칙으로 정하지 못한 경우에만 지나간다.

### 3-2. 노드마다 중간 값 보기

`invoke`는 최종 값만 돌려준다. 노드별 중간 값은 `stream`으로 본다.

```python
for step in chart_decision.stream({"query_bundle": query_bundle, "view_input": view_input},
                                  stream_mode="updates"):
    for node, update in step.items():
        print(f"[{node}] 바뀐 키: {list(update)}")
        if node == "measure_rule":
            for m in update["matches"]:
                print("   ", m["chart_id"], m["measure"], m["measure_info"]["basis"])
        if node == "chart_select":
            for c in update["charts"]:
                print("   ", c["chart_id"], c["chart_type"], "fallback:", c["fallback_charts"])
                for row in c["log"]:                       # 후보 차트별 남음/소거와 이유
                    print("      ", row["후보"], row["결과"], row["이유"])
```

| 노드 | 바뀌는 키 | 볼 수 있는 것 |
| --- | --- | --- |
| load_input | query_bundle, view_input | 정리된 입력 |
| match | matches | 하위질문 ↔ View 짝 (chart_id, unit_id) |
| filter | matches, filtered_views | 걸러진 표, `filter_info` (지표 열·단위) |
| measure_rule / measure_llm | matches | measure, 확신 여부, 규칙 근거, LLM 근거·시간 |
| profile | matches | 데이터 모양 (시점 수, 범주·계열, 단위 등) |
| chart_select / chart_llm | charts | chart_type, fallback, 후보별 소거 기록 |
| requirements | charts | requirements |
| reason | charts, chart_plan | reason, 최종 chart_plan |

### 3-3. LLM 없이 실행

LLM을 부르지 않으려면 입력에 `use_llm: False`를 넣는다. 규칙으로 정하지 못한 measure는 `None`으로 남는다.

```python
out = chart_decision.invoke({"query_bundle": query_bundle, "view_input": view_input, "use_llm": False})
```

### 3-4. 함수 하나로 실행 (LangGraph 없이)

같은 결과를 함수 하나로 얻을 수도 있다. 이때는 입력 정리를 직접 해야 한다.

```python
from backend.agent.chart_decision.chart_decision_module import decide_charts, slim_query_bundle, slim_view_input

chart_plan, filtered_views, errors = decide_charts(slim_query_bundle(query_bundle),
                                                   slim_view_input(view_input))
```

### 3-5. 다른 그래프에 노드로 붙이기

컴파일된 2번 서브그래프를 노드 하나로 넣는다. 바깥 State에 같은 이름의 키(`query_bundle`, `view_input`, `chart_plan`, `filtered_views`, `errors`)가 있어야 한다.

```python
import operator
from typing import Annotated, Optional, TypedDict
from langgraph.graph import END, START, StateGraph
from backend.agent.chart_decision.chart_decision_module.chart_type_graph import build_chart_decision_graph

class MyState(TypedDict, total=False):
    query_bundle: dict
    view_input: dict
    chart_plan: Optional[dict]
    filtered_views: list
    errors: Annotated[list, operator.add]       # 2번 모듈과 같은 방식으로 이어 붙임

def calculation_node(state):                    # 3번 모듈 자리 (예시)
    print("3번 모듈이 받는 차트 수:", len(state["chart_plan"]["charts"]))
    return {}

builder = StateGraph(MyState)
builder.add_node("chart_decision", build_chart_decision_graph())   # 2번 모듈 = 노드 하나
builder.add_node("calculation", calculation_node)
builder.add_edge(START, "chart_decision")
builder.add_edge("chart_decision", "calculation")
builder.add_edge("calculation", END)
my_graph = builder.compile()

result = my_graph.invoke({"query_bundle": query_bundle, "view_input": view_input})
```

- 이 모양을 그대로 만든 Generator 그래프가 `backend/agent/chart_decision/graph.py`에 있다 (`from backend.agent.chart_decision.graph import build_generator_graph`). 3번·5번 노드는 아직 자리만 있다.

---

## 4. 입력

| 키 | 내용 |
| --- | --- |
| `query_bundle` | 질의 변환 결과 |
| `view_input` | 검색 결과 (unit별 View) |
| `use_llm` | (선택) `False`면 LLM을 부르지 않음. 기본 `True` |

`load_input` 노드가 입력 모양을 맞춰 주므로 아래처럼 들어와도 된다.

| 들어오는 모양 | 처리 |
| --- | --- |
| QueryBundle이 리스트 `[ {...} ]` | 첫 번째 질문을 쓴다. 2개 이상이면 `errors`에 경고를 남긴다 |
| `intent`가 문자열 `"값 조회"` | 리스트 `["값 조회"]`로 바꾼다 |
| `sub_questions`가 없음, `sub_filters`가 `null` | **main unit 하나**를 `rewritten`·`filters`와 짝지어 차트 1개를 만든다. 이 차트의 `sub_question_ids`는 `"main"`이 아니라 `["<query_id>-1"]` (모듈 3의 하위질문 ID 형식과 같음) |
| 하위질문 문장이 View의 unit 문장과 다름 | unit_id 순서(`<query_id>-1`, `-2` …)로 짝짓는다 |
| Views 원본 (candidates, rank 2~3 포함) | candidates를 빼고 unit마다 rank 1 View만 쓴다 |
| 파일 경로 문자열 | 파일을 읽어서 쓴다 |
| 둘 중 하나만 들어옴 | 멈추지 않고 `errors`에 "입력에 ○○ 없음"을 남기고 끝난다 |

---

## 5. 출력

```python
out = {
    "chart_plan": {
        "query_id": "27077dec",
        "charts": [
            {
                "chart_id": "c1",                                       # 차트 이름표 (짝지은 순서대로)
                "sub_question_ids": ["27077dec-1"],                     # 이 차트가 답하는 하위질문 (combo면 2개)
                "view_ids": ["view::101_DT_1B8000G::Y::27077dec-1-1::trend"],   # 쓸 View (filtered_views와 짝)
                "chart_type": "line",                                   # 차트 종류. 그릴 차트가 없으면 None (표만)
                "requirements": ["time_axis_required", "min_points_3"], # 데이터가 지켜야 할 조건 (검사는 3번)
                "fallback_charts": ["bar"],                             # 조건 실패 시 차례로 시도할 차트
                "measure": "raw",                                       # 값 그대로 / 가공 방법 (11개 + "범위 밖")
                "reason": "혼인건수 연도별 추이",                       # 고른 이유 (QA·로그용)
            },
            # ...
        ],
    },
    "filtered_views": [...],   # 하위질문 조건으로 걸러진 View. 각각 filter_info(지표 열, 지표, 단위, 슬롯→열)가 붙음
    "errors": [],              # 짝 없음·필터 0행·입력 문제 등
}
```

- **3번 모듈에서 짝짓는 법:** `charts[i]["view_ids"]` ↔ `filtered_views[j]["record"]["id"]`
- **measure 값:** `raw`, `change`, `growth_rate`, `cagr`, `index`, `share`, `diff`, `ratio`, `rank`, `extreme`, `aggregate`, `범위 밖`
- `chart_type`이 `None`인 차트도 `charts`에 들어간다. 3번 계산 후 표만 보여준다.

---

## 6. LangGraph Studio로 보기 (선택)

1. `langgraph-cli[inmem]`을 설치한다. (`requirements.txt`의 주석 줄)
2. 저장소 최상위 폴더에 `langgraph.json`을 만든다. **상대 import라서 파일 경로가 아니라 패키지 경로로 적는다.**
   ```json
   {
     "dependencies": ["."],
     "graphs": {
       "chart_decision": "backend.agent.chart_decision.chart_decision_module.chart_type_graph:graph",
       "generator": "backend.agent.chart_decision.graph:graph"
     }
   }
   ```
3. 그 폴더에서 서버를 켠다. 윈도우는 `PYTHONUTF8=1`이 꼭 필요하다 (없으면 `UnicodeDecodeError`).
   ```bash
   PYTHONUTF8=1 langgraph dev          # Git Bash
   $env:PYTHONUTF8=1; langgraph dev    # PowerShell
   ```
4. 터미널에 나온 Studio 주소를 열고, 그래프를 고른 뒤 Input에 `studio_input.json` 내용(`{"query_bundle": {...}, "view_input": {...}}`)을 넣고 Submit.

---

## 7. 알아둘 점

- 입력을 비우거나 `{"scenario": "이름"}`으로 실행하면 예시 데이터(`input_data/`)를 찾는다. 원래 개발 폴더 기준이라 이 위치에서는 찾지 못한다. 실제 사용에서는 `query_bundle`, `view_input`을 직접 넣는다.
- 차트 후보 순서·조건 같은 규칙은 `chart_decision_module/chart_type_rules.py`에 모여 있다. 규칙을 바꿀 때는 이 파일만 고친다.
- 모든 문자열 파일은 UTF-8로 읽고 쓴다.
