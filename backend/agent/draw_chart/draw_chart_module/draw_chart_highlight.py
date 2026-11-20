"""
모듈 5 강조 — 질문용 계산(CalcResult)의 답을 차트 위에 표시한다

  calcs_for(content, calcs)  차트와 record 가 겹치고 값이 있는 계산 (op: extreme · rank · change · growth_rate · diff)
  highlight(fig, job)        fig 에 강조(막대 테두리 · 큰 점) + 화살표 주석을 더한다 → 경고 목록

    extreme                 그 점(동점 모두)          '최댓값 경기도 71,285명' / '최솟값 …'
    rank                    1위 점                    '1위 경기도 71,285명'
    change · growth_rate · diff
      값 하나 (기간 증감)    계산에 쓴 처음 · 끝 점 강조, 끝 점에 '2015→2024 -200,103명 (-45.6%)'
                            (같은 record 의 change 와 growth_rate 는 주석 하나로 합친다)
      목록 (범주별 증감)     가장 크게 증가한 점 · 가장 크게 감소한 점만 (차트가 그 목록 자체인 경우가 많다)

  대상 유형: line · area · bar · stacked_bar · combo. 주석은 차트당 최대 MAX_NOTES 개.
  계산 키({'시점': '2024', '시도별': '경기도'})로 ChartContent 행을 찾아 그 행의 x(범주) · 계열로 그림의 점을 찾는다.
"""
import re

from .draw_chart_format import display_for, fmt, is_missing

TARGET_OPS = ("extreme", "rank", "change", "growth_rate", "diff")
HIGHLIGHT_TYPES = ("line", "area", "bar", "stacked_bar", "combo")
MAX_NOTES = 4
OP_NAME = {"change": "증감", "diff": "차이", "growth_rate": "증감률"}
NOTE_FONT = {"size": 11, "color": "#222"}
EDGE = "#222"


def calcs_for(content, calcs):
    """이 차트와 record 가 겹치고 값이 있는 강조 대상 계산"""
    rids = set(content.record_ids or [])
    return [c for c in calcs or [] if c.op in TARGET_OPS and c.value is not None and rids & set(c.record_ids or [])]


def _strip_unit(s):
    """'전체 출생아수(명)' → '전체 출생아수'"""
    return re.sub(r"\s*\([^)]*\)\s*$", "", str(s or ""))


class _Points:
    """계산 키 → 그림의 점 (trace 번호, 점 번호)"""

    def __init__(self, fig, content):
        self.fig, self.c = fig, content
        self.h = content.options.get("orientation") == "horizontal"

    def cats(self, t):
        return [str(v) for v in ((t.y if self.h else t.x) or [])]

    def value(self, ti, pi):
        t = self.fig.data[ti]
        return (t.x if self.h else t.y)[pi]

    def find(self, key, item=None):
        c = self.c
        cols = c.columns
        x_col, s_col = c.encoding.get("x"), c.encoding.get("series")
        used = [k for k in key if k in cols]
        if not used or x_col not in cols:
            return None
        rows = [r for r in c.rows if all(str(r[cols.index(k)]) == str(key[k]) for k in used)]
        if not rows:
            return None
        if s_col and item and len(rows) > 1:          # 계열이 여럿이면 계산의 지표(item)와 같은 계열
            name = _strip_unit(item)
            rows = [r for r in rows if str(r[cols.index(s_col)]) in (name, item)] or rows
        row = rows[0]
        cat = str(row[cols.index(x_col)])
        series = str(row[cols.index(s_col)]) if s_col else None
        for ti, t in enumerate(self.fig.data):
            if series is not None and len(self.fig.data) > 1 and str(t.name) != series:
                continue
            cats = self.cats(t)
            if cat in cats:
                pi = cats.index(cat)
                if not is_missing(self.value(ti, pi)):
                    return ti, pi, cat
        return None


def _signed(v, d):
    s = fmt(v, d)
    return f"+{s}" if isinstance(v, (int, float)) and v > 0 else s


def _emphasize(fig, ti, pi):
    """막대: 테두리 / 점: 크게"""
    t = fig.data[ti]
    n = len(t.x if t.x is not None else t.y)
    if t.type == "bar":
        w = list(t.marker.line.width) if isinstance(t.marker.line.width, (list, tuple)) else [0] * n
        w[pi] = 3
        t.marker.line.width, t.marker.line.color = w, EDGE
    else:
        size = list(t.marker.size) if isinstance(t.marker.size, (list, tuple)) else [6] * n
        size[pi] = 13
        t.marker.size = size


def _cat_pos(fig, axis, cat, pi):
    """범주 축 위치 = 범주의 순번. '2024' 같은 숫자 모양 범주를 그대로 주면 Plotly 가 숫자 2024 로 읽어 축이 0~2024 로 늘어난다"""
    arr = getattr(fig.layout, axis).categoryarray
    cats = [str(c) for c in arr] if arr is not None else None
    return cats.index(cat) if cats and cat in cats else pi


def _annotate(fig, pts, ti, pi, cat, text):
    t = fig.data[ti]
    style = dict(text=text, showarrow=True, arrowhead=2, font=NOTE_FONT, bgcolor="rgba(255,255,255,0.88)", bordercolor=EDGE)
    if pts.h:                                           # 가로 막대: 긴 막대는 왼쪽 아래에서, 짧은 막대는 오른쪽에서 가리킨다
        v = t.x[pi]
        vmax = max((abs(x) for x in t.x if not is_missing(x)), default=0)
        long_ = vmax and abs(v) > 0.6 * vmax
        fig.add_annotation(x=v, y=_cat_pos(fig, "yaxis", cat, pi), xref="x", yref="y",
                           ax=-40 if long_ else 60, ay=28 if long_ else 0, xanchor="right" if long_ else "left", **style)
        return
    yref = "y2" if getattr(t, "yaxis", None) == "y2" else "y"
    # 위에서 가리킨다 (음수 막대도 — 아래로 내리면 x축 이름과 겹친다)
    fig.add_annotation(x=_cat_pos(fig, "xaxis", cat, pi), y=t.y[pi], xref="x", yref=yref, ax=0, ay=-44, **style)


POINT_VALUE_OPS = {"raw", "rank", "extreme"}      # 결과 값이 차트 점의 값 그대로인 연산


def _notes(job, pts):
    """계산마다 (점들, 주석 점, 문구) 목록과 경고"""
    content, notes, warns = job.content, [], []
    calcs = sorted(job.calcs or [], key=lambda c: c.op == "growth_rate")   # change 를 먼저 → 증감률을 그 주석에 붙인다
    rate_by_rec = {tuple(sorted(c.record_ids)): c for c in calcs if c.op == "growth_rate" and not isinstance(c.value, list)}
    used_rates = set()

    chart_d = display_for(content, job.displays, "y")

    def disp(c):
        """차트 점의 값을 그대로 가리키는 계산(조회 · 극값 · 순위)은 차트의 표시 설정(자릿수 보정 포함)으로 → 막대 라벨과 주석 숫자가 같다.
        그 밖의 계산(증감 · 증감률 · 차이 · 평균 …)은 값을 새로 만들므로 값이 목록이어도 **계산의 표시 설정** (단위 · 배율 · 자릿수를 통째로)을 쓴다.
        [CHANGED 11-20] 이전: 값이 목록이면 무조건 차트 설정 → 증감률 목록이 건 단위 정수로 나왔다 ('가장 크게 감소 2022 0건'. 실제 -0.42%).
        원 단위(source_unit)가 같다고 같은 값은 아니다 — 차트가 '만명, 0자리'면 1,000명 증감이 '0만명' 이 된다 (KOS-36 M5-1)"""
        calc_d = job.displays.get(c.display_ref) if c.display_ref else None
        if chart_d is not None and c.op in POINT_VALUE_OPS and (calc_d is None or calc_d.source_unit == chart_d.source_unit):
            return chart_d
        return calc_d if calc_d is not None else chart_d

    for c in calcs:
        d = disp(c)
        if c.op == "rank":
            firsts = [e for e in c.value if isinstance(e, dict) and e.get("rank") == 1] if isinstance(c.value, list) else []
            for e in firsts:
                if p := pts.find(e.get("key") or {}, _item(c)):
                    notes.append(([p], p, f"1위 {p[2]} {fmt(e.get('value'), d)}"))
        elif c.op == "extreme":
            entries = ([(e.get("key") or {}, e.get("value")) for e in c.value if isinstance(e, dict)] if isinstance(c.value, list)
                       else [(i.key, i.value) for i in c.inputs if i.value == c.value])
            for key, v in entries:
                if p := pts.find(key, _item(c)):
                    notes.append(([p], p, f"{_extreme_name(pts, p)} {p[2]} {fmt(v, d)}"))
        elif isinstance(c.value, list):                 # 범주별 증감 · 차이 목록 → 가장 크게 증가 · 감소
            vals = [e for e in c.value if isinstance(e, dict) and not is_missing(e.get("value"))]
            picks = []
            if vals:
                hi, lo = max(vals, key=lambda e: e["value"]), min(vals, key=lambda e: e["value"])
                if len(vals) == 1:
                    picks = [(hi, OP_NAME[c.op])]
                else:
                    picks = ([(hi, "가장 크게 증가")] if hi["value"] > 0 else []) + ([(lo, "가장 크게 감소")] if lo["value"] < 0 else [])
            for e, name in picks:
                if p := pts.find(e.get("key") or {}, _item(c)):
                    notes.append(([p], p, f"{name} {p[2]} {_signed(e['value'], d)}"))
        else:                                           # 기간 증감 하나 → 처음 · 끝 점
            if c.op == "growth_rate" and id(c) in used_rates:
                continue
            keys = list({tuple(sorted(i.key.items())): i.key for i in c.inputs}.values())
            found = [p for k in (keys[:1] + keys[-1:] if len(keys) > 1 else keys) if (p := pts.find(k, _item(c)))]
            if not found:
                warns.append(f"강조 생략: {c.step_id} {c.op} (차트에서 계산에 쓴 점을 찾지 못함)")
                continue
            text = (f"{found[0][2]}→{found[-1][2]} " if len(found) > 1 else "") + _signed(c.value, d)
            if c.op == "change" and (r := rate_by_rec.get(tuple(sorted(c.record_ids)))) is not None:
                text += f" ({_signed(r.value, disp(r))})"
                used_rates.add(id(r))
            elif c.op != "change":
                text = f"{OP_NAME[c.op]} {text}"
            notes.append((found, found[-1], text))
    return notes, warns


def _item(c):
    return next((i.item for i in c.inputs if i.item), None)


def _extreme_name(pts, p):
    t = pts.fig.data[p[0]]
    vals = [v for v in (t.x if pts.h else t.y) if not is_missing(v)]
    v = pts.value(p[0], p[1])
    return "최댓값" if v >= max(vals) else "최솟값" if v <= min(vals) else "극값"


def highlight(fig, job):
    """fig 에 계산 강조를 더한다 (fig 를 바꾼다) → 경고 목록"""
    if not job.calcs or job.chart_type not in HIGHLIGHT_TYPES or not fig.data:
        return []
    pts = _Points(fig, job.content)
    notes, warns = _notes(job, pts)
    merged = {}                                         # 같은 점의 주석은 하나로 ('최댓값 경기도 …' + '1위 경기도 …' → 두 줄)
    for points, at, text in notes:
        k = (at[0], at[1])
        if k not in merged:
            if len(merged) >= MAX_NOTES:
                continue
            merged[k] = (list(points), at, [])
        else:
            merged[k][0].extend(points)
        if text not in merged[k][2]:
            merged[k][2].append(text)
    for points, at, texts in merged.values():
        for p in points:
            _emphasize(fig, p[0], p[1])
        _annotate(fig, pts, at[0], at[1], at[2], "<br>".join(texts))
    return warns
