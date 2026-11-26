"""
모듈 5 겹쳐 그리기 — 2번 chart_plan.overlays 의 차트들을 그림 하나로 합친 차트를 더한다

  apply_overlays(results, jobs, overlays) → results (합친 차트를 맨 앞에 + 원래 차트 그대로)

  - 원래 차트(c1, c2 …)는 그대로 두고, 합친 차트(chart_id "c1+c2…", merged_from ["c1", "c2", …])를 더한다
  - [CHANGED 11-25 5단계] 합친 차트는 결과 목록의 **맨 앞**에 둔다 (overlays 순서). 답변 화면은 결과 순서대로 차트를 보여 주므로
    사용자가 합친 차트를 가장 먼저 본다. 이전: 두 차트 바로 뒤에 넣었다
  - 차트가 모두 drawn 이고 짝이 맞을 때만 합친다. 아니면 합치지 않고 첫 차트 경고에 이유를 남긴다
  - 합친 ChartContent 를 만들어 기존 렌더러(draw_chart)로 그린다
      combo   : 큰 값 막대(y, 왼쪽 축) + 작은 값 선(y2, 오른쪽 축)  ← overlays[].axes   (차트 2개)
      lines   : line 하나에 선 N개   /   bars : 묶음 막대 하나 (막대 N개)   — x 값이 정확히 같아야 한다
      [NEW 11-25] 사용자가 요청한 관계 차트 — 하위질문마다 지표 하나씩인 차트들을 **범주 이름으로 짝지어** 만든다
      scatter : c1 값 = x, c2 값 = y, 범주 = 점 이름                 ← overlays[].axes {c1: x, c2: y}
      bubble  : c1 = x, c2 = y, c3 = 원 크기                         ← overlays[].axes {c1: x, c2: y, c3: size}
      radar   : 차트(지표)마다 축 하나, 범주마다 다각형 하나 (단위가 같은 지표만 — 모듈 2 가 확인)
      짝짓기: 지역 열이면 검색 쪽 지역 이름 표준화(backend.rag.ingestion.normalize.std_geo_name, 읽기만)로 맞춘다
              ('강원도' ↔ '강원특별자치도'). 한 차트에 표준 이름이 같은 범주가 둘이면 이름이 표준 이름과 같은 행을 쓴다
              ('세종특별자치시' · '세종시' → 세종특별자치시). 모든 차트에 값이 있는 범주만 남기고, 뺀 범주는 경고로 알린다
  3번 모듈은 이 표시를 모른다 (2번이 chart_plan.overlays 에 남기고 5번만 읽는다).
"""
from backend.agent.chart_calculate.select import REGION_HINTS
from backend.schemas.chart import AxisSpec, ChartContent

from .draw_chart_format import SERIES_COLORS, is_missing
from .draw_chart_prepare import display_refs_of
from .draw_chart_schema import DRAWN, DrawJob
from .draw_chart_tool import draw_chart

ITEM, VALUE = "항목", "값"
RELATION_MODES = ("scatter", "bubble", "radar")
MIN_POINTS = {"scatter": 5, "bubble": 3, "radar": 1}     # 짝지은 범주가 이보다 적으면 합치지 않는다 (산점도는 모듈 3 min_points_5 와 같음)
_NOT_INHERITED = {False: ("표시 자릿수",), True: ("표시 자릿수", "대체됨")}     # 합친 차트가 물려받지 않는 원래 차트 경고 (관계 차트 여부)


def _label(c):
    """차트의 지표 이름: 계열 값이 하나면 그 값 ('혼인건수'), 아니면 y 축 이름, 없으면 항목 열의 값(하나일 때), 없으면 제목"""
    s = c.encoding.get("series")
    if s and s in c.columns:
        vals = list(dict.fromkeys(str(r[c.columns.index(s)]) for r in c.rows))
        if len(vals) == 1:
            return vals[0]
    y = c.axis.get("y")
    if y and y.label:
        return y.label
    if ITEM in c.columns:
        vals = list(dict.fromkeys(str(r[c.columns.index(ITEM)]) for r in c.rows))
        if len(vals) == 1:
            return vals[0]
    return c.title


def _labels(contents):
    """차트마다 지표 이름. 겹치면 제목, 그래도 겹치면 chart_id 를 붙인다"""
    names = [_label(c) for c in contents]
    if len(set(names)) < len(names):
        names = [c.title for c in contents]
    if len(set(names)) < len(names):
        names = [f"{n} ({c.chart_id})" for n, c in zip(names, contents)]
    return names


def _title(contents, names, sep):
    """첫 차트 제목의 지표 이름을 합친 이름으로 ('2024년 시도별 출생아수' → '2024년 시도별 출생아수·사망자수')"""
    base = contents[0].title
    return base.replace(names[0], "·".join(names)) if names[0] in base else sep.join(names)


def _points(c):
    """(x 열 이름, [(x 값, y 값), …])"""
    x, y = c.encoding.get("x"), c.encoding.get("y")
    if not x or not y or x not in c.columns or y not in c.columns:
        raise ValueError(f"{c.chart_id}: x·y 역할이 없는 차트")
    xi, yi = c.columns.index(x), c.columns.index(y)
    return x, [(str(r[xi]), r[yi]) for r in c.rows]


def _record_ids(contents):
    return list(dict.fromkeys(i for c in contents for i in c.record_ids))


def _same_x(ov, contents):
    """combo · lines · bars: x 값이 정확히 같은 차트들 → 합친 ChartContent"""
    pts = [_points(c) for c in contents]
    xa = pts[0][0]
    xs = [list(dict.fromkeys(x for x, _ in p)) for _, p in pts]
    if any(x != xs[0] for x in xs[1:]):
        raise ValueError(f"차트들의 x 값이 다름 ({' · '.join(f'{len(x)}개' for x in xs)})")
    names = _labels(contents)
    rows = [[x, n, v] for n, (_, p) in zip(names, pts) for x, v in p]
    first = contents[0]
    xspec = first.axis.get("x") or AxisSpec(label=xa)
    title = _title(contents, names, " · ")        # 차트 2개는 이전과 같은 제목 ('출생아수·합계출산율')

    if ov["mode"] == "combo":
        if len(contents) != 2:
            raise ValueError(f"combo 는 차트 2개만 합친다 ({len(contents)}개)")
        ca, cb = contents
        la, lb = names
        y_id = next((k for k, v in (ov.get("axes") or {}).items() if v == "y"), ca.chart_id)
        (cy, ly), (cy2, ly2) = ((ca, la), (cb, lb)) if y_id == ca.chart_id else ((cb, lb), (ca, la))
        # 원래 차트의 축 범위(min · max)는 그 차트 값 기준이라 지운다 → 합친 차트의 기준선 규칙(막대는 0 포함)이 적용됨
        ya = (cy.axis.get("y") or AxisSpec()).model_copy(update={"label": ly, "min": None, "max": None})
        yb = (cy2.axis.get("y") or AxisSpec()).model_copy(update={"label": ly2, "min": None, "max": None})
        return ChartContent(chart_id=ov["overlay_id"], chart_type="combo", measure=ca.measure, title=title,
                            encoding={"x": xa, "y": VALUE, "y2": VALUE, "series": ITEM},
                            axis={"x": xspec, "y": ya, "y2": yb},
                            options={"marks": {"y": "bar", "y2": "line"}, "series_axis": {ly: "y", ly2: "y2"}},
                            columns=[xa, ITEM, VALUE], rows=rows, record_ids=_record_ids(contents), warnings=[])

    # 한 차트의 축 범위로 고정하면 다른 차트 값이 화면 밖으로 나갈 수 있어 min · max 를 지운다
    yspec = (first.axis.get("y") or AxisSpec()).model_copy(update={"label": " · ".join(names), "min": None, "max": None})
    return ChartContent(chart_id=ov["overlay_id"], chart_type="line" if ov["mode"] == "lines" else "bar",
                        measure=first.measure, title=title, encoding={"x": xa, "y": VALUE, "series": ITEM},
                        axis={"x": xspec, "y": yspec}, options={} if ov["mode"] == "lines" else {"orientation": "vertical"},
                        columns=[xa, ITEM, VALUE], rows=rows, record_ids=_record_ids(contents), warnings=[])


# ── 관계 차트 (scatter · bubble · radar): 범주 이름으로 짝짓기 ─────────────────
def _category_values(c):
    """(범주 열 이름, [(범주 값, 값), …]) — 막대 · 선(x · y), 원 · 도넛 · 트리맵 · 레이더(label · value), 지도(region · value)"""
    enc = c.encoding
    for cat_role, val_role in (("x", "y"), ("label", "value"), ("region", "value")):
        k, v = enc.get(cat_role), enc.get(val_role)
        if k and v and k in c.columns and v in c.columns:
            s = enc.get("series")
            if s and s in c.columns and len({str(r[c.columns.index(s)]) for r in c.rows}) > 1:
                raise ValueError(f"{c.chart_id}: 계열이 여러 개라 범주로 짝지을 수 없음")
            ki, vi = c.columns.index(k), c.columns.index(v)
            return k, [(str(r[ki]), r[vi]) for r in c.rows]
    raise ValueError(f"{c.chart_id}: 범주 · 값 역할이 없는 차트 ({c.chart_type})")


def _canon(col, name):
    """범주 이름 → 짝짓는 이름. 지역 열이면 검색 쪽 표준 이름 ('강원도' → '강원특별자치도', '서울' → '서울특별시')"""
    name = name.strip()
    if any(h in col for h in REGION_HINTS):
        from backend.rag.ingestion.normalize import std_geo_name     # 읽기만 (처음 부를 때 불러온다)
        return std_geo_name(name)
    return name


def _by_category(c):
    """차트 하나 → (범주 열, {짝짓는 이름: 값}, 경고). 짝짓는 이름이 같은 범주가 둘 이상이면 이름이 그대로인 행을 쓴다"""
    col, pairs = _category_values(c)
    groups: dict[str, list] = {}
    for name, v in pairs:
        groups.setdefault(_canon(col, name), []).append((name, v))
    out, warns = {}, []
    for key, items in groups.items():
        name, v = next((it for it in items if it[0] == key), items[0])
        out[key] = v
        if len(items) > 1:
            warns.append(f"같은 범주로 보이는 {', '.join(n for n, _ in items)} 중 '{name}' 값만 사용")
    return col, out, warns


def _value_spec(c, label):
    """원래 차트의 값 축(표시 설정 포함) → 합친 차트의 축 하나. 축이 없는 차트는 options.display_ref 로 만든다"""
    spec = c.axis.get("y") or AxisSpec(type="numeric", display_ref=c.options.get("display_ref"))
    return spec.model_copy(update={"label": label, "min": None, "max": None})


def _display_ref(c):
    y = c.axis.get("y")
    return (y.display_ref if y else None) or c.options.get("display_ref")


def _relation(ov, contents):
    """scatter · bubble · radar → (합친 ChartContent, 경고)"""
    mode = ov["mode"]
    roles = ov.get("axes") or {}
    if mode in ("scatter", "bubble"):        # axes 의 역할 순서대로 (x → y → size)
        order = {"x": 0, "y": 1, "size": 2}
        contents = sorted(contents, key=lambda c: order.get(roles.get(c.chart_id), 9))
    names = _labels(contents)
    cols, tables, seen = [], [], {}
    for c in contents:
        col, t, w = _by_category(c)
        cols.append(col)
        tables.append(t)
        for x in w:                          # 같은 경고는 한 번만 (어느 차트인지 뒤에)
            seen.setdefault(x, []).append(c.chart_id)
    warns = [f"{x} ({', '.join(ids)})" for x, ids in seen.items()]
    keys = [k for k in tables[0] if all(k in t and not is_missing(t[k]) for t in tables)]
    dropped = [k for k in dict.fromkeys(k for t in tables for k in t) if k not in keys]
    if dropped:
        warns.append(f"모든 차트에 값이 있지 않은 범주 {len(dropped)}개는 빼고 그림: {', '.join(dropped)}")
    if len(keys) < MIN_POINTS[mode]:
        raise ValueError(f"차트들에 공통으로 있는 범주가 {len(keys)}개뿐 ({MIN_POINTS[mode]}개 이상 필요)")
    cat = cols[0]
    first = contents[0]
    title = _title(contents, names, " · ")
    if mode == "radar":
        rows = [[k, n, t[k]] for n, t in zip(names, tables) for k in keys]
        return ChartContent(chart_id=ov["overlay_id"], chart_type="radar", measure=first.measure, title=title,
                            encoding={"label": ITEM, "series": cat, "value": VALUE}, axis={},
                            options={"display_ref": _display_ref(first)} if _display_ref(first) else {},
                            columns=[cat, ITEM, VALUE], rows=rows, record_ids=_record_ids(contents), warnings=[]), warns
    rows = [[k, *(t[k] for t in tables)] for k in keys]
    enc = {"x": names[0], "y": names[1], "label": cat}
    options = {}
    if mode == "bubble":
        enc["size"] = names[2]
        if ref := _display_ref(contents[2]):
            options["display_ref"] = ref
    return ChartContent(chart_id=ov["overlay_id"], chart_type=mode, measure=first.measure, title=title,
                        encoding=enc, axis={"x": _value_spec(contents[0], names[0]), "y": _value_spec(contents[1], names[1])},
                        options=options, columns=[cat, *names], rows=rows, record_ids=_record_ids(contents),
                        warnings=[]), warns


def merge_content(ov, *contents):
    """overlay 하나 + 차트들의 ChartContent(overlays[].charts 순서) → 합친 ChartContent. 합칠 수 없으면 ValueError
    [CHANGED 11-25] 이전: merge_content(ov, ca, cb) 두 차트만. 지금도 같은 호출이 그대로 된다"""
    content, _ = merge_with_warnings(ov, *contents)
    return content


def merge_with_warnings(ov, *contents):
    """merge_content + 짝짓기 경고 (관계 차트에서 뺀 범주 · 중복 범주)"""
    if len(contents) < 2:
        raise ValueError(f"합칠 차트가 {len(contents)}개")
    if ov.get("mode") in RELATION_MODES:
        return _relation(ov, list(contents))
    return _same_x(ov, list(contents)), []


def _color(res):
    """그린 차트의 첫 trace 색 (선이면 선 색, 막대면 막대 색)"""
    if res.figure is None or not res.figure.data:
        return None
    t = res.figure.data[0]
    c = t.marker.color if t.type == "bar" else (t.line.color or t.marker.color)
    return c if isinstance(c, str) else None


def _colors(ov, content, results):
    """합친 차트의 trace 색. 선 · 막대 · 콤보 = 원래 차트 색 그대로 (rows 는 차트 순서), 산점도 · 버블 = 첫 차트 색,
    레이더 = 범주(다각형)마다 팔레트 순서"""
    if ov["mode"] == "radar":
        cats = list(dict.fromkeys(str(r[0]) for r in content.rows))
        return {n: SERIES_COLORS[i % len(SERIES_COLORS)] for i, n in enumerate(cats)}
    if ov["mode"] in ("scatter", "bubble"):
        col = _color(results[0])
        return {content.encoding["y"]: col} if col else {}
    names = list(dict.fromkeys(str(r[1]) for r in content.rows))
    return {n: col for n, col in zip(names, (_color(r) for r in results)) if col}


def apply_overlays(results, jobs, overlays):
    """results(ChartPlan 순서) 앞에 합친 차트를 더한다 (overlays 순서). 원래 차트는 그대로 둔다"""
    merged = []
    by_id = {r.chart_id: r for r in results}
    jobs_by = {j.chart_id: j for j in jobs or []}
    for ov in overlays or []:
        ids = list(ov.get("charts") or [])
        rs = [by_id.get(i) for i in ids]

        def skip(why):
            target = next((r for r in rs if r is not None), None)
            if target is not None:
                target.warnings.append(f"{ov.get('overlay_id')} 겹쳐 그리기 생략: {why}")

        if len(ids) < 2 or any(r is None for r in rs):
            skip("겹칠 차트가 결과에 없음")
            continue
        if any(r.status != DRAWN for r in rs):
            skip("그리지 못한 차트가 있음 (" + " · ".join(f"{i} {r.status}" for i, r in zip(ids, rs)) + ")")
            continue
        js = [jobs_by.get(i) for i in ids]
        try:
            content, warns = merge_with_warnings(ov, *(j.content for j in js))
        except (ValueError, AttributeError) as e:
            skip(str(e))
            continue
        job = DrawJob(chart_id=ov["overlay_id"], sub_question_ids=list(dict.fromkeys(s for j in js for s in j.sub_question_ids)),
                      planned_type="overlay", chart_type=content.chart_type, content=content,
                      displays={k: v for j in js for k, v in j.displays.items()}, display_refs=display_refs_of(content),
                      source_links=list({l["url"]: l for j in js for l in j.source_links}.values()),
                      # 원래 차트 경고를 물려받되, 자릿수 보정 경고는 합친 차트에서 축마다 다시 계산하므로 뺀다.
                      # [NEW 11-25] 관계 차트는 '대체됨'(원래 차트가 막대로 바뀐 이야기)도 뺀다 — 합친 차트가 요청한 차트다.
                      #   모듈 2 의 '요청한 {유형} 차트를 그릴 수 없음' 도 합친 차트가 바로 그 유형이면 뺀다 (콤보 포함)
                      warnings=[w for w in dict.fromkeys(w for r in rs for w in r.warnings)
                                if not w.startswith(_NOT_INHERITED[ov.get("mode") in RELATION_MODES])
                                and not w.startswith(f"요청한 {content.chart_type} 차트를 그릴 수 없음")] + warns,
                      colors=_colors(ov, content, rs))
        res = draw_chart(job)
        res.merged_from = ids
        if res.status != DRAWN:
            skip(res.reason or res.status)
            continue
        merged.append(res)
    return merged + list(results)        # [CHANGED 11-25] 합친 차트가 맨 앞 (이전: 두 차트 바로 뒤)
