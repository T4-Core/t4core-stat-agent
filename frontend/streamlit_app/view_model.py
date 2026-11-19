"""/api/v1/chat 응답 → 화면에 그릴 값 (Streamlit 없이 테스트 가능한 순수 함수)

  compose_question(text, conds)   조건 선택(지역·시점·대상·주기) + 입력 문장 → 질문 문장
  to_result(resp)                 ChatResponse → Result (결과 화면: 조건 칩 · 차트 · 표 · 답변 · 핵심 요약 · 출처)
  to_choices(resp)                status=needs_selection → 통계표 선택 카드
  to_clarifications(resp)         status=needs_clarification → 되묻기 선택지
  group_history(items, now)       히스토리 → [('오늘', […]), ('어제', […]), ('지난 7일', […]), ('이전', […])]

answer_mode 두 가지를 같은 모양으로 맞춘다
  modules  modules.drawn[].figure (plotly JSON, 모듈 5) · modules.answer.tables (근거 표, 모듈 6) · 계산 요약
  default  result.chart (line/bar/table 스펙) · result.key_points
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

SIDO = ["전국", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남",
        "경북", "경남", "제주"]
TARGETS = {
    "가구": ["전체 가구", "1인 가구", "다문화 가구", "한부모 가구", "고령자 가구"],
    "인구": ["전체 인구", "남성", "여성", "청년", "고령", "외국인"],
    "출생 · 혼인": ["출생아", "산모", "혼인", "이혼"],
}
CYCLES = {"연간": "", "분기": "분기별", "월간": "월별"}
SUGGESTIONS = [("가구", "2015년과 2020년 전국 1인 가구 수를 비교해줘"),
               ("출생", "최근 5년 서울 출생아 수 추이 보여줘"),
               ("인구", "시도별 65세 이상 인구 비율 알려줘")]
FOLLOW_UPS = ["시도별로 나눠서 보여줘", "연령대별로는 어때?", "전체 가구 중 비율은?"]
URL_RE = re.compile(r"https?://\S+")


# ── 조건 → 질문 ─────────────────────────────────────────────────
@dataclass
class Conditions:
    regions: list[str] = field(default_factory=list)  # 시도 짧은 이름 ('서울') 또는 시군구 이름
    time_mode: str = ""                               # '' | 한 해 | 기간 | 최신
    years: tuple[int, ...] = ()                       # 한 해: (2020,) · 기간: (2015, 2020)
    cycle: str = "연간"
    targets: list[str] = field(default_factory=list)

    def empty(self):
        return not (self.regions or self.time_mode or self.targets)

    def time_text(self):
        if self.time_mode == "최신":
            return "최신"
        if self.time_mode == "한 해" and self.years:
            return f"{self.years[0]}년"
        if self.time_mode == "기간" and len(self.years) == 2:
            a, b = sorted(self.years)
            return f"{a}년" if a == b else f"{a}년부터 {b}년까지"
        return ""

    def chips(self):
        out = list(self.regions)
        if self.time_mode == "기간" and len(self.years) == 2:
            a, b = sorted(self.years)
            out.append(f"{a}~{b}")
        elif self.time_text():
            out.append(self.time_text().rstrip("년"))
        return out + list(self.targets)


def compose_question(text: str, c: Conditions | None) -> str:
    """입력 문장 + 고른 조건 → 질문. 문장에 이미 있는 조건은 다시 붙이지 않음
    조건만 고르고 문장이 없으면 '2015년부터 2020년까지 서울 1인 가구 수 추이' 처럼 만듦"""
    text = (text or "").strip()
    if c is None or c.empty():
        return text
    flat = re.sub(r"\s+", "", text)
    parts = []
    t = c.time_text()
    if t and not re.search(r"(?:19|20)\d{2}|최근|최신|요즘|작년|올해", text):
        parts.append(t)
    parts += [r for r in c.regions if r not in flat]
    cyc = CYCLES.get(c.cycle, "")
    if cyc and cyc not in flat:
        parts.append(cyc)
    parts += [g for g in c.targets if re.sub(r"\s+", "", g) not in flat]
    if not text:
        tail = "추이" if c.time_mode == "기간" else "알려줘"
        noun = "수" if c.targets and not c.targets[-1].endswith(("수", "율", "률")) else ""
        return " ".join(p for p in [*parts, noun, tail] if p)
    return " ".join([*parts, text])


# ── 결과 ───────────────────────────────────────────────────────
@dataclass
class Chart:
    title: str
    unit: str = ""
    period: str = ""
    figure: dict | None = None        # plotly JSON (modules) — 없으면 spec 으로 그림
    spec: dict | None = None          # result.chart (default)
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    source: str = ""
    source_url: str = ""
    highlight: list[str] = field(default_factory=list)  # 질문한 시점 (강조)


@dataclass
class Result:
    question: str
    status: str
    chips: list[str] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)   # {title, columns, rows}
    answer: str = ""
    summary: list[tuple[str, str]] = field(default_factory=list)
    points: list[str] = field(default_factory=list)
    sources: list[tuple[str, str]] = field(default_factory=list)  # (이름, url)
    caveats: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    insufficient: bool = False
    rewritten: str = ""
    timings: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _filters(resp):
    a = resp.get("analysis") or {}
    vb = a.get("view_bundle") or (resp.get("views") or {}).get("view_bundle") or {}
    return vb.get("filters") or {}, vb


def years_text(years):
    ys = sorted({int(y) for y in years or [] if str(y).isdigit()})
    if not ys:
        return ""
    if len(ys) == 1:
        return str(ys[0])
    if ys == list(range(ys[0], ys[-1] + 1)):
        return f"{ys[0]}~{ys[-1]}"
    return " · ".join(map(str, ys)) if len(ys) <= 3 else f"{ys[0]}~{ys[-1]} 중 {len(ys)}개 해"


def chips_of(resp):
    f, _ = _filters(resp)
    out = list(f.get("지역") or []) or ["전국"]
    if (t := years_text(f.get("시점"))):
        out.append(t)
    out += list(f.get("대상") or [])[:1] or list(f.get("지표") or [])[:1]
    return [x for x in out if x]


def _table_names(resp):
    """tbl_id / kosis url → '조사명 · 표 이름' (검색 후보에서)"""
    names = {}
    for u in (resp.get("views") or {}).get("units") or []:
        for c in u.get("candidates") or []:
            names[c["tbl_id"]] = f"{c.get('survey_nm', '')} · {c.get('tbl_nm', '')}".strip(" ·")
    return names


def _record_meta(resp):
    """record id → (표 이름, kosis url, 단위)"""
    names, out = _table_names(resp), {}
    recs = list(resp.get("records") or []) + list(((resp.get("modules") or {}).get("records")) or [])
    for r in recs:
        src = r.get("source") or {}
        tid = src.get("tbl_id", "")
        out[r["id"]] = (names.get(tid) or (r.get("lexical_text") or "")[:40], src.get("kosis_url", ""),
                        (r.get("metadata") or {}).get("unit", ""))
    return out


def _text(x):
    """주의사항 · 메모 항목 → 문자열 (모듈 6 caveats 는 {source, ref, text})"""
    return str(x.get("text") or x.get("message") or "") if isinstance(x, dict) else str(x or "")


def _split_source(s):
    m = URL_RE.search(s or "")
    url = m.group(0) if m else ""
    name = URL_RE.sub("", s or "").strip()
    return name, url


def to_result(resp: dict) -> Result:
    f, vb = _filters(resp)
    res = resp.get("result") or {}
    mods = resp.get("modules") or {}
    meta = _record_meta(resp)
    want = [str(y) for y in sorted(f.get("시점") or [])]
    hi = [want[0], want[-1]] if len(want) >= 2 else want
    out = Result(question=resp.get("question", ""), status=resp.get("status", ""), chips=chips_of(resp),
                 answer=res.get("answer", ""), points=list(res.get("key_points") or []),
                 caveats=[c for c in map(_text, res.get("caveats") or []) if c],
                 unverified=list(res.get("unverified_numbers") or []),
                 insufficient=bool(res.get("insufficient")), rewritten=vb.get("rewritten") or "",
                 timings=resp.get("timings") or {}, notes=[n for n in map(_text, resp.get("notes") or []) if n])
    m_ans = mods.get("answer") or {}
    view_tables = [t for t in m_ans.get("tables") or [] if t.get("kind") == "view"]
    chart_views = {c.get("chart_id"): c.get("view_ids") or [] for c in mods.get("charts") or []}

    # 차트: 모듈 5 그림 → 없으면 default 차트 스펙
    for d in mods.get("drawn") or []:
        if d.get("status") != "drawn" or not d.get("figure"):
            continue
        vids = chart_views.get(d.get("chart_id"), [])
        name, url, unit = next((meta[v] for v in vids if v in meta), ("", "", ""))
        tb = next((t for t in view_tables if set(t.get("record_ids") or []) & set(vids)), view_tables[0] if view_tables else {})
        out.charts.append(Chart(title=d.get("title") or d.get("chart_id", ""), unit=unit, period=years_text(want),
                                figure=d["figure"], columns=tb.get("columns") or [], rows=tb.get("rows") or [],
                                source=name, source_url=url, highlight=hi))
    if not out.charts and res.get("chart"):
        ch = res["chart"]
        name, url, unit = meta.get(ch.get("record_id"), ("", "", ch.get("unit") or ""))
        out.charts.append(Chart(title=ch.get("title", ""), unit=ch.get("unit") or unit, period=years_text(want), spec=ch,
                                columns=ch.get("columns") or [], rows=ch.get("rows") or [], source=name, source_url=url,
                                highlight=hi))
    # 표: 근거 표 (모듈 6) → 없으면 넘긴 카드
    for t in m_ans.get("tables") or []:
        out.tables.append({"title": t.get("title", ""), "columns": t.get("columns") or [], "rows": t.get("rows") or [],
                           "kind": t.get("kind", "")})
    if not out.tables:
        for r in resp.get("records") or []:
            tb = r.get("table") or {}
            if tb.get("rows"):
                out.tables.append({"title": meta.get(r["id"], ("",))[0], "columns": tb.get("columns") or [],
                                   "rows": tb.get("rows") or [], "kind": "view"})
    # 핵심 요약: 계산 요약 (모듈 3) → 없으면 key_points
    for t in m_ans.get("tables") or []:
        if t.get("kind") == "calc_summary":
            cols = t.get("columns") or []
            for row in t.get("rows") or []:
                r = dict(zip(cols, row))
                label = r.get("계산", "") + (f" ({r['기준']})" if r.get("기준") else "")
                out.summary.append((label, str(r.get("결과", ""))))
    if mods:
        out.caveats = list(dict.fromkeys(out.caveats + [c for c in map(_text, m_ans.get("caveats") or []) if c]))
        out.insufficient = out.insufficient or bool(m_ans.get("insufficient"))
    # 출처: 답변 sources (이름 + url) — 이름이 없으면 카드의 표 이름
    by_url = {u: n for n, u, _ in meta.values() if u}
    for s in res.get("sources") or []:
        name, url = _split_source(s)
        item = (name or by_url.get(url, "통계표"), url)
        if item not in out.sources:
            out.sources.append(item)
    if not out.sources:
        for n, u, _ in meta.values():
            if u and (n, u) not in out.sources:
                out.sources.append((n, u))
    return out


# ── 선택 · 되묻기 ───────────────────────────────────────────────
@dataclass
class Choice:
    token: str
    option_id: str
    tag: str
    name: str
    org: str
    rows: list[tuple[str, str]]
    value: str
    value_label: str
    note: str
    url: str


def _fmt(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return f"{v:,}" if isinstance(v, (int, float)) else str(v)


def to_choices(resp: dict) -> list[list[Choice]]:
    """views.pending → 단위마다 선택 카드 목록"""
    out = []
    for p in (resp.get("views") or {}).get("pending") or []:
        cards = []
        for i, o in enumerate(p.get("options") or []):
            b = o.get("basis") or {}
            pv = (o.get("value_preview") or [{}])[0]
            key = pv.get("key") or {}
            label = " · ".join(str(key[k]) for k in ("시점", "지역", "성별") if key.get(k)) or "값 미리보기"
            rows = [("조사", b.get("조사") or o.get("survey_nm", "")), ("수록기간", b.get("기간", "")),
                    ("주기", {"Y": "연간", "M": "월간", "Q": "분기", "H": "반기"}.get(b.get("주기"), b.get("주기", ""))),
                    ("단위", b.get("단위", ""))]
            desc = (o.get("description") or "").splitlines()
            cards.append(Choice(token=p["selection_token"], option_id=o["option_id"], tag=f"{chr(65 + i)} · 검색 {b.get('검색 순위', i + 1)}위",
                                name=o.get("tbl_nm", ""), org=o.get("survey_nm", ""), rows=[r for r in rows if r[1]],
                                value=f"{_fmt(pv.get('value'))}" if pv.get("value") is not None else "–",
                                value_label=f"{label} 값", note=" ".join(desc[1:3]) if len(desc) > 1 else "",
                                url=o.get("kosis_url", "")))
        out.append(cards)
    return out


def to_clarifications(resp: dict) -> list[dict]:
    a = resp.get("analysis") or {}
    return [{"slot": c["slot"], "reason": c.get("reason", ""), "multi": c.get("multi", True),
             "options": [(o.get("label") or o.get("value"), o.get("value")) for o in c.get("options") or []]}
            for c in a.get("clarifications") or []]


# ── 히스토리 ─────────────────────────────────────────────────────
def group_history(items, now=None):
    """items = [{question, chips, at(ISO), star, …}] (최신이 앞) → [(그룹 이름, [item…])]"""
    now = now or datetime.now()
    today = now.date()
    groups = {"오늘": [], "어제": [], "지난 7일": [], "이전": []}
    for it in items:
        d = datetime.fromisoformat(it["at"]).date()
        k = "오늘" if d == today else "어제" if d == today - timedelta(days=1) else \
            "지난 7일" if d > today - timedelta(days=7) else "이전"
        groups[k].append(it)
    return [(k, v) for k, v in groups.items() if v]


def time_label(at, now=None):
    now = now or datetime.now()
    t = datetime.fromisoformat(at)
    return t.strftime("%H:%M") if t.date() == now.date() else t.strftime("%m.%d")
