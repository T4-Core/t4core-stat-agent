"""Chart-Data Fidelity (criteria.md 5장 M5)

figure(Plotly JSON)와 ChartContent 를 같은 정규형 셀 {(series, category): value} 로 바꿔 비교한다.
figure 값은 v / unit_scale 이고 반올림하지 않으므로 비교는 (b)층: 기대 원값 / unit_scale 과 rtol=1e-9.
렌더러 표현(draw_chart_renderers.py)
  line · area · bar · stacked_bar · combo : Scatter/Bar x · y (가로 막대는 x=값, y=범주)
  pyramid : 가로 Bar, x = sign × v (첫 group 은 음수) → 부호 제거
  pie · donut : labels · values        treemap : ids · parents · values (잎만)
  radar : r · theta (닫힘 점 1개 중복) map : 시도 타일 격자 Heatmap z (SIDO_TILES 배치)
  heatmap : x · y · z 2차원            scatter · bubble : 점 레이블 customdata[0], x · y, bubble size = abs(v) (배율 없음)
  dumbbell : 연결선 trace(첫 번째, 비교 제외) + start · end 점 trace (x=값, y=범주)
강조(highlight)는 annotation 만 더하고 trace 를 추가하지 않는다. 겹쳐 그린 차트(merged_from)는 unsupported.
"""
import base64
import math
from dataclasses import dataclass, field

from backend.agent.draw_chart.draw_chart_module.draw_chart_renderers import SIDO_TILES, sido_short

SUPPORTED = {"line", "area", "bar", "stacked_bar", "combo", "pyramid", "pie", "donut", "treemap", "radar", "map",
             "heatmap", "scatter", "bubble", "dumbbell"}
RTOL = 1e-9
_DTYPES = {"f8": "d", "f4": "f", "i4": "i", "i8": "q", "i2": "h", "i1": "b", "u1": "B", "u2": "H", "u4": "I", "u8": "Q"}


def arr(v):
    """plotly 6 의 typed array ({dtype, bdata[, shape]}) 를 list 로"""
    if isinstance(v, dict) and "bdata" in v:
        import array
        a = array.array(_DTYPES[v["dtype"]])
        a.frombytes(base64.b64decode(v["bdata"]))
        out = a.tolist()
        if v.get("shape"):
            shape = [int(x) for x in str(v["shape"]).split(",")]
            if len(shape) == 2:
                out = [out[i * shape[1]:(i + 1) * shape[1]] for i in range(shape[0])]
        return out
    if isinstance(v, (list, tuple)):
        return [arr(x) for x in v]
    return v


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


@dataclass
class Fidelity:
    chart_id: str
    chart_type: str
    status: str                       # ok · mismatch · unsupported · no_figure
    missing: list = field(default_factory=list)
    extra: list = field(default_factory=list)
    diff: list = field(default_factory=list)

    @property
    def ok(self) -> bool | None:
        return None if self.status in ("unsupported", "no_figure") else self.status == "ok"


def _display_for(content: dict, displays: dict, role: str | None = None) -> dict | None:
    spec = (content.get("axis") or {}).get(role) if role else None
    ref = ((spec or {}).get("display_ref")) or (content.get("options") or {}).get("display_ref")
    return displays.get(ref) if ref else None


def _scale(d: dict | None) -> float:
    return float((d or {}).get("unit_scale") or 1)


def expected(content: dict, displays: dict) -> dict:
    """ChartContent → {(series, category): figure 값(배율 적용)}"""
    t, enc = content["chart_type"], content.get("encoding") or {}
    cols = content.get("columns") or []
    rows = [dict(zip(cols, r)) for r in content.get("rows") or []]
    s = lambda v: None if v is None else str(v)  # noqa: E731
    out: dict = {}

    def put(series, cat, v, d):
        n = _num(v)
        out[(series, cat)] = None if n is None else n / _scale(d)

    if t in ("line", "area", "bar", "stacked_bar"):
        d = _display_for(content, displays, "y")
        for r in rows:
            put(s(r.get(enc.get("series"))) if enc.get("series") else None, s(r[enc["x"]]), r[enc["y"]], d)
    elif t == "combo":
        axis_of = (content.get("options") or {}).get("series_axis") or {}
        for r in rows:
            name = s(r.get(enc.get("series"))) if enc.get("series") else None
            put(name, s(r[enc["x"]]), r[enc["y"]], _display_for(content, displays, axis_of.get(name) or "y"))
    elif t == "pyramid":
        d = _display_for(content, displays, "x")
        for r in rows:
            put(s(r[enc["group"]]), s(r[enc["y"]]), r[enc["value"]], d)
    elif t in ("pie", "donut"):
        d = _display_for(content, displays)
        for r in rows:
            put(None, s(r[enc["label"]]), r[enc["value"]], d)
    elif t == "treemap":
        d = _display_for(content, displays)
        p = enc.get("parent")
        for r in rows:
            n = _num(r[enc["value"]])
            out[(s(r[p]) if p else None, s(r[enc["label"]]))] = 0.0 if n is None else n / _scale(d)
    elif t == "radar":
        d = _display_for(content, displays)
        for r in rows:
            put(s(r.get(enc.get("series"))) if enc.get("series") else None, s(r[enc["label"]]), r[enc["value"]], d)
    elif t == "map":
        d = _display_for(content, displays)
        for r in rows:
            key = sido_short(r[enc["region"]])
            if key in SIDO_TILES and _num(r[enc["value"]]) is not None:
                put(None, key, r[enc["value"]], d)
    elif t == "heatmap":
        d = _display_for(content, displays, "x") or _display_for(content, displays, "y")
        for r in rows:
            put(None, (s(r[enc["y"]]), s(r[enc["x"]])), r[enc["value"]], d)
    elif t in ("scatter", "bubble"):
        dx, dy = _display_for(content, displays, "x"), _display_for(content, displays, "y")
        for r in rows:
            vals = [_num(r[enc["x"]]), _num(r[enc["y"]])] + ([_num(r[enc["size"]])] if t == "bubble" else [])
            if any(v is None for v in vals):
                continue                                  # 렌더러도 값이 빠진 점은 뺀다
            series = s(r.get(enc.get("series"))) if enc.get("series") else None
            label = s(r[enc["label"]]) if enc.get("label") else ""
            point = (vals[0] / _scale(dx), vals[1] / _scale(dy)) + ((abs(vals[2]),) if t == "bubble" else ())
            out[(series, label)] = point
    elif t == "dumbbell":
        d = _display_for(content, displays, "x")
        for r in rows:
            put(str(enc["start"]), s(r[enc["label"]]), r[enc["start"]], d)
            put(str(enc["end"]), s(r[enc["label"]]), r[enc["end"]], d)
    return out


def observed(figure: dict, chart_type: str, single_series: bool) -> dict:
    data = [{k: arr(v) for k, v in tr.items()} for tr in (figure or {}).get("data") or []]
    out: dict = {}
    t = chart_type
    name = lambda tr: None if single_series else (str(tr.get("name")) if tr.get("name") is not None else None)  # noqa: E731
    if t in ("line", "area", "bar", "stacked_bar", "combo"):
        for tr in data:
            xs, ys = tr.get("x") or [], tr.get("y") or []
            if tr.get("orientation") == "h":
                xs, ys = ys, xs
            for x, y in zip(xs, ys):
                out[(name(tr), str(x))] = _num(y)
    elif t == "pyramid":
        for tr in data:
            for c, v in zip(tr.get("y") or [], tr.get("x") or []):
                n = _num(v)
                out[(str(tr.get("name")), str(c))] = None if n is None else abs(n)
    elif t in ("pie", "donut"):
        tr = data[0] if data else {}
        for lb, v in zip(tr.get("labels") or [], tr.get("values") or []):
            out[(None, str(lb))] = _num(v)
    elif t == "treemap":
        tr = data[0] if data else {}
        ids, parents, labels, values = (tr.get(k) or [] for k in ("ids", "parents", "labels", "values"))
        parent_ids = {p for p in parents if p}
        for i, lb, v, p in zip(ids, labels, values, parents):
            if i in parent_ids:
                continue
            out[(p[3:] if p else None, str(lb))] = _num(v) or 0.0
    elif t == "radar":
        for tr in data:
            r, th = list(tr.get("r") or []), list(tr.get("theta") or [])
            if len(th) > 1 and th[-1] == th[0]:
                r, th = r[:-1], th[:-1]
            for a, v in zip(th, r):
                out[(name(tr), str(a))] = _num(v)
    elif t == "map":
        tr = data[0] if data else {}
        z = tr.get("z") or []
        pos = {v: k for k, v in SIDO_TILES.items()}
        for ri, line in enumerate(z):
            for ci, v in enumerate(line or []):
                if _num(v) is not None and (ci, ri) in pos:
                    out[(None, pos[(ci, ri)])] = _num(v)
    elif t == "heatmap":
        tr = data[0] if data else {}
        for yi, y in enumerate(tr.get("y") or []):
            for xi, x in enumerate(tr.get("x") or []):
                v = ((tr.get("z") or [])[yi] or [None])[xi] if yi < len(tr.get("z") or []) else None
                out[(None, (str(y), str(x)))] = _num(v)
    elif t in ("scatter", "bubble"):
        for tr in data:
            xs, ys, cd = tr.get("x") or [], tr.get("y") or [], tr.get("customdata") or []
            size = (tr.get("marker") or {}).get("size")
            for i, (x, y) in enumerate(zip(xs, ys)):
                label = str(cd[i][0]) if i < len(cd) and isinstance(cd[i], (list, tuple)) else ""
                pt = (_num(x), _num(y)) + ((abs(_num(size[i])),) if t == "bubble" and isinstance(size, list) else ())
                out[(name(tr), label)] = pt
    elif t == "dumbbell":
        for tr in data[1:]:                               # data[0] = 연결선
            for v, c in zip(tr.get("x") or [], tr.get("y") or []):
                out[(str(tr.get("name")), str(c))] = _num(v)
    return out


def _close(a, b) -> bool:
    if isinstance(a, tuple) or isinstance(b, tuple):
        return isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= RTOL * max(abs(a), abs(b), 1e-12)


def compare(content: dict, displays: dict, drawn: dict | None) -> Fidelity:
    cid, t = content.get("chart_id"), content.get("chart_type")
    if t not in SUPPORTED:
        return Fidelity(cid, t, "unsupported")
    if not drawn or not drawn.get("figure"):
        return Fidelity(cid, t, "no_figure")
    if drawn.get("merged_from"):
        return Fidelity(cid, t, "unsupported")
    enc = content.get("encoding") or {}
    single = t in ("line", "area", "bar", "stacked_bar", "radar") and not enc.get("series") or \
        t in ("scatter", "bubble") and not enc.get("series")
    exp, obs = expected(content, displays), observed(drawn["figure"], t, single)
    if t == "combo" and not enc.get("series"):
        obs = {(None, k[1]): v for k, v in obs.items()}
    f = Fidelity(cid, t, "ok")
    for k, v in exp.items():
        if k not in obs:
            if v is not None:
                f.missing.append(str(k))
        elif not _close(v, obs[k]):
            f.diff.append({"cell": str(k), "expected": v, "observed": obs[k]})
    f.extra = [str(k) for k, v in obs.items() if k not in exp and v is not None]
    if f.missing or f.extra or f.diff:
        f.status = "mismatch"
    return f
