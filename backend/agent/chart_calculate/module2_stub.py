"""
[NEW] 모듈 2 대역 — 하위 질문의 의도 + View 모양으로 ChartRequest(차트 계획)를 만든다

  TODO(임시): 모듈 2(차트 판단)가 생기면 그 출력으로 바꾼다. 이 파일과 POST /api/v1/chart/suggest 는 그때 지운다.

  판단 순서
    1. 의도 → 기본 차트  (추이·증감·증감률 → line / 비교 → bar / 순위 → bar·rank / 구성비 → pie·share / 그 밖 → 차트 없음)
    2. 그 하위 질문의 View 모양(시점 수, 범주 수, 행 수)으로 보정  — 어긋나면 어차피 validate.py 가 떨어뜨리므로,
       여기서 미리 맞는 차트를 고른다. requirements 는 명세 8장 기본값(specs.requirements_for)을 그대로 쓴다.

  View id 의 번호 자리 (rag/ingestion/views.py): 원 질문 View = '{query_id}-{순위}', 하위 질문 i 의 View = '{query_id}-{i}-{순위}'.
  하위 질문이 있으면 '{query_id}-1' 은 원 질문 View 다 → 하위 질문 1 의 View 로 붙이지 않는다.
  View 를 못 찾으면 보정 없이 의도 기본값만 쓴다.
"""
import re

from backend.agent.chart_calculate.calculate import TIME_COL
from backend.agent.chart_calculate.planner import sub_question_ids
from backend.agent.chart_calculate.select import VALUE_COL
from backend.agent.chart_calculate.specs import requirements_for
from backend.schemas.chart import ChartRequest
from backend.schemas.query import QueryBundle
from backend.schemas.record import Record

# 의도 → (chart_type, measure, fallback_chart). 값 조회·합계·범위 밖은 표에 없다 = 차트 없음
BASE: dict[str, tuple[str, str, str | None]] = {
    "추이": ("line", "raw", "bar"), "증감": ("line", "raw", "bar"), "증감률": ("line", "raw", "bar"),
    "비교": ("bar", "raw", None), "순위": ("bar", "rank", None), "구성비": ("pie", "share", "bar"),
}
PIE_MAX = 5          # specs: pie max_categories_5
LINE_MIN_POINTS = 3  # specs: line min_points_3


class Shape:
    """하위 질문의 View 들을 합친 모양. 시점 수(None = 시점 열 없음), 범주 수, 값 있는 행 수"""

    def __init__(self, records: list[Record]):
        times: set = set()
        cats = rows = 0
        self.has_time = False
        for r in records:
            cols = r.table.columns
            vi = cols.index(VALUE_COL) if VALUE_COL in cols else len(cols) - 1
            data = [row for row in r.table.rows if row[vi] is not None]
            rows += len(data)
            if TIME_COL in cols:
                self.has_time = True
                times |= {row[cols.index(TIME_COL)] for row in data}
            # 범주 수 = 시점·값을 뺀 열(지역·항목·성별 …) 중 값이 가장 다양한 열의 값 종류 수
            others = [i for i, c in enumerate(cols) if c not in (TIME_COL, VALUE_COL) and i != vi]
            cats = max([cats, *(len({row[i] for row in data}) for i in others)])
        self.n_time, self.n_cat, self.n_rows = len(times), cats, rows


def _records_of(records: list[Record], bundle: QueryBundle, sub_id: str) -> list[Record]:
    # [CHANGED] 이전: ::{sub_id}(-\d+)?:: — 하위 질문이 있을 때 원 질문 View('{qid}-1')까지 하위 질문 1 의 것으로 붙었다
    if bundle.sub_questions:
        pat = re.compile(rf"::{re.escape(sub_id)}-\d+::")
    else:
        pat = re.compile(rf"::{re.escape(bundle.query_id or 'q')}-\d+::")
    return [r for r in records if pat.search(r.id)]


def _intent_of(bundle: QueryBundle, i: int, intents: list[str] | None) -> str | None:
    """intents[i] → (intents 가 짧으면 첫 값) → sub_filters[i].의도 → 원 질문 의도 → filters.의도.
    sub_filters·filters 의 의도는 View 용 4종(값 조회·추이·비교·순위)으로 줄어든 값이다"""
    if intents:
        return intents[i] if i < len(intents) else intents[0]
    subs = bundle.sub_filters or []
    if i < len(subs) and subs[i] is not None and subs[i].의도:
        return subs[i].의도
    return bundle.intent or (bundle.filters.의도 if bundle.filters else None)


def _adjust(intent: str, base: tuple[str, str, str | None], shape: Shape) -> tuple[tuple[str, str, str | None], str]:
    """(보정한 (chart_type, measure, fallback), 사유). chart_type None = 차트 없음"""
    chart, measure, fallback = base
    if shape.n_rows <= 1:       # 값이 하나뿐이면 그릴 것이 없다 (시점이 하나여도 마찬가지)
        return (None, "raw", None), "값이 하나뿐이라 차트 없음"
    if chart == "line" and shape.has_time and shape.n_time < LINE_MIN_POINTS:
        # line 은 min_points_3 → 시점이 1~2개면 막대. 대체 차트가 필요 없으니 fallback 도 비운다
        return ("bar", "raw", None), f"시점 {shape.n_time}개라 line 대신 bar"
    if chart == "pie" and shape.n_cat < 2:
        return (None, "raw", None), "구성 항목이 하나뿐이라 차트 없음"
    if chart == "pie" and shape.n_cat > PIE_MAX:
        return ("bar", "share", None), f"범주 {shape.n_cat}개(>5)라 pie 대신 bar"
    if chart == "bar" and intent in ("비교", "순위") and shape.n_cat < 2 and shape.n_time < 2:
        return (None, "raw", None), "견줄 범주가 하나뿐이라 차트 없음"
    # 비교·순위의 범주가 20개를 넘어도 bar 를 유지한다: max_categories_20 검증이 사유와 함께 걸러낸다
    return base, ""


def suggest_charts(bundle: QueryBundle, records: list[Record], intents: list[str] | None = None) -> list[ChartRequest]:
    out: list[ChartRequest] = []
    for i, (sid, _) in enumerate(sub_question_ids(bundle)):
        intent = _intent_of(bundle, i, intents)
        base = BASE.get(intent or "")
        recs = _records_of(records, bundle, sid)
        why = f"의도 '{intent or '-'}'"
        if base is None:
            chosen = (None, "raw", None)
            why += " → 표로 충분해 차트 없음"
        elif recs:
            chosen, note = _adjust(intent, base, Shape(recs))
            why += f" → {chosen[0] or '차트 없음'}" + (f" ({note})" if note else "")
        else:
            chosen = base
            why += f" → {base[0]} (View 를 못 찾아 보정 없음)"
        chart_type, measure, fallback = chosen
        out.append(ChartRequest(
            chart_id=f"c{i + 1}", sub_question_ids=[sid], chart_type=chart_type, measure=measure,
            requirements=requirements_for(chart_type) if chart_type else [], fallback_chart=fallback,
            reason=f"모듈 2 대역: {why}"))
    return out
