"""답변 프롬프트·출력 스키마 (질의 재작성 프롬프트는 backend/rag/query_analyzer/slots.py)"""
from typing import get_args

from backend.schemas.chart import ChartType

ANSWER_SCHEMA = {"type": "object", "properties": {
    "answer": {"type": "string"},
    "summary": {"type": "string"},
    "key_points": {"type": "array", "items": {"type": "string"}},
    "used_ids": {"type": "array", "items": {"type": "string"}},
    "chart_id": {"type": "string"},
    "insufficient": {"type": "boolean"}},
    "required": ["answer", "summary", "key_points", "used_ids", "chart_id", "insufficient"]}
ANSWER_SYS = """너는 한국 공식통계(KOSIS)를 근거로 답하는 통계 안내원이다.
규칙:
1. 반드시 [자료]에 있는 숫자만 쓴다. 계산(차이·증감률)이 필요하면 [자료]의 숫자로 계산하고 '약'을 붙인다. 없는 숫자를 만들지 않는다.
2. 질문에 맞는 자료가 없거나 조건(연도·지역)이 다르면 insufficient=true 로 하고, 가장 가까운 자료로 무엇을 알 수 있는지 설명한다.
   자료의 지역·시점이 질문과 다르면 그 값을 질문 대상의 값처럼 쓰지 않는다 (예: 전국 값을 서울 값으로 쓰지 않는다).
   '질문 조건 적용' 데이터가 있으면 그 값을 우선 사용한다. 지표 이름이 질문과 다르면(예: 주민등록인구 ↔ 주민등록연앙인구) 차이를 밝힌다.
3. 기준 시점과 단위를 항상 밝힌다. 주의사항이 있으면 한 문장으로 덧붙인다.
4. 문체는 '~입니다'체. answer 는 3~6문장, summary 는 1문장, key_points 는 핵심 수치 2~4개.
5. used_ids 에 실제로 근거로 쓴 자료 id, chart_id 에 그래프로 보여줄 자료 id 1개를 넣는다.
JSON만 출력한다."""


# ─── [NEW] 모듈 3 계산 계획 (backend/agent/chart_calculate/decide.py) ───
# HCX 는 '무엇을 계산할지'만 정한다. 숫자 계산과 나머지 계획 필드는 코드가 채운다 (chart/planner.py).
# select 는 원래 {열: [값]} 사전이지만, 구조화 출력 스키마에 '키가 정해지지 않은 객체'를 쓸 수 있는지 확인하지 못해
# conditions = [{column, values}] 목록으로 받고 decide.py 가 사전으로 바꾼다. 쓰지 않는 칸은 "" · [] · 0 으로 받는다.
# 고정된 값만 오는 칸(op, role, scope, agg)은 enum 으로 묶는다. HCX 가 enum 을 거절하면(HTTP 400) core.llm.chat 이
# 스키마 없이 다시 부르고 JSON 을 파싱한다. 그래도 남는 실수는 planner.normalize 가 바로잡는다.
CHART_OPS = ["raw", "change", "growth_rate", "cagr", "index", "share", "diff", "ratio", "rank", "extreme", "aggregate",
             "combine"]
ANSWER_ROLES = ["value", "part", "a", "b", "term"]
SERIES_ROLES = ["y", "y2", "x", "size", "start", "end"]
_CONDITIONS = {"type": "array", "items": {"type": "object", "properties": {
    "column": {"type": "string"}, "values": {"type": "array", "items": {"type": "string"}}},
    "required": ["column", "values"]}}


def _pick(roles):
    return {"type": "object", "properties": {
        "role": {"type": "string", "enum": roles}, "record_id": {"type": "string"}, "item": {"type": "string"},
        "conditions": _CONDITIONS, "sign": {"type": "string", "enum": ["", "+", "-"]}, "unit": {"type": "string"}},
        "required": ["role", "record_id", "item", "conditions", "sign", "unit"]}


_ARGS = {
    "from": {"type": "string"}, "to": {"type": "string"}, "base": {"type": "string"},
    "agg": {"type": "string", "enum": ["", "sum", "mean"]}, "top_n": {"type": "integer"},
    "kind": {"type": "string", "enum": ["", "max", "min"]}, "order": {"type": "string", "enum": ["", "desc", "asc"]},
    "join_on": {"type": "array", "items": {"type": "string"}},
    "denominator": {"type": "object", "properties": {
        "scope": {"type": "string", "enum": ["", "question", "selected"]}, "basis": {"type": "string"},
        "label": {"type": "string"}, "record_id": {"type": "string"}, "item": {"type": "string"},
        "conditions": _CONDITIONS},
        "required": ["scope", "basis", "label", "record_id", "item", "conditions"]}}
CHART_TYPES = list(get_args(ChartType))
# [CHANGED 11-25 4단계] charts 에 chart_type (세트의 '차트 후보' 중 질문 의도에 맞는 하나. "" = 1순위 그대로). planner.choose_chart 가 검사한다
CHART_PLAN_SCHEMA = {"type": "object", "properties": {
    "charts": {"type": "array", "items": {"type": "object", "properties": {
        "chart_id": {"type": "string"}, "chart_type": {"type": "string", "enum": ["", *CHART_TYPES]},
        "title": {"type": "string"}, "record_id": {"type": "string"}, "conditions": _CONDITIONS,
        "series": {"type": "array", "items": _pick(SERIES_ROLES)}, **_ARGS},
        "required": ["chart_id", "chart_type", "title", "record_id", "conditions", "series", *_ARGS]}},
    "answers": {"type": "array", "items": {"type": "object", "properties": {
        "sub_question_id": {"type": "string"}, "op": {"type": "string", "enum": CHART_OPS},
        "operands": {"type": "array", "items": _pick(ANSWER_ROLES)}, **_ARGS},
        "required": ["sub_question_id", "op", "operands", *_ARGS]}}},
    "required": ["charts", "answers"]}

# [CHANGED 11-11] 테스트 화면 첫 실행(2026-11-10)에서 HCX 가 change 피연산자를 a·b 로 쪼개고, join_on 을 피연산자로 적고,
# 피연산자 시점을 한 해로 좁혀 계산이 null 이 됐다 → 연산별 피연산자 표, 기간 규칙, 하지 말 것, 예시를 추가.
# 이전 프롬프트는 git 이력에 없다 (이 브랜치에서 처음 만든 뒤 커밋 전에 고침)
# [CHANGED 11-11] 규칙 3·5 와 예시: 실제 View 는 '항목' 열이 표 단위 고정값이고 지표는 분류 열(종류별 등)에 있다
#   이전 규칙 3: item 에는 '항목' 열(없으면 항목 이름이 든 열)의 값 하나를 적는다
# [CHANGED 11-11] 피연산자 unit: 표가 단위를 표 단위로만 줘서('명 가임여자 1명당 명') 항목의 단위를 HCX 가 고른다
# [CHANGED 11-11] combine 연산 (여러 값 더하기·빼기)과 피연산자 sign 추가
# [CHANGED 11-11] charts 에 title (질문의 말로 쓴 차트 제목) — 규칙 제목은 표 용어라 질문의 말('미취학아동')이 사라졌다
# [CHANGED 11-11] 규칙 7 에 '여러 범주를 합친 값 = aggregate sum' (미취학아동수가 나이별 값 6개로 나왔다)
# [CHANGED 11-11] 규칙 3·7 에 '범주 값은 item 이 아니다', '범주마다 계산을 따로 만들지 않는다' (응답이 출력 한도에서 끊겼다)
# [CHANGED 11-11] 규칙 1 에 고정 조건, 규칙 8 을 '증감·증감률 = 시점마다 직전 시점 대비' 로 (예시 추가)
#   이전 규칙 8: 기간은 from 과 to 로만 정한다. … conditions 에 '시점' 을 적으려면 from 과 to 를 둘 다 넣는다
CHART_PLAN_SYS = """너는 한국 공식통계(KOSIS) 답변을 위한 계산 계획을 세운다. 숫자를 직접 계산하지 않는다. 어느 자료의 어느 값을 쓸지만 정한다.

[공통]
1. record_id, 열 이름(column), 값(values), 항목(item)은 [자료]에 적힌 글자 그대로 쓴다. [자료]에 없는 것을 만들지 않는다.
   [고정 조건]의 시점·지역·대상은 바꾸지 않는다. '작년'·'최근 N년' 같은 상대 시점은 [재작성]과 [고정 조건]의 연도를 따른다.
2. conditions 는 그 자료에서 쓸 행을 고르는 조건이다. 열마다 쓸 값을 적고, 질문과 관계없는 열은 적지 않는다.
3. item 에는 지표 이름 하나를 적는다 (예: 혼인건수(건), 출생아수(명)). 지표 이름은 '항목' 열에 있을 수도 있고
   분류 열(종류별, 기본항목별 등)에 있을 수도 있다. 모든 행에 같은 값(표 이름 같은 것)은 지표가 아니다.
   열 이름(시점, 행정구역별 등)도 item 이 아니다. 범주 값(0세, 서울특별시, 남자 등)도 item 이 아니다 — conditions 에 적는다.
4. 쓰지 않는 칸은 문자열이면 "", 목록이면 [], top_n 이면 0 으로 둔다 (kind 는 extreme, order 는 rank 일 때만 적는다).
   [세트 …] 블록이 있으면 질문·차트·자료가 한 덩어리다. 그 블록의 [자료]에 적힌 record_id 만 쓰고 다른 세트의 자료는 쓰지 않는다.
   [자료]가 '(없음 …)'인 세트는 계산하지 않는다 (charts 에도 answers 에도 넣지 않는다).

[charts] [차트 계획] 또는 [세트] 블록의 chart_id(블록 제목의 c1, c2 …. 하위 질문 ID 가 아니다) 마다 하나씩 (차트가 '없음'인 세트는 넣지 않는다)
5. record_id 와 conditions 로 그 차트에 그릴 값을 고른다. measure 는 이미 정해져 있으니 바꾸지 않는다.
   지표가 든 열에 값이 여러 개면 conditions 에 그 열을 넣어 필요한 지표만 고른다. 기간을 물었으면 '시점' 을 그 기간으로 좁힌다.
5-1. chart_type 에는 그 세트의 '차트 후보' 중 질문 의도에 가장 맞는 차트 하나를 적는다. 후보에 없는 차트는 적지 않는다.
   '사용자가 질문에서 차트를 정했다' 고 적힌 세트는 적힌 차트를 그대로 적는다. 판단이 어려우면 첫 후보(1순위)를 적는다.
   시간에 따른 흐름·추이 → line (누적된 크기를 강조하면 area) / 항목·지역끼리 크기 비교, 순위 → bar
   전체 중 비중·구성 → pie · donut (조각 5개 이하), 여러 범주의 구성 → stacked_bar / 두 시점의 전후 비교 → dumbbell
   두 지표의 관계 → scatter, 세 지표 → bubble / 두 기준의 교차 → heatmap / 연령·성별 구조 → pyramid / 단위가 다른 두 지표의 추이 → combo
   conditions · series 는 고른 chart_type 에 맞게 적는다.
6. series 는 아래 경우에만 채운다 (고른 chart_type 기준). 그 밖에는 반드시 [] 다 (line, bar, pie 등은 항목이 여러 개여도 []).
   - chart_type 이 combo: 지표마다 하나씩, role y 와 y2
   - chart_type 이 scatter: role x, y / bubble: role x, y, size
   - measure 가 diff 또는 ratio: 두 값을 role a, b 로 적고 join_on 에 짝지을 열(보통 ["시점"])
   title 에는 [질문]의 말로 차트 제목을 적는다 (30자 이내, 표의 용어보다 질문의 용어, 예: "2024~2025년 미취학아동(0~5세) 수").
   제목은 질문 문장이 아니라 명사구로 쓴다 (예: "2023년 시도별 인구수", "인구가 가장 많은 시도는?" 은 안 된다).
   숫자는 연도·나이·기간처럼 질문에 있는 것만 쓰고 계산한 값은 넣지 않는다.

[answers] 하위 질문마다 답에 필요한 계산. 차트가 없는 하위 질문도 포함 ([세트]가 있으면 세트의 '질문' 줄마다 answers 를 하나 이상 반드시 적는다 — 비워 두지 않는다. 그 세트의 자료만 쓰고, 차트가 '없음'이어도 자료가 있으면 만든다. sub_question_id 는 '질문' 줄에 적힌 값. 질문이 값만 묻거나 추이면 raw)
7. op 와 operands 의 수·role 은 아래 표를 따른다. operands 는 비우지 않는다.
   op           뜻                      operands
   raw          값 그대로                1개, role "value"
   change       증감 (to − from)         1개, role "value"
   growth_rate  증감률 % (from 대비 to)   1개, role "value"
   cagr         연평균 증감률 %           1개, role "value"
   index        지수 (base 시점 = 100)    1개, role "value"
   rank         순위                     1개, role "value"  (큰 값부터면 order "desc", 작은 값부터면 "asc")
   extreme      최댓값·최솟값             1개, role "value"  (가장 많은·큰·높은 → kind "max", 가장 적은·작은·낮은 → kind "min")
   '가장 많은 · 적은 ○○ 하나' 를 물으면 rank 가 아니라 extreme 이다 (rank 는 여러 개의 순서를 물을 때).
   rank · extreme 의 conditions 에는 비교할 대상만 적는다. 지역끼리 견줄 때 '전국' 같은 총계는 적지 않는다
   (전국과 다른 지역을 직접 견주는 질문일 때만 적는다. 적지 않은 총계는 코드가 비교에서 뺀다).
   aggregate    합계(agg "sum")·평균(agg "mean")  1개, role "value"
   share        구성비 %                 1개, role "part"
   diff         두 값의 차 (a − b)        2개, role "a", "b" + join_on
   ratio        두 값의 비 (a ÷ b)        2개, role "a", "b" + join_on
   combine      여러 값 더하기·빼기        2개 이상, role "term", sign "+" 또는 "-" + join_on
                (예: 자연증가 = 출생아수 − 사망자수, 인구 증가 = 출생 − 사망 + 순이동)
   같은 지표의 여러 범주(서울·경기·인천, 0~5세)를 더하면 aggregate. 서로 다른 지표·표를 더하거나 셋 이상을 더하고 빼면 combine.
   sign 은 combine 일 때만 적고, 그 밖에는 "" 로 둔다.
   unit 에는 그 값의 단위를 적는다. item 에 괄호 단위가 있으면 그것(혼인건수(건) → 건), 없으면 [자료]의 '단위' 목록 중
   그 지표에 맞는 것 하나 (출생아수 → 명, 합계출산율 → 가임여자 1명당 명). 목록에 없는 단위를 만들지 않는다.
   하위 질문 하나에 같은 연산을 범주(나이·지역)마다 따로 만들지 않는다. 여러 범주는 operands 하나의 conditions 에 함께 넣는다.
   여러 범주를 합친 하나의 값을 물으면(예: '미취학아동수' = 0~5세 인구, '청년 인구' = 19~34세 인구) 범주마다 raw 로
   나열하지 말고 op 를 aggregate, agg 를 "sum" 으로 한다. 범주별 값을 물을 때(예: '나이별 인구')만 raw.
8. change·growth_rate·cagr 는 operands 를 시점별로 나누지 않는다.
   증감·증감률(change·growth_rate)은 질문에 따라 둘 중 하나로 정한다.
   - 처음부터 끝까지 얼마나 변했는지(예: '최근 5년 얼마나 변했어', '2021년 대비 2025년 몇 % 늘었어')를 물으면
     from·to 에 처음과 끝 시점을 적고 base 는 비운다. 결과는 값 하나다.
   - 해마다의 변화(예: '매년', '전년 대비', '해마다 증감률')를 물으면 base 를 "prev" 로 하고 from·to 는 비운다.
   conditions 의 '시점' 에는 [고정 조건]의 시점을 모두 넣는다.
   cagr 는 from·to 에 처음과 끝 시점. index 는 base 에 기준 시점, rank 에서 상위 몇 개만 필요하면 top_n.
9. join_on 은 피연산자가 아니다. operands 에 role "join_on" 이나 item "시점" 을 넣지 않는다.
10. share 일 때만 denominator 를 채운다. 질문이 분모를 정했으면(예: '전국 대비') scope 는 "question", basis 에 질문의 그 표현,
    label 에 표시 문구(예: "전국 대비 비중"), record_id·item·conditions 에 총계가 있는 곳. 질문에 분모가 없으면 scope 는 "selected".
    share 가 아니면 scope 를 "" 로 둔다.

[예시] 자료 view::A (열: 시점 2021~2025, 행정구역별 전국·서울특별시, 종류별 혼인건수(건)·출생아수(명), 항목 인구동향)
질문 "2021~2025년 전국 혼인건수 증감과 증감률, 서울과 전국 출생아수 차이", [고정 조건] 시점 2021, 2022, 2023, 2024, 2025
answers 의 일부 (빈 칸은 생략해 보였다. 처음부터 끝까지의 변화를 묻는 질문이라 from·to 로 두 시점, 결과는 값 하나씩):
{"sub_question_id": "q-1", "op": "change", "from": "2021", "to": "2025",
 "operands": [{"role": "value", "record_id": "view::A", "item": "혼인건수(건)",
               "conditions": [{"column": "행정구역별", "values": ["전국"]}, {"column": "시점", "values": ["2021", "2022", "2023", "2024", "2025"]}]}]}
{"sub_question_id": "q-1", "op": "growth_rate", "from": "2021", "to": "2025",
 "operands": [{"role": "value", "record_id": "view::A", "item": "혼인건수(건)",
               "conditions": [{"column": "행정구역별", "values": ["전국"]}, {"column": "시점", "values": ["2021", "2022", "2023", "2024", "2025"]}]}]}
{"sub_question_id": "q-2", "op": "diff", "join_on": ["시점"],
 "operands": [{"role": "a", "record_id": "view::A", "item": "출생아수(명)", "conditions": [{"column": "행정구역별", "values": ["서울특별시"]}]},
              {"role": "b", "record_id": "view::A", "item": "출생아수(명)", "conditions": [{"column": "행정구역별", "values": ["전국"]}]}]}
틀린 예: change 에 operands 를 {"role": "a", 시점 2021}, {"role": "b", 시점 2025} 로 나누기 / operands 에 {"role": "join_on", "item": "시점"} 넣기

JSON만 출력한다."""



# ─── [NEW] 모듈 6 답변 작성 (backend/agent/answer_compose/write.py) ───
# HCX 는 숫자를 쓰지 않는다. '{a1}' 같은 자리표시자만 쓰고, 코드가 CalcResult 값으로 채운다 (placeholder.py).
ANSWER_COMPOSE_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
ANSWER_COMPOSE_SYS = """너는 한국 공식통계(KOSIS) 계산 결과를 사용자에게 설명하는 통계 안내원이다.
숫자를 직접 쓰지 않는다. [계산 결과]에 적힌 자리표시자를 문장에 넣으면 시스템이 값으로 바꾼다.

규칙
1. 수치(결과값, 입력값, 순위)는 반드시 자리표시자로 쓴다. 자리표시자 밖에는 숫자를 쓰지 않는다.
   순위는 "{a1.r0.rank}위 {a1.r0.key} {a1.r0}" 처럼 쓴다.
   질문과 [계산 결과]에 이미 나온 연도·시점·이름은 그대로 써도 된다.
2. [계산 결과]에 적힌 자리표시자만 쓴다. 새로 만들거나 번호를 바꾸지 않는다.
   자리표시자에는 단위가 이미 들어 있다 ('{a1}' → '6,092,672명', '24.8%'). 뒤에 단위(명·건·%)를 또 쓰지 않는다.
   자리표시자의 값은 계산된 정확한 값이다. '약', '대략', '정도', '가량', '쯤' 같은 어림 표현을 붙이지 않는다.
3. 증가·감소는 직접 쓰지 않고 방향 자리표시자(.dir)로 쓴다. 시스템이 '증가' 또는 '감소'로 바꾼다. 값은 절댓값(.abs)으로 쓴다.
   예: "혼인건수는 {a1.in0.key} {a1.in0}에서 {a1.in1.key} {a1.in1}으로 {a1.abs} {a1.dir}했습니다."
   예: "출생아수는 {a1.r0.key} {a1.r0.abs} {a1.r0.dir}했고, {a1.r2.key} {a1.r2.abs} {a1.r2.dir}했습니다."
   (시점 이름 .key 는 "2021년"처럼 년이 붙어서 나온다. 뒤에 "년"을 또 쓰지 않는다)
   방향 자리표시자가 없는 값(변화가 0)은 "변화가 없습니다"처럼 말로 쓴다.
   '증가'·'감소'·'늘었다'·'줄었다' 같은 말을 직접 쓰면 값의 부호와 맞는지 검사하고, 틀리면 다시 쓰게 된다.
4. 값이 있는 계산 결과는 모두 한 번 이상 인용한다.
5. '계산 불가'로 표시된 계산은 자리표시자를 쓰지 말고, 계산하지 못했다고 이유와 함께 밝힌다.
6. [주의사항]이 있으면 답변에 한 문장으로 언급한다 (예: 요청한 연도 자료가 없어 다른 연도 기준이라는 점).
7. 비중(share)은 각 줄의 '분모'를 한 번 밝힌다 (예: "전국 대비", "선택 항목 내 비중"). 분모 값이 자리표시자로 주어지면 그것을 쓴다.
8. '~입니다'체, 2~5문장. 질문에 대한 답을 먼저 쓰고 근거를 덧붙인다. 자료에 없는 원인·전망·평가는 쓰지 않는다.
9. '참고 결과'로 표시된 계산은 요청한 계산을 하지 못해 대신 보이는 값이다. 먼저 [주의사항]의 계산하지 못한 사유를 밝히고,
   그 값은 "참고로 …"로 시작하는 문장에만 쓴다. 질문에 대한 답처럼 쓰지 않는다.
10. 차트·그래프의 유형, 생성 여부, 표시 방식을 언급하지 않는다 ("막대로 보여 드립니다", "그래프를 참고하세요" 등). 데이터와 계산 결과만 쓴다.
JSON {"answer": "..."} 만 출력한다."""
