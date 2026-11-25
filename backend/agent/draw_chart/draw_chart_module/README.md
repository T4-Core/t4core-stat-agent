# 5번 모듈: 차트 그리기 (draw_chart)

2번 모듈의 차트 계획(**ChartPlan**)과 3번 모듈의 계산 결과(**ChartContent[] · CalcResult[] · displays**)를 받아, 차트를 **Plotly로 그리고** 차트별 파일(json · png)과 질문별 HTML 한 장으로 저장한다.
무엇을 그릴지(차트 유형 · 열 · 값 · 단위 · 제목)는 2·3번 모듈이 이미 정했다. 5번 모듈은 **정해진 규칙대로 그리기만** 하며, LLM을 쓰지 않는다.

```text
2번 chart_plan ─┐
                ├──▶ [5번 차트 그리기] ──▶ DrawResult[] + output/{query_id}/ (json · png · html)
3번 Module3Output ┘
```

## 가장 간단한 사용 (import 1줄 + 함수 1번)

```python
from backend.agent.draw_chart import run_module5, results_table
# from backend.agent.draw_chart.draw_chart_module import run_module5, results_table   # 같은 함수 (패키지에서 직접)

out = run_module5(chart_plan=module2_chart_plan, module3_output=module3_output)

out["results"]                 # DrawResult[] — 차트마다 status · figure · files · warnings (ChartPlan 순서)
out["html"]                    # 질문 HTML 경로 (차트 + 그리지 못한 차트 안내 박스)
out["load_errors"]             # 입력 스키마 오류 (없으면 {})
results_table(out["results"])  # 결과 요약 표 (pandas DataFrame)
```

- `module2_chart_plan`: 2번 모듈 출력 `{"query_id", "charts": [...]}` — 2번 그래프 state 전체를 넘겨도 된다 (`chart_plan` 키를 꺼낸다)
- `module3_output`: 3번 모듈 출력 — `Module3Output`(`run_module3`) · 그 dict · `Module3Trace`(`run_module3_trace`) · 3번 그래프 결과 `{"output", "trace"}` 어느 것이든 된다
- 저장소 최상위 폴더(`t4core-stat-agent/`)에서 실행한다.

입력 4개를 직접 넘길 수도 있다.

```python
out = run_module5(chart_plan=plan, chart_contents=contents, calc_results=calcs, displays=displays)
```

| 인자 | 기본값 | 설명 |
| --- | --- | --- |
| `chart_plan` | — | 2번 출력 |
| `module3_output` | — | 3번 출력 (주면 아래 4개 대신 이것을 쓴다) |
| `chart_contents`, `calc_results`, `displays` | — | 입력을 직접 줄 때 |
| `validation` | — | (선택) 3번 validation — 차트가 없을 때 이유를 찾는 데만 쓴다 |
| `out_dir` | `backend/agent/draw_chart/output/{query_id}/` | 저장 위치 |
| `save` | `True` | `False`면 파일을 쓰지 않고 그리기만 한다 (`out["html"]`은 None) |

---

## 1. 폴더 구조

```text
backend/agent/draw_chart/
├── __init__.py                   # run_module5 · results_table · run_samples 내보내기 (from backend.agent.draw_chart import run_module5)
└── draw_chart_module/            # 5번 모듈
    ├── README.md                 # 이 문서
    ├── requirements.txt          # 필요한 패키지
    ├── __init__.py               # run_module5 · graph · results_table · contract_table 등 내보내기
    ├── __main__.py               # 명령줄 실행 (15종 예시)
    ├── draw_chart_run.py         # ★ 입구: run_module5() 함수 하나로 5번 모듈 실행
    ├── draw_chart_graph.py       # LangGraph 그래프 (load → prepare → Send(draw) × N → save)
    ├── draw_chart_load.py        # ① 입력 로드: 2·3번 출력(여러 모양) / 4개 직접 → 3번 스키마로 파싱
    ├── draw_chart_prepare.py     # ② 차트 하나당 DrawJob 하나 (skipped · failed · 대체 경고 · 출처 링크 · 강조할 계산)
    ├── draw_chart_highlight.py   # 계산 강조: 최대 · 최소 · 순위 · 증감을 차트 위에 표시
    ├── draw_chart_tool.py        # ③ draw_chart(job) — precheck · 렌더러 · decorate (파일을 쓰지 않는 순수 함수)
    ├── draw_chart_renderers.py   # 렌더러 15종 + RENDERERS
    ├── draw_chart_format.py      # 표시 헬퍼 (format_value, 축 이름, 축 범위, y 기준선 …)
    ├── draw_chart_save.py        # ④ 모아서 저장: json · PNG 일괄 · 질문 HTML
    ├── draw_chart_schema.py      # 상태 코드 · 15종 · 유형별 약속 · DrawJob · DrawResult · 경로
    └── draw_chart_samples.py     # 15종 예시 데이터 + run_samples()
```

## 2. 준비

```bash
uv pip install -r backend/agent/draw_chart/draw_chart_module/requirements.txt
```

- 3번 모듈 코드(`backend/schemas/chart.py`, `backend/agent/chart_calculate/specs.py` · `display.py`)를 import해서 쓴다 → 저장소 안에서 실행한다.
- PNG 저장에는 `kaleido`와 **Chrome(또는 Chromium)** 이 필요하다. 없으면 PNG만 저장되지 않고(`files["png"]`에 이유), json · HTML은 정상이다.
- `.env`나 API 키는 필요 없다 (LLM을 쓰지 않는다).

## 3. 명령줄 실행

```bash
python -m backend.agent.draw_chart.draw_chart_module            # 15종 예시 16개 → backend/agent/draw_chart/output/samples/
python -m backend.agent.draw_chart.draw_chart_module samples    # 위와 같음
```

2·3번 출력으로 실행할 때는 명령줄이 아니라 `run_module5`를 부른다.

---

## 4. 흐름 (LangGraph)

```text
START → load → prepare ─┬─ Send(draw) × 차트 수 ─┬→ save → END
                        └──── (차트 없음) ────────┘
```

| 노드 | 파일 | 하는 일 |
| --- | --- | --- |
| load | `draw_chart_load` | 2·3번 출력을 받아 3번 스키마(`ChartContent`, `CalcResult`, `Display`)로 파싱. 틀린 항목은 멈추지 않고 `load_errors`에 남긴다 |
| prepare | `draw_chart_prepare` | ChartPlan 차트 순서대로 차트 하나당 **DrawJob** 하나 (그 차트의 content · 쓰는 displays · 출처 링크) |
| draw | `draw_chart_tool` | `draw_chart(job)` — 차트 하나 그리기. **`Send`로 차트마다 따로(병렬) 실행** (fan-out) |
| save | `draw_chart_save` | 모든 draw가 끝나면 결과를 ChartPlan 순서로 모아 json · PNG(한 번에) · 질문 HTML 저장 (fan-in) |

- 그래프는 `graph`(또는 `build_module5_graph()`)로 꺼낼 수 있다. 다른 그래프에 붙일 때는 노드로 넣는다.
- 입력 스키마 `Module5Input`, 출력 스키마 `Module5Result` (3번 모듈 그래프와 같은 방식).

### draw_chart(job) 안

```text
① precheck   유형별 약속 확인 (아래 6장) → 안 되면 상태와 이유를 남기고 끝
② to_df      columns + rows → DataFrame
③ 렌더러      RENDERERS[chart_type](df, content, displays) → traces · layout
④ decorate   제목(+scope_label) · 한글 폰트 · 범례 · 출처 링크 (공통)
⑤ DrawResult status=drawn, figure   ※ 예외가 나면 failed + 이유
```

---

## 5. 입력 · 출력

### 입력

| 입력 | 출처 | 5번에서 쓰는 곳 |
| --- | --- | --- |
| ChartPlan | 2번 | 차트 순서, 계획 유형(대체 여부 확인), 차트 없음 판단(`chart_type: None` · `measure: "범위 밖"`) |
| ChartContent[] | 3번 | **주 입력.** 최종 차트 유형 · encoding(역할 → 열) · axis · options · rows |
| CalcResult[] | 3번 | 최대 · 최소 · 순위 · 증감 계산을 차트 위에 강조 (`draw_chart_highlight`) |
| displays | 3번 | `{display_ref: 표시 설정}` — 단위 환산 · 소수 자리 · 표시 단위 |
| validation | 3번 (Module3Output 안) | 차트가 없을 때 그 이유 |

- 스키마 기준은 [backend/schemas/chart.py](../../../schemas/chart.py).
- 차트 유형은 **ChartContent.chart_type(최종)** 을 따른다. 2번의 chart_type은 원래 계획이며, 3번에서 대체 차트로 바뀔 수 있다 (→ 경고 `대체됨: line → bar`).

### 출력 `DrawResult`

| 필드 | 내용 |
| --- | --- |
| `chart_id`, `sub_question_ids` | 2번 ChartPlan의 값 |
| `planned_type` → `chart_type` | 계획 유형 → 최종 유형 |
| `status` | 아래 상태 코드 |
| `reason` | 그리지 못한 이유 |
| `figure` | Plotly Figure (drawn일 때) |
| `files` | `{json, png, html}` 저장 경로 (PNG 실패 시 이유) |
| `merged_from` | 겹쳐 그린 차트면 원래 두 chart_id (예: `["c1", "c2"]`), 아니면 `[]` |
| `warnings` | **2번 경고**(`chart_plan.charts[].warnings`: 시점 대체, 요청한 나눔 없음, 차트 없음 이유 …) + 3번 경고(ChartContent) + 5번 경고 (대체됨, 결측값, 지도에 없는 지역 …) |

### 상태 코드

| 상태 | 언제 | HTML에서 |
| --- | --- | --- |
| `drawn` | 정상으로 그림 (결측값이 있으면 끊긴 선으로 그리고 경고만) | 차트 |
| `skipped` | ChartPlan에는 있는데 ChartContent가 없음. 이유를 나눠 적는다: **2번이 차트 없음으로 판단** / **3번 검증 실패**(validation의 원래·대체 차트 이유) | 안내 박스 |
| `failed` | 스키마 오류, 15종 밖 유형, 필수 역할·열 없음, rows 비어 있음, 숫자 역할에 숫자가 아닌 값, 음수 불가 역할에 음수, pyramid group ≠ 2개, 없는 display_ref, 그리는 중 예외 | 안내 박스 |
| `not_implemented` | 렌더러가 등록되지 않은 유형 (지금은 15종 모두 등록되어 있어 보통 생기지 않음) | 안내 박스 |

차트 하나가 실패해도 나머지 차트는 계속 그린다.

---

## 6. 유형별 약속 (입력 계약)

입력 스키마는 15종 모두 **ChartContent 하나**다. 유형마다 다른 것은 encoding 역할 · 행 모양 · options뿐이고, 이를 약속으로 정해 precheck가 확인한다.

- 필수/선택 역할, 행 모양, 음수 불가 역할, y 기준선 → 3번 `SPECS`(`backend/agent/chart_calculate/specs.py`) 그대로
- 숫자여야 하는 역할 → 5번 `NUMERIC_ROLES` / 그 밖의 약속 → `EXTRA_RULES` (`draw_chart_schema.py`)
- 코드에서 표로 보기: `from backend.agent.draw_chart.draw_chart_module import contract_table; contract_table()`

| chart_type | 필수 역할 | 선택 역할 | 행 모양 | 숫자 역할 | 음수 불가 | y 기준선 | 추가 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| line | x, y | series | long | y | | | |
| bar | x, y | series | long | y | | include_zero | |
| stacked_bar | x, y, series | | long | y | y | zero | |
| pyramid | y, group, value | | long | value | value | | group 값 2개 |
| area | x, y | series | long | y | y | zero | |
| pie / donut | label, value | | long | value | value | | |
| bubble | x, y, size | label, series | joined | x, y, size | size | | |
| combo | x, y, y2 | series | long | y, y2 | | | |
| radar | label, series, value | | long | value | | | |
| map | region, value | | long | value | | | |
| heatmap | x, y, value | | long | value | | | |
| treemap | parent, label, value | | long | value | value | | |
| scatter | x, y | label, series | joined | x, y | | | |
| dumbbell | label, start, end | | joined | start, end | | | |

- 행 모양: long = `[분류…, 항목, 값]` (행 하나 = 값 하나) / joined = `[키…, 지표1, 지표2…]` (행 하나 = 점 하나)
- y 기준선: zero = y가 0부터 / include_zero = y 범위에 0 포함 / 빈칸 = 기준 없음

## 7. 렌더러 15종 (`draw_chart_renderers.py`)

| chart_type | 그리는 방법 | 표시 설정을 찾는 곳 |
| --- | --- | --- |
| line | 계열별 선+점, x는 category 축 (연도가 2021.5로 나오지 않게) | axis.y |
| area | line과 같고 선 아래를 0까지 채움 | axis.y |
| bar | 묶음 막대. `options.orientation=horizontal`이면 가로 막대(1위가 위) | axis.y |
| stacked_bar | 같은 x에서 series를 쌓음 | axis.y |
| pyramid | 첫 group은 왼쪽(음수로 그림), 둘째는 오른쪽. 눈금은 절댓값 | (없음 → 원값) |
| pie / donut | 이름+비율 표시. donut은 가운데 `options.center_text` | options.display_ref |
| treemap | parent 아래 label, 부모 크기 = 자식 합계 | options.display_ref |
| radar | 계열별 닫힌 다각형 | options.display_ref |
| map | **시도 타일 지도**(17칸, 칸 색이 값). 타일에 없는 지역(전국, 시군구)은 빼고 경고 | options.display_ref |
| heatmap | x×y 칸 색이 값, 80칸 이하면 칸 안에 값 | (없음 → 원값) |
| combo | `options.series_axis`로 지표별 축(y 왼쪽 / y2 오른쪽), `options.marks`로 막대/선 | axis.y, axis.y2 |
| scatter | x·y 점, 20개 이하면 이름 표시 | axis.x, axis.y |
| bubble | scatter + 원 면적이 size 값 | axis.x, axis.y |
| dumbbell | 범주마다 start·end 두 점을 선으로 연결 | axis.x |

새 유형을 추가할 때는 렌더러 함수 `(df, content, displays) → (traces, layout, warnings)`를 만들어 `RENDERERS`에 등록하고, `draw_chart_schema.NUMERIC_ROLES`에 숫자 역할을 적는다.

### 공통 표시 규칙
- 숫자 표시는 3번의 `format_value`를 쓴다 → 차트 숫자와 답변(6번) 숫자 모양이 같다.
  - hover: 단위 포함 (`192,507건`) / 점·막대 위 값 라벨: 단위 없이 (`192,507`)
  - 축 이름: `label(표시 단위)` (`혼인건수(건)`), 눈금: 천 단위 쉼표 + displays의 소수 자리
- 값 라벨은 계열당 점이 12개 이하일 때만 붙인다. 범례는 trace가 2개 이상일 때만 보인다.
- 출처: 차트 아래 `출처: KOSIS DT_1B8000G` — `record_ids`(`view::101_DT_1B8000G::…`)에서 KOSIS 통계표 링크를 만든다. HTML에서는 클릭할 수 있고, PNG에서는 글자.
  아래 여백 맨 밑(여백 끝에서 4px 위, `yshift`)에 놓아 그림 높이와 관계없이 잘리지 않는다.
- 범주 x축 값이 20개를 넘으면: 시점(line · area · combo)은 2 · 5 · 10 … 칸마다 눈금 하나(12개 이하), 이름(세로 막대)은 -45도로 기울인다.
- 막대가 2개 이하면 범주 축을 4칸 폭으로 넓히고 `bargap` 0.5 → 막대 하나가 화면을 꽉 채우지 않는다.
- combo: 왼쪽 · 오른쪽 축 모두 보기 좋은 간격(1 · 2 · 2.5 · 5 × 10^k)의 눈금 6개 → 두 축의 눈금 · 격자가 같은 높이.
  막대 축은 0을 포함한다. 눈금 글자가 display 자릿수로 겹치면(0.8 · 1.0 · 1.2 → `1`) 구분될 때까지 자릿수를 늘린다.
- 값이 1개뿐인 차트(line · area · combo · bar · stacked_bar의 x, pie · donut · treemap의 label에 값이 있는 것이 1개)는 그리되
  경고 `값이 1개뿐인 차트 (시점 '1995' 하나) — 비교를 보기 어려워 표로 보는 편이 낫다`를 붙인다 (`draw_chart_tool.single_value_warning`).
  요청한 나눔(성별 등)이 표에 없다는 경고는 2번 `chart_plan.charts[].warnings`에서 그대로 온다.
- 계산 강조 (`draw_chart_highlight.py`): 차트와 record 가 겹치는 CalcResult 의 답을 막대 테두리 · 큰 점 + 화살표 주석으로 표시한다
  (line · area · bar · stacked_bar · combo, 차트당 주석 최대 4개, 같은 점의 주석은 한 상자에 여러 줄).

  | 계산 | 표시 |
  | --- | --- |
  | extreme | 그 점(동점 모두): `최댓값 경기도 71,285명` / `최솟값 …` (그림의 값과 비교해 정함) |
  | rank | 1위 점: `1위 경기도 71,285명` |
  | change · growth_rate · diff — 값 하나 | 계산에 쓴 처음 · 끝 점 강조, 끝 점에 `2015→2024 -200,103명 (-45.6%)` (같은 record 의 증감률은 괄호로 합침) |
  | change · growth_rate · diff — 범주별 목록 | 가장 크게 증가한 점 · 가장 크게 감소한 점만 (`가장 크게 증가 경기도 +2,468명`) |

  계산 키(`{'시점': '2024', '시도별': '경기도'}`)로 ChartContent 행 → 그 행의 x · 계열로 점을 찾는다. 못 찾으면 경고 `강조 생략: …`.
  범주 축 주석 위치는 범주 순번으로 준다 ('2024' 를 그대로 주면 Plotly 가 숫자로 읽어 축이 늘어난다).
- 계열 색: 질문 하나 안에서 같은 이름(지표 · 계열)은 어느 차트에서든 같은 색 (`draw_chart_format.color_map` · `apply_colors`).
  prepare 가 ChartPlan 순서대로 처음 나온 이름에 Plotly 기본 색을 차례로 준다 → c1 혼인건수 파랑 · c2 이혼건수 빨강 · 합친 차트(c1+c2)도 파랑 · 빨강.
  합친 차트는 원래 두 차트에서 실제로 그린 색을 그대로 가져온다 (`draw_chart_overlay._color`).
- 표시 자릿수 보정 (`draw_chart_tool.widen_job_displays`): 3번 displays 의 자릿수로 표시하면 서로 다른 값이 같은 숫자가 될 때
  (합계출산율 1.24 · 1.17 → `1`) 구분될 때까지 이 차트에서만 자릿수를 늘린다 (최대 4자리) + 경고 `표시 자릿수를 0자리 → 2자리로 늘림 …`.
  축(역할)마다 따로 본다: combo 의 y(출생아수) · y2(합계출산율)가 같은 display_ref 를 쓰면 늘려야 하는 축만 `{ref}@{역할}` 표시 설정을 새로 만든다.
  3번 displays 원본과 받은 DrawJob 은 바꾸지 않는다 (draw_chart 는 job 사본에서 작업) → 답변(6번) · 다른 차트 · 겹쳐 그리기에 영향 없음.
  계산 강조 주석 중 차트 점과 같은 값(극값 · 순위 · 범주별 목록)은 차트의 표시 설정을 써서 막대 라벨과 숫자 모양이 같다.
- 스타일: Plotly 기본 템플릿 + 맑은 고딕.

---

## 7-1. 겹쳐 그리기 (`draw_chart_overlay.py`)

2번 `chart_plan.overlays`에 표시된 차트들을 그림 하나로 합친 차트를 더한다 (원래 차트는 그대로).

| mode | 그림 |
| --- | --- |
| `combo` | 큰 값 막대(왼쪽 축 y) + 작은 값 선(오른쪽 축 y2). 어느 차트가 y 인지는 `overlays[].axes` (차트 2개) |
| `lines` | line 하나에 선 N개 |
| `bars` | 묶음 막대 하나 (막대 N개) |
| `scatter` | [NEW 11-25] c1 값 = x, c2 값 = y, 범주(시도 등) = 점 이름 (`axes`) |
| `bubble` | [NEW 11-25] c1 = x, c2 = y, c3 = 원 크기. 그림 오른쪽 위에 "원 크기: …" |
| `radar` | [NEW 11-25] 차트(지표)마다 축 하나, 범주마다 다각형 하나 (단위가 같은 지표만) |

- 결과: `chart_id` = `overlay_id` (예: `c1+c2`, `c1+c2+c3`), `merged_from` = `["c1", "c2", …]`, `planned_type` = `"overlay"`.
  [CHANGED 11-25] 결과 목록의 **맨 앞**에 놓인다 (답변 화면의 첫 차트). 이전: 두 차트 뒤
- combo · lines · bars 는 차트가 모두 `drawn`이고 **x 값이 정확히 같을 때만** 합친다. 아니면 합치지 않고 첫 차트 경고에 "c1+c2 겹쳐 그리기 생략: …"을 남긴다.
- scatter · bubble · radar 는 **범주 이름으로 짝짓는다**. 지역 열이면 검색 쪽 지역 이름 표준화(`backend.rag.ingestion.normalize.std_geo_name`, 읽기만)로 맞춘다
  ('강원도' ↔ '강원특별자치도'). 한 차트에 표준 이름이 같은 범주가 둘이면 이름이 표준 이름과 같은 행을 쓴다 ('세종특별자치시' · '세종시').
  모든 차트에 값이 있는 범주만 그리고 뺀 범주는 경고로 남긴다. 짝지은 범주가 산점도 5개 · 버블 3개보다 적으면 합치지 않는다.
- 원래 차트의 축 범위(min·max)는 그 차트 값 기준이라 합친 차트에서는 지운다.
- 3번 모듈은 이 표시를 모른다 (3번은 지금처럼 하위질문마다 차트를 계산한다).

## 8. 저장 (`draw_chart_save.py`)

```text
{out_dir}/                    기본: backend/agent/draw_chart/output/{query_id}/
├── {chart_id}.json           drawn 차트의 Plotly figure
├── {chart_id}.png            drawn 차트 (kaleido로 한 번에 저장)
└── {query_id}.html           질문 하나 = 한 장. 차트 + 그리지 못한 차트 자리에 안내 박스
```

- HTML은 plotly.js를 CDN에서 받는다(`PLOTLYJS = "cdn"`) → 열 때 인터넷이 필요하다. 오프라인용이면 `True`로 바꾼다 (파일 안에 넣음, 장당 약 4.8MB).

## 9. 예시 데이터 (`draw_chart_samples.py`)

3번이 만드는 모양(long · joined 행, encoding, axis, options)으로 15종 + 가로 막대(순위) 예시 16개를 그린다. 값은 그리기 확인용 예시이며 실제 통계가 아니다.

```python
from backend.agent.draw_chart import run_samples

out = run_samples(out_dir="원하는/폴더")   # 기본: backend/agent/draw_chart/output/samples/
```

---

## 10. 주의 · 알려진 한계

| 항목 | 내용 |
| --- | --- |
| 저장 위치 | 기본 저장 위치 `backend/agent/draw_chart/output/`은 .gitignore에 없다 → 결과 파일이 git에 섞이지 않게 `out_dir`을 지정하거나 .gitignore에 추가한다 |
| PNG | kaleido + Chrome 필요. 리눅스 서버에서는 한글 폰트가 없으면 PNG의 한글이 깨질 수 있다 (HTML은 괜찮음) |
| 노트북 표시 | `fig.show()`는 `nbformat` 패키지가 필요하다. 없으면 `display(HTML(fig.to_html(full_html=False, include_plotlyjs="cdn")))`로 표시한다 |
| 지도 | 지역 경계(GeoJSON)가 저장소에 없어 시도 타일 지도로 그린다. 시군구는 경계 파일이 생기면 추가 |
| 표시 설정이 없는 유형 | 3번이 pyramid · heatmap에 display_ref를 넣지 않아 단위 없이 원값으로 표시된다 |
| 3번 표시 자릿수 | 3번 displays 의 자릿수가 값에 비해 적으면(합계출산율 digits 0) 5번이 차트에서만 늘린다. 답변(6번) 숫자는 3번 displays 그대로라 차트와 자릿수가 다를 수 있다 |
| 여러 계열의 축 이름 | 계열이 여럿이면 3번이 축 label을 `값`으로 준다 → `값(건)`처럼 나온다 |
| CalcResult | extreme · rank · change · growth_rate · diff 만 강조한다. 겹쳐 그린 차트(c1+c2)에는 강조를 넣지 않는다. cagr · share 등은 아직 표시하지 않음 |
| 3번 스키마 | `backend/schemas/chart.py`가 바뀌면 5번도 함께 맞춰야 한다 |
