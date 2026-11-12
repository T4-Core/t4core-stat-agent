"""
모듈 5 tool — draw_chart(job) → DrawResult

  DrawJob 하나를 차트 하나로 그린다. 파일을 쓰지 않는 순수 함수라 병렬(LangGraph Send)로 불러도 안전하다.
    ① precheck   유형별 약속 확인 (15종 · 렌더러 · 필수 역할 · 열 · rows · 숫자 역할 · 음수 불가 · pyramid group · display_ref)
    ② to_df      columns + rows → DataFrame
    ③ 렌더러      RENDERERS[chart_type] → traces · layout
    ④ decorate   제목(+scope_label) · 한글 폰트 · 범례 · 출처 (공통)
    ⑤ DrawResult 예외가 나면 failed + 이유
"""
import plotly.graph_objects as go

from backend.agent.chart_calculate.specs import SPECS

from .draw_chart_format import FONT_FAMILY, is_missing, source_text, to_df
from .draw_chart_renderers import RENDERERS
from .draw_chart_schema import (CHART_TYPES, DRAWN, FAILED, NOT_IMPLEMENTED, NUMERIC_ROLES, READY, DrawJob,
                                DrawResult)

def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def column_values(content, col):
    i = content.columns.index(col)
    return [r[i] if i < len(r) else None for r in content.rows]


def precheck(job):
    """① 사전 검사 = 유형별 약속(2번 셀의 약속 표) 확인 → (상태, 이유, 경고). 그릴 수 있으면 (READY, None, 경고)
      1. 2번에서 정해진 상태 (SKIPPED / FAILED)
      2. 15종 안의 유형인가 / 렌더러가 있는가
      3. 필수 역할이 encoding에 있는가 (SPECS.required)  — 약속에 없는 역할은 경고만
      4. encoding이 가리키는 열이 columns에 있는가 / rows가 비어 있지 않은가
      5. 숫자 역할(NUMERIC_ROLES)의 값이 숫자인가 (None은 결측으로 허용) / 값이 하나는 있는가
      6. 음수 불가 역할(SPECS.non_negative)에 음수가 없는가
      7. 유형별 추가 약속: pyramid의 group은 값이 2개
      8. display_ref가 displays에 있는가"""
    warns = []
    if job.status != READY:
        return job.status, job.reason, warns
    c, t = job.content, job.chart_type
    if t not in CHART_TYPES:
        return FAILED, f"15종 밖의 차트 유형: {t}", warns
    if t not in RENDERERS:
        return NOT_IMPLEMENTED, f"{t} 렌더러가 아직 없음", warns
    spec = SPECS[t]
    missing_roles = [r for r in spec.required if r not in c.encoding]
    if missing_roles:
        return FAILED, f"필수 역할이 encoding에 없음: {missing_roles} ({t} 약속: 필수 {list(spec.required)})", warns
    if unknown := [r for r in c.encoding if r not in spec.required + spec.optional]:
        warns.append(f"{t} 약속에 없는 역할은 쓰지 않음: {unknown}")
    missing_cols = sorted({col for col in c.encoding.values() if col not in c.columns})
    if missing_cols:
        return FAILED, f"encoding이 가리키는 열이 columns에 없음: {missing_cols}", warns
    if not c.rows:
        return FAILED, "rows가 비어 있음", warns
    for role in NUMERIC_ROLES[t]:
        if role not in c.encoding:
            continue
        col = c.encoding[role]
        vals = column_values(c, col)
        if bad := [v for v in vals if not is_missing(v) and not is_number(v)]:
            return FAILED, f"숫자여야 하는 역할 {role}('{col}')에 숫자가 아닌 값 {len(bad)}개: {bad[:3]}", warns
        if all(is_missing(v) for v in vals):
            return FAILED, f"숫자여야 하는 역할 {role}('{col}')에 값이 하나도 없음", warns
    for role in spec.non_negative:
        if role in c.encoding and (neg := [v for v in column_values(c, c.encoding[role]) if is_number(v) and v < 0]):
            return FAILED, f"음수가 올 수 없는 역할 {role}('{c.encoding[role]}')에 음수 {len(neg)}개: {neg[:3]}", warns
    if t == "pyramid":
        groups = list(dict.fromkeys(map(str, column_values(c, c.encoding["group"]))))
        if len(groups) != 2:
            return FAILED, f"pyramid의 group('{c.encoding['group']}') 값은 2개여야 함: {groups}", warns
    missing_refs = [r for r in job.display_refs if r not in job.displays]
    if missing_refs:
        return FAILED, f"displays에 없는 display_ref: {missing_refs}", warns
    return READY, None, warns


# ── 공통 꾸미기 ───────────────────────────────────
def decorate(fig, job, layout):
    """⑤ 제목(+scope_label) · 한글 폰트 · 범례(trace 2개 이상이면 표시) · 렌더러 레이아웃 · 출처"""
    title = job.content.title
    if scope := job.content.options.get("scope_label"):
        title += f"<br><sup>{scope}</sup>"
    base = {
        "template": "plotly",
        "title": {"text": title, "x": 0.02, "xanchor": "left"},
        "font": {"family": FONT_FAMILY},
        "showlegend": sum(bool(getattr(t, "showlegend", True) is not False) for t in fig.data) > 1,
        "margin": {"t": 80, "b": 90, "l": 70, "r": 30},
    }
    base.update(layout)                       # 렌더러가 정한 값이 우선
    fig.update_layout(**base)
    if text := source_text(job.source_links):
        fig.add_annotation(text=text, xref="paper", yref="paper", x=0, y=-0.22, xanchor="left", yanchor="top",
                           showarrow=False, font={"size": 11, "color": "#666"})
    return fig


# ── draw_chart (tool) ─────────────────────────────
def draw_chart(job: DrawJob) -> DrawResult:
    """DrawJob 하나 → DrawResult. 파일을 쓰지 않는 순수 함수 (병렬 실행 안전)
    ① 사전 검사 → ② 표 → ③ 표시 설정·④ 렌더러 → ⑤ 공통 꾸미기 → ⑥ 결과. 예외는 FAILED + 이유"""
    res = DrawResult(chart_id=job.chart_id, chart_type=job.chart_type, status=READY, planned_type=job.planned_type,
                     sub_question_ids=job.sub_question_ids, title=job.content.title if job.content else None,
                     warnings=list(job.warnings))
    try:
        status, reason, warns = precheck(job)                             # ① 유형별 약속 확인
        res.warnings += warns
        if status != READY:
            res.status, res.reason = status, reason
            return res
        df = to_df(job.content)                                           # ②
        traces, layout, warns = RENDERERS[job.chart_type](df, job.content, job.displays)   # ③ ④
        fig = decorate(go.Figure(traces), job, layout)                    # ⑤
        res.status, res.figure = DRAWN, fig                               # ⑥
        res.warnings += warns
    except Exception as e:                                                # noqa: BLE001 — 차트 하나의 실패가 전체를 멈추지 않게
        res.status, res.reason = FAILED, f"그리는 중 예외: {type(e).__name__}: {e}"
    return res
