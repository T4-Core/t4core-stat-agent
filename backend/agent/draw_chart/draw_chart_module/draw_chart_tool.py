"""
모듈 5 tool — draw_chart(job) → DrawResult

  DrawJob 하나를 차트 하나로 그린다. 파일을 쓰지 않는 순수 함수라 병렬(LangGraph Send)로 불러도 안전하다.
    ① precheck   유형별 약속 확인 (15종 · 렌더러 · 필수 역할 · 열 · rows · 숫자 역할 · 음수 불가 · pyramid group · display_ref)
    ② to_df      columns + rows → DataFrame
    ③ 렌더러      RENDERERS[chart_type] → traces · layout
    ④ decorate   제목(+scope_label) · 한글 폰트 · 범례 · 출처 (공통)
    ⑤ DrawResult 예외가 나면 failed + 이유. 값이 1개뿐인 차트는 그리되 경고 (single_value_warning)
"""
from dataclasses import replace

import plotly.graph_objects as go

from backend.agent.chart_calculate.specs import SPECS

from .draw_chart_format import FONT_FAMILY, SOURCE_GAP, apply_colors, digits_of, is_missing, source_text, to_df, widen_digits
from .draw_chart_highlight import highlight
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


# ── 표시 자릿수 보정 ───────────────────────────────
def _role_values(content, role):
    """역할 열의 값. combo 의 y · y2 는 같은 값 열이라 options.series_axis 로 그 축의 계열 행만"""
    col = content.encoding.get(role)
    if not col or col not in content.columns:
        return []
    vals = column_values(content, col)
    s_col, axis_of = content.encoding.get("series"), content.options.get("series_axis") or {}
    if content.chart_type == "combo" and role in ("y", "y2") and s_col in content.columns and axis_of:
        ss = column_values(content, s_col)
        vals = [v for v, s in zip(vals, ss) if axis_of.get(str(s), "y") == role]
    return vals


def widen_job_displays(job):
    """차트 값을 display 자릿수로 표시하면 서로 다른 값이 같은 숫자가 될 때, 이 차트에서만 자릿수를 늘린다 → 경고 목록
    축(역할)마다 따로 본다: combo 처럼 y(출생아수) · y2(합계출산율)가 같은 display_ref 를 쓰면 늘려야 하는 축만
    '{ref}@{역할}' 새 표시 설정을 만들어 그 축에 연결한다 (이 job 의 content 사본만 바꾼다)
    모듈 3 displays 원본은 그대로 → 답변(모듈 6) · 다른 차트에는 영향 없음"""
    c, warns = job.content, []
    displays, axis = dict(job.displays), dict(c.axis)
    by_ref = {}
    for role, spec in c.axis.items():
        if spec.display_ref in job.displays and role in c.encoding:
            by_ref.setdefault(spec.display_ref, []).append(role)
    if (ref := c.options.get("display_ref")) in job.displays:              # 축 없는 차트 (pie · map …)
        by_ref.setdefault(ref, []).extend(r for r in ("value", "size") if r in c.encoding and r not in c.axis)
    for ref, roles in by_ref.items():
        d = job.displays[ref]
        widened = {r: widen_digits(d, _role_values(c, r)) for r in roles}
        need = {r: w for r, w in widened.items() if w[1] is not None}
        if not need:
            continue
        if len(need) == len(roles) and len({w[1] for w in need.values()}) == 1:   # 이 ref 를 쓰는 축이 모두 같은 자릿수로
            new, dg = next(iter(need.values()))
            displays[ref] = new
            warns.append(f"표시 자릿수를 {digits_of(d)}자리 → {dg}자리로 늘림 ({ref}: 그대로면 서로 다른 값이 같은 숫자로 보임)")
            continue
        for role, (new, dg) in need.items():                                      # 축마다 따로
            key = f"{ref}@{role}"
            displays[key] = new
            axis[role] = axis[role].model_copy(update={"display_ref": key})
            warns.append(f"표시 자릿수를 {digits_of(d)}자리 → {dg}자리로 늘림 ({ref} · {role} 축: 그대로면 서로 다른 값이 같은 숫자로 보임)")
    if axis != c.axis:
        job.content = c.model_copy(update={"axis": axis})
    job.displays = displays
    return warns


# ── 데이터 모양 경고 ───────────────────────────────
# 비교 · 추이를 보여 주는 축: 이 열의 값(값이 있는 것)이 1개뿐이면 차트로 보여 줄 것이 없다
POINT_ROLES = {"line": ("x", "y", "추이를"), "area": ("x", "y", "추이를"), "combo": ("x", "y", "추이를"),
               "bar": ("x", "y", "비교를"), "stacked_bar": ("x", "y", "비교를"),
               "pie": ("label", "value", "구성을"), "donut": ("label", "value", "구성을"), "treemap": ("label", "value", "구성을")}


def single_value_warning(content):
    """x(또는 label) 값이 1개뿐인 차트 → 경고 문장. 아니면 None
    예: '연도별 고령자 수를 남녀로' 인데 1995년 한 해 · 성별 없음 → 막대 1개"""
    key_role, val_role, what = POINT_ROLES.get(content.chart_type, (None, None, None))
    k_col, v_col = content.encoding.get(key_role), content.encoding.get(val_role)
    if not k_col or not v_col:
        return None
    vals = column_values(content, v_col)
    keys = list(dict.fromkeys(str(k) for k, v in zip(column_values(content, k_col), vals) if not is_missing(v)))
    if len(keys) > 1:
        return None
    shown = f" '{keys[0]}'" if keys else ""
    return f"값이 1개뿐인 차트 ({k_col}{shown} 하나) — {what} 보기 어려워 표로 보는 편이 낫다"


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
        # 그림 높이와 관계없이 아래 여백 맨 밑에 놓는다 (예전: y=-0.22 → 높이 520px 에서 아래로 2px 잘림)
        b = fig.layout.margin.b if fig.layout.margin.b is not None else 80
        fig.add_annotation(text=text, xref="paper", yref="paper", x=0, y=0, xanchor="left", yanchor="bottom",
                           yshift=-(b - SOURCE_GAP), showarrow=False, font={"size": 11, "color": "#666"})
    return fig


# ── draw_chart (tool) ─────────────────────────────
def draw_chart(job: DrawJob) -> DrawResult:
    """DrawJob 하나 → DrawResult. 파일을 쓰지 않는 순수 함수 (병렬 실행 안전)
    ① 사전 검사 → ② 표 → ③ 표시 설정·④ 렌더러 → ⑤ 공통 꾸미기 → ⑥ 결과. 예외는 FAILED + 이유
    받은 job 은 바꾸지 않는다 (사본에서 자릿수 보정) → 겹쳐 그리기가 원래 job 의 표시 설정을 그대로 쓴다"""
    job = replace(job, displays=dict(job.displays))
    res = DrawResult(chart_id=job.chart_id, chart_type=job.chart_type, status=READY, planned_type=job.planned_type,
                     sub_question_ids=job.sub_question_ids, title=job.content.title if job.content else None,
                     warnings=list(job.warnings))
    try:
        status, reason, warns = precheck(job)                             # ① 유형별 약속 확인
        res.warnings += warns
        if status != READY:
            res.status, res.reason = status, reason
            return res
        res.warnings += widen_job_displays(job)                          # 값이 같은 숫자로 뭉개지지 않게 자릿수 보정
        df = to_df(job.content)                                           # ②
        traces, layout, warns = RENDERERS[job.chart_type](df, job.content, job.displays)   # ③ ④
        fig = go.Figure(traces)
        apply_colors(fig, job.colors)                                     # 같은 이름 = 같은 색 (질문 전체)
        fig = decorate(fig, job, layout)                                  # ⑤
        res.status, res.figure = DRAWN, fig                               # ⑥
        res.warnings += warns
        if w := single_value_warning(job.content):                       # 그리기는 하되 사용자에게 알린다
            res.warnings.append(w)
        try:                                                              # 계산 강조 (실패해도 차트는 그대로)
            res.warnings += highlight(fig, job)
        except Exception as e:                                            # noqa: BLE001
            res.warnings.append(f"강조 생략: {type(e).__name__}: {e}")
    except Exception as e:                                                # noqa: BLE001 — 차트 하나의 실패가 전체를 멈추지 않게
        res.status, res.reason = FAILED, f"그리는 중 예외: {type(e).__name__}: {e}"
    return res
