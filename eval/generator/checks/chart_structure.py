"""[NEW] 차트 구조 판정: 요구 결과 · 조건(의미) · 표시 · 좌표 포함 (criteria.md 차트 판정)

  ① chart_outcome       v2 required · fallback · per_subquestion: 요구한 종류로 그렸는가 (못 그렸으면 고지했는가)
  ② chart_requirement   v2 required_chart.requirements 코드를 **정답 좌표(claim binding)** 와 대조해 다시 판정한다
  ③ chart_visible       그린 차트의 수치가 고정 축 범위 안에 있고, y2 역할이 있으면 보조축 계열이 있다 (모든 세트)
  ④ chart_covers_final  차트가 맡은 하위 질문의 FINAL 좌표가 chart_contents 행에 모두 있다
  ⑤a chart_answer_consistent  차트가 그려졌는데 답변이 '계산 결과 없음'이면 모순이다 (1단계). 기대 상태가 answer인 문항 (judge_rules >= 3)
  ⑤b chart_forbidden_drawn    데이터셋이 차트 금지(forbidden)로 둔 문항에서 차트가 그려졌다 (2단계 보류). v2 forbidden 문항 (judge_rules >= 3)

Generator 도 같은 코드(chart_calculate/specs.py · validate.check_chart)로 자체 검증하지만 형태만 본다.
예: dumbbell two_points_per_category 는 '범주마다 점 2개' 만 보므로 범주와 비교 쌍이 뒤바뀌어도 통과한다.
여기서는 같은 코드를 정답 좌표 기준의 의미로 판정한다 (구현은 Generator 코드와 독립).

판정 규칙 버전(judge_rules): ①~④는 2 이상, ⑤는 3 이상인 실행에만 적용한다. 이전 실행은 다시 판정하지 않는다.
"""
import re
from collections import defaultdict

from eval.generator import CHART_CONSISTENCY_RULES, CHART_STRUCTURE_RULES, trace
from eval.generator.binding import region_key
from eval.generator.checks import chart_request
from eval.generator.checks.chart_request import _final_types
from eval.generator.claim import period_key
from eval.generator.findings import Finding
from eval.generator.schema import Question

CODES = ("chart_outcome", "chart_requirement", "chart_visible", "chart_covers_final", "chart_answer_consistent", "chart_forbidden_drawn")
STAGE2 = ("chart_outcome", "chart_covers_final", "chart_forbidden_drawn")
# 범주 수(max/min_categories_N)를 세는 역할
CATEGORY_ROLE = {"bar": "x", "stacked_bar": "x", "line": "x", "area": "x", "combo": "x", "pie": "label", "donut": "label",
                 "radar": "label", "map": "region", "pyramid": "y", "dumbbell": "label", "treemap": "label", "heatmap": "y"}
_PAREN = re.compile(r"^(?P<item>.*?)\s*\((?P<val>[^()]+)\)$")
_COUNT = re.compile(r"^(max|min)_(categories|points)_(\d+)$")
_TIME_COLS = {"시점", "연도", "월", "분기"}
_SKIP_DIMS = {"기준"}                      # 척도 설명 같은 상수 차원은 좌표 대조에서 뺀다


def applies(run: dict, minimum: int = CHART_STRUCTURE_RULES) -> bool:
    return int(run.get("judge_rules") or 1) >= minimum


# ── 좌표 ──────────────────────────────────────────────────────────
def _core(s) -> str:
    return re.sub(r"\s+", "", re.sub(r"\(.*?\)$", "", str(s)).replace("합성", ""))


def _norm(dim: str, v) -> str:
    if dim == "지역":
        return region_key(str(v)) or str(v)
    if dim == "시점":
        return period_key(str(v)) or str(v)
    if dim == "항목":
        return _core(v)
    return str(v).strip()


def col_dim(col: str) -> str:
    c = str(col)
    if c in _TIME_COLS:
        return "시점"
    if "지역" in c or c in ("시도", "시군구", "행정구역"):
        return "지역"
    return c


def gold_dims(values) -> dict[str, set[str]]:
    """FINAL 정답 claim 의 좌표 → {차원: 값 집합}"""
    out: dict[str, set[str]] = defaultdict(set)
    for vs in values:
        b = vs.binding
        if b is None:
            continue
        for r in b.regions():
            out["지역"].add(_norm("지역", r))
        for p in [b.period] if isinstance(b.period, str) else list(b.period or []):
            out["시점"].add(_norm("시점", p))
        if b.item:
            out["항목"].add(_norm("항목", b.item))
        for k, v in b.dims().items():
            if k not in _SKIP_DIMS:
                out[k].add(_norm(k, v))
    return dict(out)


def gold_coords(values) -> list[dict[str, str]]:
    out = []
    for vs in values:
        b = vs.binding
        if b is None:
            continue
        c = {}
        if b.regions():
            c["지역"] = _norm("지역", b.regions()[0])
        per = b.period if isinstance(b.period, str) else (b.period or [None])[0]
        if per:
            c["시점"] = _norm("시점", per)
        if b.item:
            c["항목"] = _norm("항목", b.item)
        c.update({k: _norm(k, v) for k, v in b.dims().items() if k not in _SKIP_DIMS})
        out.append(c)
    return out


def _dim_of_value(v: str, gold: dict[str, set[str]]) -> str | None:
    hits = [d for d, vals in gold.items() if any(_norm(d, v) == g for g in vals)]
    return hits[0] if len(hits) == 1 else None


def _role_dim(content: dict, role: str, gold: dict[str, set[str]]) -> str | None:
    """역할 → 차원. long 형식은 열 이름, joined 형식의 '항목 (값)' 열은 괄호 안 값의 차원"""
    col = (content.get("encoding") or {}).get(role)
    if col is None:
        return None
    m = _PAREN.match(str(col))
    if m:
        d = _dim_of_value(m.group("val"), gold)
        if d:
            return d
    return col_dim(col)


def _col_values(content: dict, col: str) -> list:
    cols = content.get("columns") or []
    if col not in cols:
        return []
    i = cols.index(col)
    return [r[i] for r in content.get("rows") or [] if i < len(r)]


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ── ② 조건 코드별 의미 검사: (content, gold) → (ok, 설명). ok=None 은 판정 불가 ──
def _multi(gold):
    return {d for d, v in gold.items() if len(v) >= 2}


def _two_points_per_category(c, gold):
    pair = [d for d in _multi(gold) if len(gold[d]) == 2 and d != "항목"]
    if len(pair) != 1:
        return None, f"정답에서 값이 2개인 차원을 하나로 정할 수 없음 {sorted(pair)}"
    pair = pair[0]
    start, end, label = (_role_dim(c, r, gold) for r in ("start", "end", "label"))
    want_label = sorted(_multi(gold) - {pair, "항목"})
    ok = start == end == pair and label != pair and (not want_label or label in want_label)
    return ok, (f"범주(label) {label} · 양 끝(start · end) {start}/{end} / 정답: 범주 {want_label or '-'}, "
                f"양 끝 {pair}({' · '.join(sorted(gold[pair]))})")


def _two_series(c, gold):
    enc = c.get("encoding") or {}
    col = enc.get("group") or enc.get("series")
    if not col:
        return False, "계열 역할(group · series) 없음"
    vals = {str(v) for v in _col_values(c, col)}
    d = col_dim(col)
    ok = len(vals) == 2 and (d not in gold or len(gold[d]) == 2)
    return ok, f"계열 {col}: 값 {len(vals)}개" + (f" / 정답 {d} {len(gold[d])}개" if d in gold else "")


def _time_axis(c, gold):
    d = _role_dim(c, "x", gold)
    return d == "시점", f"x 축 {d}"


def _category_axis(c, gold):
    role = CATEGORY_ROLE.get(c.get("chart_type"), "x")
    d = _role_dim(c, role, gold)
    series = col_dim((c.get("encoding") or {}).get("group") or (c.get("encoding") or {}).get("series") or "")
    want = sorted(_multi(gold) - {series, "항목", "시점"})
    return (d in want if want else None), f"범주 축({role}) {d} / 정답 범주 후보 {want}"


def _two_dimensions(c, gold):
    x, y = _role_dim(c, "x", gold), _role_dim(c, "y", gold)
    many = lambda d, role: (len(gold[d]) >= 2) if d in gold else len(set(map(str, _col_values(c, (c.get("encoding") or {}).get(role))))) >= 2  # noqa: E731
    return (x != y and many(x, "x") and many(y, "y")), f"x {x} · y {y}"


def _measures(n):
    def check(c, gold):
        enc = c.get("encoding") or {}
        roles = ("x", "y", "size")[:n]
        cols = [enc.get(r) for r in roles]
        if any(col is None for col in cols):
            return False, f"측정 역할 {roles} 중 빈 역할 {[r for r, col in zip(roles, cols) if col is None]}"
        items = {_core(col) for col in cols}
        want = gold.get("항목", set())
        return (len(items) == n and (not want or items == want)), f"{dict(zip(roles, cols))} / 정답 항목 {sorted(want)}"
    return check


def _region_dim(c, gold):
    d = _role_dim(c, "region", gold)
    return d == "지역", f"region 역할 {d}"


def _non_negative(c, gold):
    enc = c.get("encoding") or {}
    bad = [(r, v) for r in ("y", "value", "size", "start", "end") if enc.get(r)
           for v in _col_values(c, enc[r]) if _num(v) and v < 0]
    return not bad, f"음수 {bad[:3]}" if bad else "음수 없음"


def _parts_sum(c, gold):
    """구성 요소 합이 총계다(데이터셋 notes). share 면 묶음별 합 100, 원값이면 별도 합계 행 없이 충족"""
    if c.get("measure") != "share":
        return True, "원값 구성: 구성 요소 합을 총계로 봄"
    enc = c.get("encoding") or {}
    val = enc.get("value") or enc.get("y")
    grp = enc.get("x") if c.get("chart_type") == "stacked_bar" else None
    sums: dict = defaultdict(float)
    vals, keys = _col_values(c, val), _col_values(c, grp) if grp else None
    for i, v in enumerate(vals):
        if _num(v):
            sums[keys[i] if keys else None] += v
    bad = {k: round(s, 2) for k, s in sums.items() if abs(s - 100) > 0.05}
    return not bad, f"구성비 합 {bad or '모두 100'}"


def _count(kind, what, n):
    def check(c, gold):
        role = CATEGORY_ROLE.get(c.get("chart_type"), "x")
        col = (c.get("encoding") or {}).get(role)
        k = len({str(v) for v in _col_values(c, col)}) if col else len(c.get("rows") or [])
        ok = k <= n if kind == "max" else k >= n
        return ok, f"{'범주' if what == 'categories' else '점'} {k}개 ({kind} {n})"
    return check


CHECKS = {"two_points_per_category": _two_points_per_category, "two_series_required": _two_series,
          "time_axis_required": _time_axis, "category_axis_required": _category_axis,
          "two_dimensions_required": _two_dimensions, "two_measures_required": _measures(2),
          "three_measures_required": _measures(3), "region_dimension_required": _region_dim,
          "non_negative": _non_negative, "parts_sum_to_total": _parts_sum}


def requirement_check(code: str, content: dict, gold: dict[str, set[str]]) -> tuple[bool | None, str]:
    m = _COUNT.match(code)
    fn = _count(*m.groups()[:2], int(m.group(3))) if m else CHECKS.get(code)
    if fn is None:
        return None, f"알 수 없는 조건 {code} (판정하지 않음)"
    return fn(content, gold)


# ── ③ 표시 ────────────────────────────────────────────────────────
def visible_problems(content: dict | None, figure: dict) -> list[tuple[str, str]]:
    """[(모듈, 설명)]. 고정 축 범위 밖 수치 → M5. y2 역할이 있는데 보조축 계열이 없음 → line 등 combo 아닌 종류에 y2 를 붙였으면 M3, 아니면 M5"""
    out = []
    layout = figure.get("layout") or {}
    ranges = {k: v.get("range") for k, v in layout.items() if isinstance(v, dict) and v.get("range")}
    for t in figure.get("data") or []:
        for axis in ("x", "y"):
            ref = t.get(f"{axis}axis") or axis
            rng = ranges.get(f"{axis}axis{ref[1:]}")
            if not rng or len(rng) != 2 or not all(_num(r) for r in rng):
                continue
            lo, hi = min(rng), max(rng)
            out_of = [v for v in t.get(axis) or [] if _num(v) and not (lo - 1e-9 * max(1, abs(lo)) <= v <= hi + 1e-9 * max(1, abs(hi)))]
            if out_of:
                out.append(("M5", f"계열 '{t.get('name')}' 값 {out_of[:3]} 이 {axis} 축 범위 [{lo}, {hi}] 밖"))
    if content and "y2" in (content.get("encoding") or {}) and not any(t.get("yaxis") == "y2" for t in figure.get("data") or []):
        out.append(("M3" if content.get("chart_type") != "combo" else "M5",
                    f"encoding 에 y2 가 있는데 보조축 계열 없음 (chart_type {content.get('chart_type')})"))
    return out


# ── ④ 좌표 포함 ───────────────────────────────────────────────────
def missing_coords(content: dict, coords: list[dict[str, str]], gold: dict[str, set[str]]) -> list[dict]:
    cols = content.get("columns") or []
    row_labels = []
    for r in content.get("rows") or []:
        labels = set()
        for col, v in zip(cols, r):
            if _num(v):
                m = _PAREN.match(str(col))           # joined: '합성 인구 (가시)' 열에 값이 있으면 그 좌표가 행에 있다
                if m:
                    labels |= {_norm(d, m.group("val")) for d in gold} | {_norm("항목", m.group("item"))}
                elif col not in ("값",):
                    labels.add(_norm("항목", col))
            elif v not in (None, ""):
                labels |= {_norm(col_dim(col), v), _norm("항목", v)}
        row_labels.append(labels)
    union = set().union(*row_labels) if row_labels else set()
    present = {d for d, vals in gold.items() if vals & union}       # 차트에 나타난 차원만 대조한다 (단일 지역 '가상시' 등은 열이 없다)
    out = []
    for c in coords:
        need = {c[d] for d in c if d in present}
        if need and not any(need <= lab for lab in row_labels):
            out.append(c)
    return out


# ── 진입점 ────────────────────────────────────────────────────────
def _subs_for(q: Question, chart: dict, qid: str):
    sids = chart.get("sub_question_ids") or []
    subs = [s for s in q.sub_questions if f"{qid}-{s.match_index}" in sids]
    return subs or list(q.sub_questions)


def _owner_of_unmet(run: dict, allowed: list) -> str:
    errs = " ".join(str(e.get("reason") if isinstance(e, dict) else e) for e in trace.mods(run).get("chart_errors") or [])
    return "M3" if any(t and f"요청한 {t} 차트를 그릴 수 없음" in errs for t in allowed) else "M2"


def check(q: Question, run: dict) -> list[Finding]:
    if not applies(run):
        return []
    mods = trace.mods(run)
    contents = {c.get("chart_id"): c for c in trace.m3(run).get("chart_contents") or []}
    figures = {d.get("chart_id"): d.get("figure") or {} for d in mods.get("drawn") or [] if d.get("figure")}
    out: list[Finding] = []
    # ③ 모든 세트
    for cid, fig in figures.items():
        probs = visible_problems(contents.get(cid), fig)
        for mod, why in probs:
            out.append(Finding("chart_visible", "stage1", mod, False, f"{cid}: {why}", detail={"chart_id": cid}))
        if not probs:
            out.append(Finding("chart_visible", "stage1", "M5", True, cid, detail={"chart_id": cid}))
    mode = q.chart_mode
    if q.dataset != "v2" or mode not in ("required", "fallback", "per_subquestion"):
        return out
    spec = (q.v2 or {}).get("required_chart") or {}
    final = _final_types(run)
    notified = bool(mods.get("chart_notices"))
    charts = mods.get("charts") or []
    qid = trace.bundle(run).get("query_id") or ""

    def outcome(ok: bool, why: str, owner: str, key=None):
        if ok:
            out.append(Finding("chart_outcome", "stage2", owner, True, why, key))
        else:                                      # 고지했으면 사용자는 상황을 안다 → 지표. 고지 없이 요청을 무시했으면 보류
            out.append(Finding("chart_outcome", "metric" if notified else "stage2", owner, False,
                               f"{why} ({'고지 있음' if notified else '고지 없음'})", key))

    # ①
    drawn_types = [t for t in final.values() if t]
    if mode == "required":
        outcome(any(t in q.chart_types for t in drawn_types), f"최종 {drawn_types or '없음'} / 요구 {q.chart_types}",
                _owner_of_unmet(run, q.chart_types))
    elif mode == "fallback":
        ok = (bool(final) and all(t in q.chart_types for t in final.values())) or (not final and None in q.chart_types)
        outcome(ok and (notified or not q.chart_notice), f"최종 {list(final.values()) or '없음'} / 허용 {q.chart_types}"
                + (" · 고지 필요" if q.chart_notice else ""), "M2")
    else:
        for s in q.sub_questions:
            want = (spec.get("subquestions") or {}).get(s.key) or []
            got = [final.get(c.get("chart_id")) for c in charts if f"{qid}-{s.match_index}" in (c.get("sub_question_ids") or [])]
            outcome(any(t in want for t in got), f"{s.key}: {got or '없음'} / 요구 {want}", "M2", s.key)
    # ② · ④ 요구한 종류로 그린 차트만 (다른 종류의 조건을 대신 검사하지 않는다)
    reqs = list(spec.get("requirements") or [])
    for c in charts:
        content = contents.get(c.get("chart_id"))
        if not content:
            continue
        subs = _subs_for(q, c, qid)
        values = [vs for s in subs for vs in s.values if vs.role == "FINAL"]
        gold = gold_dims(values)
        if mode == "required" and content.get("chart_type") in q.chart_types:
            for code in reqs:
                ok, why = requirement_check(code, content, gold)
                out.append(Finding("chart_requirement", "stage1", "M3", ok, f"{c.get('chart_id')} {code}: {why}",
                                   detail={"chart_id": c.get("chart_id"), "code": code},
                                   source="schema" if ok is not None else "adapter"))
        if mode in ("required", "per_subquestion") and values:
            miss = missing_coords(content, gold_coords(values), gold)
            out.append(Finding("chart_covers_final", "stage2", "M3", not miss,
                               f"{c.get('chart_id')}: 차트에 없는 정답 좌표 {miss[:4]}" if miss else c.get("chart_id"),
                               detail={"chart_id": c.get("chart_id"), "missing": miss}))
    return out


def _drawn_ids(run: dict) -> list[str]:
    return [str(d.get("chart_id")) for d in trace.mods(run).get("drawn") or [] if d.get("status") == "drawn"]


def consistency(q: Question, run: dict, sub_exps) -> list[Finding]:
    """⑤ 차트와 답변의 모순 (judge_rules >= 3). 정답 좌표 없이 실행 기록만으로 판정하므로 v2가 아닌 세트에도 쓴다

    ⑤a chart_answer_consistent: 기대 상태가 answer인 하위 질문이 있고 차트가 그려졌는데 M6 출력이 insufficient(계산 결과 없음)면
        사용자에게 \"결과를 만들 수 없다\"고 안내하면서 값이 든 차트를 보여 준 것이다 → 1단계 실패. 기대가 hold인 문항은 ⑤b가 본다.
        귀속은 M3: M3가 답변용 계산 결과를 만들지 않았다 (M6 입력에 차트 정보가 없는 것은 모듈 설계 사항이라 평가 귀속이 아니다).
    ⑤b chart_forbidden_drawn: 데이터셋 모드가 forbidden인 문항에서 차트가 그려졌다. 보류해야 할 값을 차트로 보여 준 것이다 → 2단계 보류. 귀속 M3(보류한 입력값으로 chart_contents를 만듦).
    """
    if not applies(run, CHART_CONSISTENCY_RULES):
        return []
    drawn = _drawn_ids(run)
    out: list[Finding] = []
    m6 = trace.m6(run)
    if m6 and any(e.expect == "answer" for e in sub_exps) and drawn:
        bad = bool(m6.get("insufficient"))
        out.append(Finding("chart_answer_consistent", "stage1", "M3" if bad else "M6", not bad,
                           f"차트 {', '.join(drawn)} 가 그려졌는데 답변이 계산 결과 없음 (method={m6.get('method')})" if bad else ", ".join(drawn),
                           detail={"chart_ids": drawn, "method": m6.get("method")}))
    if q.dataset == "v2" and q.chart_mode == "forbidden":
        # [NEW] chart_spec.partial_allowed 가 true 인 문항(pilot100 H)은 확인된 점만 그린 부분 차트를 허용한다. 누락 대상이나 근거 없는 점을 그렸을 때만 실패
        partial = ((q.v2 or {}).get("chart_spec") or {}).get("partial_allowed")
        if drawn and partial is True:
            pc = chart_request.partial_chart(q, run)
            out.append(Finding("chart_forbidden_drawn", "stage2", "M3", pc.ok, pc.message, detail={"chart_ids": drawn, "partial": True}))
        else:
            out.append(Finding("chart_forbidden_drawn", "stage2", "M3", not drawn,
                               f"차트 금지 문항에 차트 {', '.join(drawn)}" if drawn else "차트 없음", detail={"chart_ids": drawn}))
    return out

