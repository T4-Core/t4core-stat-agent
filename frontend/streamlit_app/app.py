"""KOSIS 통계 에이전트 — Streamlit 확인용 화면 (시안 screens.html 기준)

  실행   cd frontend/streamlit_app && streamlit run app.py      (백엔드: uvicorn backend.main:app --port 8000)
  주소   환경변수 STAT_AGENT_API (기본 http://localhost:8000) · 화면 오른쪽 위 ⚙ 에서도 바꿈

화면 (시안 번호)
  Agent    01 메인 · 02~04 조건 고르기(지역·시점·대상) · 05 조건으로 볼 수 있는 통계 · 06 진행 단계
           07 통계표 선택(needs_selection) · 되묻기(needs_clarification) · 08 결과(차트·표 | 답변)
           09 크게 보기 · 12~16 차트 2개 이상(한 개씩 · 한번에 · 넓게 · 크게 보기 나란히/한 개씩)
  History  10 목록 + 미리보기 · 11 빈 화면
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import api
import charts
import ui
import view_model as vm

HERE = Path(__file__).resolve().parent
CHARACTER = HERE / "assets" / "sloth.png"          # 있으면 시안의 '캐릭터 영역'에 그림
HISTORY_PATH = Path(os.getenv("UI_HISTORY_PATH", HERE / ".history.json"))
HISTORY_MAX = 50

st.set_page_config(page_title="KOSIS 통계 에이전트", page_icon="🌿", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)


# ── 상태 ───────────────────────────────────────────────────────
def _load_history():
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_history():
    try:
        HISTORY_PATH.write_text(json.dumps(S.history[:HISTORY_MAX], ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


S = st.session_state
for k, v in {"page": "Agent", "screen": "home", "cond": vm.Conditions(), "resp": None, "pending_q": None,
             "pending_call": None, "error": "", "draft": "", "viz_mode": "한 개씩", "wide": False,
             "hist_sel": None, "api": api.BASE, "answer_mode": "modules", "auto_select": False, "today": None}.items():
    S.setdefault(k, v)
if "history" not in S:
    S.history = _load_history()


def go(screen):
    S.screen = screen
    st.rerun()


def add_history(resp):
    r = vm.to_result(resp)
    item = {"id": uuid.uuid4().hex[:8], "question": r.question, "chips": r.chips, "at": datetime.now().isoformat(timespec="seconds"),
            "star": False, "resp": resp}
    S.history = [item] + [h for h in S.history if h["question"] != r.question][:HISTORY_MAX - 1]
    S.hist_sel = item["id"]
    _save_history()


def ask(question, **kw):
    """질문 → 다음 실행에서 진행 화면(06)을 보이고 /chat 호출"""
    if question.strip():
        S.pending_q, S.pending_call, S.error = question.strip(), kw, ""
        S.page = "Agent"
        st.rerun()


# ── 머리 ───────────────────────────────────────────────────────
def header():
    a, b, c = st.columns([3, 2, 3], vertical_alignment="center")
    a.markdown('<div class="nx-logo"><i>🌿</i>Nexai</div>', unsafe_allow_html=True)
    with b:
        if S.get("nav") != S.page:  # 코드가 화면을 바꿨으면 (결과 다시 열기 등) 위젯 값도 맞춤 — 위젯을 만들기 전에만 가능
            S["nav"] = S.page
        st.segmented_control("화면", ["Agent", "History"], key="nav", label_visibility="collapsed",
                             on_change=lambda: S.update(page=S.get("nav") or S.page))
    with c:
        _, x, y = st.columns([4, 1, 1])
        if x.button("✏️", help="새 질문", width="stretch"):
            S.screen, S.resp, S.draft, S.cond = "home", None, "", vm.Conditions()
            S.page = "Agent"
            st.rerun()
        with y.popover("⚙️", width="stretch"):
            st.markdown("**설정**")
            S.api = st.text_input("백엔드 주소", S.api)
            h = api.health(S.api)
            st.caption(("🟢 연결됨 · " + ", ".join(f"{k}={'✓' if v else '✗'}" for k, v in h.items() if k != "status"))
                       if h else "🔴 연결 안 됨 — `uvicorn backend.main:app --port 8000`")
            S.answer_mode = st.radio("답변 방식", ["modules", "default"], index=0 if S.answer_mode == "modules" else 1,
                                     format_func=lambda m: {"modules": "모듈 2→3→5→6 (차트 계획·계산·그림)",
                                                            "default": "답변 HCX 1회 (차트 스펙)"}[m])
            S.auto_select = st.toggle("표마다 값이 다르면 1순위로 바로 진행", S.auto_select,
                                      help="끄면 비슷한 통계표가 여럿일 때 고르는 화면(07)이 나옴")
            use_today = st.toggle("기준일 지정 ('작년'·'최근 N년' 기준)", S.today is not None)
            S.today = st.date_input("기준일", S.today or date.today()) if use_today else None


# ── 01~05 메인 ──────────────────────────────────────────────────
def _label(icon, name, vals):
    return f"{icon} {', '.join(vals)}" if vals else f"{icon} {name} 선택"


def _split(text):
    return [x.strip() for x in str(text or "").split(",") if x.strip()]


def picker_region(c):
    # 버튼 이름은 팝오버 안의 위젯보다 먼저 그려지므로, 이번 실행에서 바뀐 위젯 값(세션 상태)으로 미리 계산
    now = list(dict.fromkeys(list(S.get("pk_sido", [r for r in c.regions if r in vm.SIDO]) or [])
                             + _split(S.get("pk_sgg", ", ".join(r for r in c.regions if r not in vm.SIDO)))))
    with st.popover(_label("📍", "지역", now), width="stretch"):
        st.markdown("**지역 선택** <span class='nx-meta'>여러 곳을 고르면 비교해 드려요</span>", unsafe_allow_html=True)
        sido = st.pills("시도", vm.SIDO, selection_mode="multi", default=[r for r in c.regions if r in vm.SIDO],
                        key="pk_sido", label_visibility="collapsed")
        sgg = st.text_input("시군구 (선택)", ", ".join(r for r in c.regions if r not in vm.SIDO),
                            placeholder="예) 종로구, 수원시 권선구", key="pk_sgg")
        c.regions = list(dict.fromkeys(list(sido or []) + [x.strip() for x in sgg.split(",") if x.strip()]))


def picker_time(c):
    mode0, y1, y2 = S.get("pk_tmode", c.time_mode or None), S.get("pk_y1"), S.get("pk_y2")
    last = (S.today or date.today()).year - 1
    years = ((y1 or last,) if mode0 == "한 해" else tuple(y2) if mode0 == "기간" and y2
             else c.years if len(c.years) == 2 else (last - 5, last) if mode0 == "기간" else c.years)
    t = vm.Conditions(time_mode=mode0 or "", years=years).chips()
    with st.popover(_label("📅", "시점", t[:1]), width="stretch"):
        mode = st.segmented_control("시점", ["한 해", "기간", "최신"], default=c.time_mode or None, key="pk_tmode")
        last = (S.today or date.today()).year - 1
        if mode == "한 해":
            y = st.select_slider("연도", list(range(1980, last + 1)), value=c.years[0] if c.years else last, key="pk_y1")
            c.time_mode, c.years = mode, (y,)
        elif mode == "기간":
            a, b = c.years if len(c.years) == 2 else (last - 5, last)
            r = st.select_slider("기간", list(range(1980, last + 1)), value=(a, b), key="pk_y2")
            c.time_mode, c.years = mode, tuple(r)
        elif mode == "최신":
            c.time_mode, c.years = mode, ()
        else:
            c.time_mode, c.years = "", ()
        st.markdown('<div class="nx-lbl">주기</div>', unsafe_allow_html=True)
        c.cycle = st.pills("주기", list(vm.CYCLES), default=c.cycle, key="pk_cyc", label_visibility="collapsed") or "연간"


def picker_target(c):
    now = []
    for g, opts in vm.TARGETS.items():
        now += (S[f"pk_t_{g}"] if f"pk_t_{g}" in S else [x for x in c.targets if x in opts]) or []
    now += _split(S.get("pk_free", ", ".join(t for t in c.targets if not any(t in v for v in vm.TARGETS.values()))))
    with st.popover(_label("👤", "대상", list(dict.fromkeys(now))), width="stretch"):
        st.markdown("**대상 선택** <span class='nx-meta'>누구(무엇)에 대한 통계인가요?</span>", unsafe_allow_html=True)
        free = st.text_input("대상 검색", ", ".join(t for t in c.targets if not any(t in v for v in vm.TARGETS.values())),
                             placeholder="예) 청년, 다문화", key="pk_free")
        picked = []
        for g, opts in vm.TARGETS.items():
            st.markdown(f'<div class="nx-lbl">{g}</div>', unsafe_allow_html=True)
            picked += st.pills(g, opts, selection_mode="multi", default=[t for t in c.targets if t in opts],
                               key=f"pk_t_{g}", label_visibility="collapsed") or []
        c.targets = list(dict.fromkeys(picked + [x.strip() for x in free.split(",") if x.strip()]))


@st.cache_data(ttl=300, show_spinner=False)
def _search(q, base):
    return api.search(q, 3, base)


def home():
    if CHARACTER.exists():
        st.image(str(CHARACTER), width=132)
    st.markdown('<div class="nx-h1">어떤 통계가 궁금하세요?</div>'
                '<div class="nx-sub">질문을 직접 적거나, 아래에서 지역·시점·대상을 골라 찾아보세요.</div>', unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 4, 1])
    c = S.cond
    with mid:
        with st.container(key="comp"):
            with st.form("ask", border=False, clear_on_submit=False):
                t, s = st.columns([12, 1], vertical_alignment="bottom")
                text = t.text_input("질문", S.draft, label_visibility="collapsed",
                                    placeholder="무엇이든 물어보세요  예) 2020년 서울 1인 가구는 몇 가구야?")
                sent = s.form_submit_button("➤", width="stretch")
            l0, r1, r2, r3, rz = st.columns([2, 3, 3, 3, 1.4], vertical_alignment="center")
            l0.markdown('<div class="nx-lbl">조건으로 찾기</div>', unsafe_allow_html=True)
            with r1:
                picker_region(c)
            with r2:
                picker_time(c)
            with r3:
                picker_target(c)
            if not c.empty() and rz.button("초기화", type="tertiary"):
                S.cond = vm.Conditions()
                for k in [k for k in S if str(k).startswith("pk_")]:
                    del S[k]
                st.rerun()
        if sent:
            S.draft = text
            q = vm.compose_question(text, c)
            if q:
                ask(q)
            st.warning("질문을 적거나 조건을 골라 주세요.")
        if S.error:
            st.error(S.error)

        if not c.empty():  # 05 조건으로 볼 수 있는 통계
            q = vm.compose_question(text, c)
            try:
                cands = _search(q, S.api)
            except api.ApiError as e:
                cands = []
                st.caption(f"통계표 후보를 불러오지 못함: {e}")
            st.markdown(f'<div class="nx-lbl" style="display:flex;justify-content:space-between"><span>이 조건으로 볼 수 있는 '
                        f'통계 {len(cands)}개</span><span>하나를 고르거나, 위에 질문을 더 적어도 돼요</span></div>',
                        unsafe_allow_html=True)
            st.caption(ui.md(f"질문으로 보낼 문장: {q}"))
            for i, cd in enumerate(cands):
                with st.container(key=f"card{'-sel' if i == 0 else ''}-cand{i}"):
                    a, b = st.columns([5, 2], vertical_alignment="center")
                    a.markdown(f'<div class="nx-title">📊 {ui.escape(cd["tbl_nm"])}</div><div class="nx-meta">'
                               f'{ui.escape(cd["survey_nm"])}</div>' + "".join(ui.chip(x, True) for x in c.chips()),
                               unsafe_allow_html=True)
                    if b.button("이 통계로 보기 ›", key=f"cand{i}", width="stretch"):
                        ask(f"{q} ({cd['tbl_nm']})")
            if st.button("조건으로 바로 물어보기", type="primary"):
                ask(q)
        else:
            st.markdown('<div class="nx-lbl">이런 질문은 어때요?</div>', unsafe_allow_html=True)
            cols = st.columns(len(vm.SUGGESTIONS))
            for col, (tag, q) in zip(cols, vm.SUGGESTIONS):
                with col.container(key=f"card-sug-{tag}"):
                    st.markdown(f'<div class="nx-meta" style="color:#5F8B85;font-weight:700">{tag}</div>', unsafe_allow_html=True)
                    if st.button(ui.md(q), key=f"sug-{tag}", type="tertiary"):
                        ask(q)
            if S.history:
                h1, h2 = st.columns([4, 1])
                h1.markdown('<div class="nx-lbl">최근에 물어본 질문</div>', unsafe_allow_html=True)
                if h2.button("히스토리 전체 보기 ›", type="tertiary"):
                    S.page = "History"
                    st.rerun()
                for h in S.history[:3]:
                    if st.button(ui.md(f"🕘  {h['question']}"), key=f"recent-{h['id']}", type="tertiary"):
                        S.resp = h["resp"]
                        go("result")


# ── 06 진행 ─────────────────────────────────────────────────────
STEPS = [("질문 이해하기", "analyze"), ("알맞은 통계표 찾기 · 데이터 불러오기", "views"), ("차트와 답변 만들기", "answer")]


def run_pending():
    q, kw = S.pending_q, S.pending_call or {}
    S.pending_q, S.pending_call = None, None
    st.markdown(ui.question_bubble(q), unsafe_allow_html=True)
    if CHARACTER.exists():
        st.image(str(CHARACTER), width=200)
    st.markdown('<div class="nx-h1" style="font-size:22px">통계표에서 숫자를 찾고 있어요…</div>', unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 2, 1])
    with mid, st.container(key="card-steps"):
        box = st.empty()
        box.markdown(ui.steps([(n, False, "") for n, _ in STEPS]), unsafe_allow_html=True)
        with st.spinner("처리 중… (HCX 호출이 있어 수십 초 걸릴 수 있어요)"):
            try:
                resp = api.chat(q, today=S.today.isoformat() if S.today else None, answer_mode=S.answer_mode,
                                auto_select=S.auto_select, base=S.api, **kw)
            except api.ApiError as e:
                S.error = str(e)
                go("home")
        t = resp.get("timings") or {}
        ans_t = t.get("answer", t.get("modules"))
        box.markdown(ui.steps([(n, True, f"{t[k]:.1f}초" if isinstance(t.get(k), (int, float)) else "")
                               for n, k in STEPS[:2]] + [(STEPS[2][0], True, f"{ans_t:.1f}초" if ans_t is not None else "")]),
                     unsafe_allow_html=True)
    S.resp = resp
    status = resp.get("status")
    if status in ("ok", "out_of_scope"):
        add_history(resp)
        S["pager"] = 0
        go("result")
    go({"needs_selection": "choose", "needs_clarification": "clarify"}.get(status, "result"))


# ── 07 통계표 선택 · 되묻기 ──────────────────────────────────────
def choose():
    resp = S.resp
    st.markdown(ui.question_bubble(resp["question"]), unsafe_allow_html=True)
    units = vm.to_choices(resp)
    n = sum(len(u) for u in units)
    st.markdown(f'<div class="nx-h1" style="font-size:23px">비슷한 통계표가 {n}개 있어요. 어떤 걸로 볼까요?</div>'
                '<div class="nx-sub" style="font-size:14px">같은 질문이라도 조사 방식·기준이 달라 숫자가 조금 달라요.</div>',
                unsafe_allow_html=True)
    picks = S.setdefault("picks", {})
    for ui_i, cards in enumerate(units):
        if len(units) > 1:
            st.markdown(f'<div class="nx-lbl">검색 단위 {ui_i + 1}</div>', unsafe_allow_html=True)
        cols = st.columns(len(cards))
        for col, ch in zip(cols, cards):
            sel = picks.get(ch.token, cards[0].option_id) == ch.option_id
            with col.container(key=f"card{'-sel' if sel else ''}-opt-{ui_i}-{ch.option_id}"):
                st.markdown(ui.chip(ch.tag) + f'<div style="font-size:19px;font-weight:700;margin-top:8px">{ui.escape(ch.name)}</div>'
                            f'<div class="nx-meta" style="margin-bottom:6px">{ui.escape(ch.org)}</div>'
                            + ui.kv("통계표 정보", ch.rows, "🗂️")
                            + f'<div class="nx-lbl">{ui.escape(ch.value_label)}</div><div class="nx-big">{ch.value}</div>'
                            + (f'<p class="nx-note">{ui.escape(ch.note)}</p>' if ch.note else "")
                            + (f'<a class="nx-link" href="{ui.escape(ch.url)}" target="_blank">KOSIS 원본 보기 ›</a>' if ch.url else ""),
                            unsafe_allow_html=True)
                if st.button("이 통계표로 보기", key=f"pick-{ui_i}-{ch.option_id}", type="primary" if sel else "secondary",
                             width="stretch"):
                    picks[ch.token] = ch.option_id
                    if len(units) == 1:
                        submit_picks(units)
                    st.rerun()
    st.write("")
    a, b, c = st.columns([2, 1, 1])
    if len(units) > 1 and a.button("고른 통계표로 보기", type="primary"):
        submit_picks(units)
    if b.button("검색 1위로 바로 보기"):
        S.picks = {}
        submit_picks(units)
    if c.button("질문 다시 쓰기"):
        S.draft = resp["question"]
        go("home")


def submit_picks(units):
    sel = [{"selection_token": cards[0].token, "option_id": S.get("picks", {}).get(cards[0].token, cards[0].option_id)}
           for cards in units if cards]
    prev, S.picks = S.resp, {}
    ask(prev["question"], previous=prev, view_selections=sel)


def clarify():
    resp = S.resp
    st.markdown(ui.question_bubble(resp["question"]), unsafe_allow_html=True)
    st.markdown('<div class="nx-h1" style="font-size:23px">조금만 더 알려 주세요</div>', unsafe_allow_html=True)
    picked = {}
    _, mid, _ = st.columns([1, 3, 1])
    with mid:
        for c in vm.to_clarifications(resp):
            with st.container(key=f"card-clar-{c['slot']}"):
                st.markdown(f"**{c['slot']}** <span class='nx-meta'>{ui.escape(c['reason'])}</span>", unsafe_allow_html=True)
                labels = {lab: val for lab, val in c["options"]}
                got = st.pills(c["slot"], list(labels), selection_mode="multi" if c["multi"] else "single",
                               key=f"clar-{c['slot']}", label_visibility="collapsed", format_func=ui.md)
                got = got if isinstance(got, list) else [got] if got else []
                if got:
                    picked[c["slot"]] = [labels[g] for g in got]
        if st.button("이 조건으로 보기", type="primary", disabled=not picked):
            ask(resp["question"], previous=resp, selections=picked)


# ── 08 결과 ─────────────────────────────────────────────────────
def _df(columns, rows):
    try:
        return pd.DataFrame(rows, columns=columns)
    except ValueError:
        return pd.DataFrame(rows)


def draw_chart(ch, height=330, legend=True, key=""):
    fig = charts.figure_of(ch, height)
    st.markdown(f'<div class="nx-title">{ui.escape(ch.title)}</div><div class="nx-meta">'
                f'{ui.escape(" · ".join(x for x in [f"단위: {ch.unit}" if ch.unit else "", ch.period] if x))}</div>', unsafe_allow_html=True)
    if fig is None:
        st.dataframe(_df(ch.columns, ch.rows), hide_index=True, width="stretch")
        return
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key=f"fig-{key}")
    if legend and ch.highlight and len(ch.highlight) == 2 and any(t.type == "bar" for t in fig.data):
        st.markdown(ui.legend(), unsafe_allow_html=True)


@st.dialog("크게 보기", width="large")
def big_view(r: vm.Result):
    mode = "나란히"
    if len(r.charts) > 1:
        mode = st.segmented_control("보기", ["나란히", "한 개씩"], default="나란히", key="big_mode")
    if len(r.charts) > 1 and mode == "나란히":
        cols = st.columns(len(r.charts))
        for i, (col, ch) in enumerate(zip(cols, r.charts)):
            with col:
                draw_chart(ch, 380, key=f"big{i}")
    elif r.charts:
        i = 0
        if len(r.charts) > 1:
            i = st.radio("차트", range(len(r.charts)), format_func=lambda k: ui.md(f"{k + 1}. {r.charts[k].title}"), horizontal=True)
        draw_chart(r.charts[i], 460, key="big1")
    else:
        st.info("차트로 그릴 값이 없어 표만 보여 드려요.")
    for i, t in enumerate(r.tables):
        st.markdown(f'<div class="nx-lbl">{ui.escape(t["title"] or "표")}</div>', unsafe_allow_html=True)
        df = _df(t["columns"], t["rows"])
        st.dataframe(df, hide_index=True, width="stretch")
        st.download_button("CSV 받기", df.to_csv(index=False).encode("utf-8-sig"), f"{t['title'] or 'table'}.csv",
                           "text/csv", key=f"csv{i}")
    for name, url in r.sources:
        if url:
            st.link_button(ui.md(f"KOSIS 원본 통계표 열기 · {name}"), url)


def viz_card(r: vm.Result):
    with st.container(key="card-viz"):
        n = len(r.charts)
        h1, h2, h3 = st.columns([3, 3, 1], vertical_alignment="center")
        h1.markdown(ui.card_head("📊", "시각화", f'<span class="nx-chip" style="margin-left:6px">{n}개</span>' if n > 1 else ""),
                    unsafe_allow_html=True)
        opts = ["한 개씩", "한번에", "표"] if n > 1 else ["차트", "표"]
        S.viz_mode = h2.segmented_control("차트 보기", opts, default=S.viz_mode if S.viz_mode in opts else opts[0],
                                          key=f"vizm{n > 1}", label_visibility="collapsed") or opts[0]
        if h3.button("⛶", help="크게 보기", key="expand"):
            big_view(r)
        if n > 1:
            S.wide = st.toggle("넓게 펼쳐 나란히 보기", S.wide, key="wide_t")
        if not r.charts:
            st.info("차트로 그릴 값이 없어요. 아래 표로 확인해 주세요.")
        if S.viz_mode == "표" or not r.charts:
            for t in r.tables or [{"title": c.title, "columns": c.columns, "rows": c.rows} for c in r.charts]:
                st.markdown(f'<div class="nx-lbl">{ui.escape(t["title"] or "표")}</div>', unsafe_allow_html=True)
                st.dataframe(_df(t["columns"], t["rows"]), hide_index=True, width="stretch")
        elif n > 1 and S.wide:
            cols = st.columns(n)
            for i, (col, ch) in enumerate(zip(cols, r.charts)):
                with col:
                    draw_chart(ch, 300, key=f"w{i}")
        elif n > 1 and S.viz_mode == "한번에":
            for i, ch in enumerate(r.charts):
                with st.container(border=True):
                    draw_chart(ch, 190, legend=False, key=f"s{i}")
        elif r.charts:
            i = 0
            if n > 1:
                if S.get("pager", 0) >= n:
                    S["pager"] = 0
                i = st.radio("차트 고르기", list(range(n)), horizontal=True, key="pager",
                             format_func=lambda k: ui.md(f"{k + 1}  {r.charts[k].title}"), label_visibility="collapsed")
            draw_chart(r.charts[i], 300 if n > 1 else 340, key=f"one{i}")
            if n > 1:  # 넘기기 — 위젯 값은 콜백에서만 바꿀 수 있음
                a, b, c = st.columns([1, 2, 1])
                a.button("‹", disabled=i == 0, key="prev", on_click=lambda: S.update(pager=i - 1))
                b.markdown(f'<div style="text-align:center" class="nx-meta">{i + 1} / {n}</div>', unsafe_allow_html=True)
                c.button("›", disabled=i == n - 1, key="next", on_click=lambda: S.update(pager=i + 1))
        src = next(((c.source, c.source_url) for c in r.charts if c.source_url), r.sources[0] if r.sources else ("", ""))
        st.markdown(ui.source_line(*src), unsafe_allow_html=True)


def answer_card(r: vm.Result, short=False):
    with st.container(key="card-answer"):
        h1, h2 = st.columns([5, 1], vertical_alignment="center")
        h1.markdown(ui.card_head("📝", "답변"), unsafe_allow_html=True)
        with h2.popover("⧉", help="답변 복사"):
            st.code(r.answer, language=None)
        if r.insufficient:
            st.warning("자료가 충분하지 않아 일부만 답했어요.")
        st.markdown(ui.answer_html(r.answer) or '<p class="nx-ans">답변이 비어 있어요.</p>', unsafe_allow_html=True)
        if r.summary:
            st.markdown(ui.kv("핵심 요약", r.summary), unsafe_allow_html=True)
        elif r.points:
            st.markdown(ui.bullets("핵심 요약", r.points), unsafe_allow_html=True)
        for c in r.caveats[:4]:  # 못 맞춘 조건 · 계산하지 못한 이유 — 답을 읽을 때 꼭 봐야 해서 펼쳐 둠
            st.caption(ui.md(f"⚠️ {c}"))
        if r.unverified:
            st.caption(ui.md(f"자료에서 확인되지 않은 숫자: {', '.join(r.unverified)}"))
        if not short:
            for name, url in r.sources[:3]:
                st.markdown(ui.table_row(name, url), unsafe_allow_html=True)
        with st.expander("질문을 이렇게 이해했어요", expanded=False):
            st.markdown(f"**재작성** · {ui.md(r.rewritten or '—')}")
            st.markdown(" ".join(ui.chip(c) for c in r.chips), unsafe_allow_html=True)
            for x in r.caveats[4:] + r.notes[:8]:
                st.caption(ui.md(x))
            if r.timings:
                st.caption("소요 · " + " · ".join(f"{k} {v:.1f}초" for k, v in r.timings.items() if isinstance(v, (int, float))))


def result():
    resp = S.resp
    r = vm.to_result(resp)
    st.markdown(ui.question_bubble(r.question, r.chips), unsafe_allow_html=True)
    if r.status == "out_of_scope":
        _, mid, _ = st.columns([1, 2, 1])
        with mid:
            answer_card(r)
    elif len(r.charts) > 1 and S.wide:
        viz_card(r)
        answer_card(r, short=True)
    else:
        cols = st.columns([5, 2, 5] if CHARACTER.exists() else [1, 1])
        with cols[0]:
            viz_card(r)
        if CHARACTER.exists():
            cols[1].image(str(CHARACTER), width="stretch")
        with cols[-1]:
            answer_card(r)
    # 이어서 물어보기
    st.write("")
    fu = st.columns([1] + [2] * len(vm.FOLLOW_UPS) + [1])
    for col, f in zip(fu[1:-1], vm.FOLLOW_UPS):
        if col.button(ui.md(f), key=f"fu-{f}", width="stretch"):
            ask(f"{r.question} {f}")
    q = st.chat_input("이어서 물어보세요…")
    if q:
        ask(q)


# ── 10·11 히스토리 ──────────────────────────────────────────────
def history():
    if not S.history:
        st.markdown('<div class="nx-empty"><div class="nx-h1" style="font-size:22px">아직 물어본 질문이 없어요</div>'
                    '<div class="nx-sub">첫 질문을 하면 여기에 차곡차곡 쌓여요.</div></div>', unsafe_allow_html=True)
        _, mid, _ = st.columns([2, 1, 2])
        if mid.button("첫 질문 하러 가기 ›", type="primary", width="stretch"):
            S.page, S.screen = "Agent", "home"
            st.rerun()
        return
    left, right = st.columns([7, 5])
    with left:
        a, b = st.columns([1, 1], vertical_alignment="bottom")
        a.markdown(f'<div style="font-size:24px;font-weight:700">히스토리</div><div class="nx-meta">지금까지 물어본 질문 '
                   f'{len(S.history)}개</div>', unsafe_allow_html=True)
        kw = b.text_input("검색", placeholder="🔍 질문·지역·대상으로 검색", label_visibility="collapsed")
        only_star = st.segmented_control("보기", ["전체", "⭐ 즐겨찾기"], default="전체", key="hfilter",
                                         label_visibility="collapsed") == "⭐ 즐겨찾기"
        items = [h for h in S.history if (not only_star or h["star"])
                 and (not kw or kw in h["question"] or any(kw in c for c in h["chips"]))]
        for g, rows in vm.group_history(items):
            st.markdown(f'<div class="nx-lbl">{g}</div>', unsafe_allow_html=True)
            for h in rows:
                sel = h["id"] == S.hist_sel
                with st.container(key=f"card{'-sel' if sel else ''}-h-{h['id']}"):
                    c1, c2, c3, c4 = st.columns([8, 1.2, 0.8, 0.8], vertical_alignment="center")
                    if c1.button(ui.md(h["question"]), key=f"hq-{h['id']}", type="tertiary"):
                        S.hist_sel = h["id"]
                        st.rerun()
                    c1.markdown("".join(ui.chip(c) for c in h["chips"]), unsafe_allow_html=True)
                    c2.markdown(f'<div class="nx-meta">{vm.time_label(h["at"])}</div>', unsafe_allow_html=True)
                    if c3.button("⭐" if h["star"] else "☆", key=f"hs-{h['id']}", type="tertiary"):
                        h["star"] = not h["star"]
                        _save_history()
                        st.rerun()
                    if c4.button("🗑", key=f"hd-{h['id']}", type="tertiary", help="삭제"):
                        S.history = [x for x in S.history if x["id"] != h["id"]]
                        _save_history()
                        st.rerun()
    with right:
        h = next((x for x in S.history if x["id"] == S.hist_sel), S.history[0])
        r = vm.to_result(h["resp"])
        with st.container(key="card-preview"):
            st.markdown(f'<div class="nx-lbl" style="display:flex;justify-content:space-between"><span>미리보기</span>'
                        f'<span>{vm.time_label(h["at"])}</span></div><div style="font-size:17px;font-weight:700;margin:6px 0">'
                        f'{ui.escape(r.question)}</div>' + "".join(ui.chip(c) for c in r.chips), unsafe_allow_html=True)
            if r.charts:
                draw_chart(r.charts[0], 250, key=f"pv-{h['id']}")
            st.markdown(ui.answer_html(r.answer), unsafe_allow_html=True)
            if r.sources:
                st.markdown(f'<div class="nx-meta">출처 · {ui.escape(r.sources[0][0])}</div>', unsafe_allow_html=True)
            a, b = st.columns(2)
            if a.button("결과 다시 열기", type="primary", width="stretch"):
                S.resp, S.page, S["pager"] = h["resp"], "Agent", 0
                go("result")
            if b.button("이어서 질문", width="stretch"):
                S.draft, S.page = r.question, "Agent"
                go("home")


# ── 실행 ───────────────────────────────────────────────────────
header()
if S.page == "History":
    history()
elif S.pending_q:
    run_pending()
elif S.screen == "choose" and S.resp:
    choose()
elif S.screen == "clarify" and S.resp:
    clarify()
elif S.screen == "result" and S.resp:
    result()
else:
    home()
