"""
KOSIS RAG 50문항 Human 검수 앱 (Streamlit)

노트북 [Cell 2]가 만든 eval_50_auto_results.json 을 읽어서
요약표 / 검수 카드 / 판정 저장을 한 화면에서 처리합니다.

실행:  streamlit run review_app.py
요구:  streamlit>=1.35, pandas
"""
import html
import json
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="KOSIS RAG 검수", page_icon="⚡", layout="wide")

METRICS = ["검색_적합성", "원본_수치_추출", "Context_충분성", "변화율_응답_완성도", "자동_환각_검증"]
GRADES = ["PASS", "PARTIAL", "FAIL"]
COLORS = {"PASS": ("#d4edda", "#155724"), "PARTIAL": ("#fff3cd", "#856404"), "FAIL": ("#f8d7da", "#721c24")}
ICON = {"PASS": "🟢", "PARTIAL": "🟡", "FAIL": "🔴"}
PAGES = ["📊 요약표", "🔍 검수 카드"]


# ---------------------------------------------------------------- helpers
def badge(v: str) -> str:
    bg, fg = COLORS.get(v, ("#e2e8f0", "#000000"))
    return (f'<span style="background:{bg};color:{fg};font-weight:600;'
            f'padding:2px 8px;border-radius:6px;white-space:nowrap">{v}</span>')


def icon(v: str) -> str:
    return f"{ICON.get(v, '⚪')} {v}"


def rule_overall(d: dict) -> str:
    """노트북과 동일한 자동 종합 규칙"""
    if all(d[m] == "PASS" for m in METRICS):
        return "PASS"
    return "FAIL" if "FAIL" in (d["검색_적합성"], d["변화율_응답_완성도"]) else "PARTIAL"


def highlight(text: str, nums) -> str:
    out = html.escape(text or "")
    for n in sorted(set(nums or []), key=len, reverse=True):
        e = html.escape(n)
        out = out.replace(e, f'<mark style="background:#fecaca;padding:0 2px">{e}</mark>')
    return out.replace("\n", "<br>")


def recompute(rows):
    """조건 필터링 표가 정확히 2행이면 변화량/변화율 검산"""
    try:
        if len(rows) != 2:
            return None
        a, b = float(rows[0]["value"]), float(rows[1]["value"])
        pa, pb = rows[0].get("period_label", "A"), rows[1].get("period_label", "B")
        pct = (b - a) / a * 100 if a else float("nan")
        return f"검산: {pa} {a:,.0f} → {pb} {b:,.0f} = {b - a:+,.0f} ({pct:+.2f}%)"
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------- sidebar: 파일
with st.sidebar:
    st.header("📁 파일")
    json_path = Path(st.text_input("자동화 결과 JSON", "kosis_data/rag_views/eval_50_auto_results.json"))
    csv_path = Path(st.text_input("최종 CSV", "kosis_data/rag_views/eval_50_human_final.csv"))
    if st.button("🔄 디스크에서 다시 읽기"):
        st.session_state.pop("data", None)
        for k in [k for k in st.session_state if "::" in str(k)]:
            del st.session_state[k]

if "data" not in st.session_state or st.session_state.get("data_path") != str(json_path):
    if not json_path.exists():
        st.error(f"JSON 파일이 없습니다: `{json_path}`\n\n노트북 [Cell 2]를 먼저 실행하세요.")
        st.stop()
    rows = json.loads(json_path.read_text(encoding="utf-8"))
    st.session_state.data = {r["id"]: r for r in rows}
    st.session_state.data_path = str(json_path)

data: dict = st.session_state.data
all_ids = sorted(data)


def save_all():
    ordered = [data[k] for k in sorted(data)]
    json_path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
    out = []
    for r in ordered:
        hm = r["human_review"]
        ev0 = (r.get("evidence_sources") or [{}])[0]
        out.append({
            "id": r["id"], "survey": r["survey"], "test_type": r["test_type"],
            "target_modules": r.get("target_modules", ""), "question": r["question"],
            "ai_answer": r["ai_answer"],
            "근거_Facts_요약": " | ".join(ev0.get("facts_summary", [])),
            "KOSIS_링크": ev0.get("kosis_url", ""), "로컬_CSV": ev0.get("raw_csv", ""),
            **{m: hm[m] for m in METRICS},
            "최종_HUMAN_평가": hm["최종_HUMAN_평가"],
            "human_comment": hm.get("human_comment", ""),
            "reviewed": hm.get("reviewed", False),
        })
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(out).to_csv(csv_path, index=False, encoding="utf-8-sig")


# ---------------------------------------------------------------- sidebar: 필터 & 진행률
with st.sidebar:
    st.header("🔎 필터")
    view_filter = st.radio("표시 범위", ["전체", "PARTIAL/FAIL만", "미검수만"], horizontal=True)
    surveys = sorted({data[i]["survey"] for i in all_ids})
    types = sorted({data[i]["test_type"] for i in all_ids})
    sel_surveys = st.multiselect("조사명", surveys)
    sel_types = st.multiselect("유형", types)

    def keep(r):
        hm = r["human_review"]
        if view_filter == "PARTIAL/FAIL만" and hm["최종_HUMAN_평가"] == "PASS":
            return False
        if view_filter == "미검수만" and hm.get("reviewed"):
            return False
        if sel_surveys and r["survey"] not in sel_surveys:
            return False
        if sel_types and r["test_type"] not in sel_types:
            return False
        return True

    filtered = [i for i in all_ids if keep(data[i])]
    st.session_state._filtered = filtered

    done = sum(bool(data[i]["human_review"].get("reviewed")) for i in all_ids)
    st.header("📈 진행률")
    st.progress(done / max(len(all_ids), 1), text=f"검수 완료 {done} / {len(all_ids)}")

    st.header("🧭 화면")
    st.radio("화면", PAGES, key="page", label_visibility="collapsed")

if not filtered:
    st.info("필터 조건에 맞는 문항이 없습니다.")
    st.stop()

if st.session_state.get("qid") not in filtered:
    st.session_state.qid = filtered[0]

if msg := st.session_state.pop("_toast", None):
    st.toast(msg, icon="💾")


# ---------------------------------------------------------------- callbacks
def go(delta: int):
    lst = st.session_state._filtered
    cur = st.session_state.qid
    i = lst.index(cur) if cur in lst else 0
    st.session_state.qid = lst[(i + delta) % len(lst)]


def open_from_table():
    sel = st.session_state.overview.selection.rows
    if sel:
        st.session_state.qid = st.session_state._table_ids[sel[0]]
        st.session_state.page = PAGES[1]


def save_review(qid: str, advance: bool = False):
    hm = data[qid]["human_review"]
    for m in METRICS:
        hm[m] = st.session_state[f"{qid}::{m}"]
    hm["최종_HUMAN_평가"] = st.session_state[f"{qid}::final"]
    hm["human_comment"] = st.session_state[f"{qid}::comment"]
    hm["reviewed"] = True
    save_all()
    st.session_state._toast = f"{qid} 저장 완료"
    if advance:
        go(1)


def reset_to_auto(qid: str):
    r = data[qid]
    am, hm = r["auto_metrics"], r["human_review"]
    for m in METRICS:
        hm[m] = am[m]
        st.session_state[f"{qid}::{m}"] = am[m]
    hm["최종_HUMAN_평가"] = am["자동_종합_판정"]
    st.session_state[f"{qid}::final"] = am["자동_종합_판정"]
    hm["human_comment"] = ""
    st.session_state[f"{qid}::comment"] = ""
    hm["reviewed"] = False
    save_all()
    st.session_state._toast = f"{qid} 자동 판정으로 되돌림"


def grade_radio(label, key, current):
    kw = {} if key in st.session_state else {"index": GRADES.index(current) if current in GRADES else 1}
    return st.radio(label, GRADES, key=key, horizontal=True, format_func=icon, **kw)


# ================================================================ 페이지 1: 요약표
if st.session_state.page == PAGES[0]:
    st.title("📊 Fast_eval_도구")

    finals = [data[i]["human_review"]["최종_HUMAN_평가"] for i in all_ids]
    c = st.columns(4)
    c[0].metric("🟢 PASS", finals.count("PASS"))
    c[1].metric("🟡 PARTIAL", finals.count("PARTIAL"))
    c[2].metric("🔴 FAIL", finals.count("FAIL"))
    c[3].metric("✅ 검수 완료", f"{done}/{len(all_ids)}")

    table = []
    for i in filtered:
        r = data[i]
        hm = r["human_review"]
        table.append({
            "ID": i, "조사명": r["survey"], "유형": r["test_type"], "질문": r["question"],
            **{m.replace("_", " "): icon(hm[m]) for m in METRICS},
            "최종 HUMAN": icon(hm["최종_HUMAN_평가"]),
            "검수": "✅" if hm.get("reviewed") else "⏳",
            "코멘트": hm.get("human_comment", ""),
        })
    st.session_state._table_ids = filtered
    st.caption(f"표시 {len(filtered)}건 · 행을 클릭하면 해당 문항의 검수 카드로 이동합니다.")
    st.dataframe(
        pd.DataFrame(table), hide_index=True, height=min(38 * len(table) + 40, 900),
        on_select=open_from_table, selection_mode="single-row", key="overview",
        column_config={"질문": st.column_config.TextColumn(width="large"),
                       "코멘트": st.column_config.TextColumn(width="medium")},
    )

# ================================================================ 페이지 2: 검수 카드
else:
    # --- 네비게이션
    n1, n2, n3 = st.columns([1, 6, 1])
    n1.button("◀ 이전", on_click=go, args=(-1,))
    n2.selectbox(
        "문항", filtered, key="qid", label_visibility="collapsed",
        format_func=lambda i: f"{i} · {ICON[data[i]['human_review']['최종_HUMAN_평가']]} "
                              f"{'✅' if data[i]['human_review'].get('reviewed') else '⏳'} "
                              f"[{data[i]['test_type']}] {data[i]['question'][:60]}",
    )
    n3.button("다음 ▶", on_click=go, args=(1,))

    qid = st.session_state.qid
    r = data[qid]
    am, ar, hm = r["auto_metrics"], r["auto_reasons"], r["human_review"]

    st.markdown(
        f"### [{qid}] {r['survey']} &nbsp; `{r['test_type']}` &nbsp; `모듈: {r.get('target_modules', '')}` "
        f"&nbsp; {badge(hm['최종_HUMAN_평가'])} {'✅ 검수완료' if hm.get('reviewed') else '⏳ 자동초안'}",
        unsafe_allow_html=True,
    )

    left, right = st.columns([3, 2], gap="large")

    # --- 왼쪽: 질문 / 답변 / 지표
    with left:
        with st.container(border=True):
            st.markdown(f"**❓ 질문**  \n{r['question']}")
            st.markdown(f"🎯 **통과 기준**: {r['pass_criteria']}")
            st.caption(f"🔎 재작성 검색어: {r.get('rewritten_query', '')}")

        with st.container(border=True):
            st.markdown("**🤖 AI 답변**")
            st.markdown(highlight(r["ai_answer"], r.get("unverified_numbers")), unsafe_allow_html=True)
            kp = ", ".join(r.get("ai_key_points") or []) or "없음"
            st.caption(f"핵심 수치: {kp} · insufficient = {r['insufficient']}")
            if r.get("unverified_numbers"):
                st.error(f"⚠️ 컨텍스트에 없는 수치(붉은 표시): {', '.join(r['unverified_numbers'])}")
            else:
                st.success("✅ 미검증 수치 없음")

        rows_html = "".join(
            f"<tr><td style='padding:6px;font-weight:600'>{n}. {m.replace('_', ' ')}</td>"
            f"<td style='text-align:center'>{badge(am[m])}</td>"
            f"<td style='text-align:center'>{badge(hm[m])}</td>"
            f"<td style='padding:6px'>{html.escape(str(ar.get(m, '')))}</td></tr>"
            for n, m in enumerate(METRICS, 1)
        )
        st.markdown(
            "<table style='width:100%;border-collapse:collapse;font-size:14px'>"
            "<thead><tr style='border-bottom:2px solid #888'><th>지표</th><th>자동</th><th>HUMAN</th>"
            f"<th style='text-align:left'>자동 진단 근거</th></tr></thead><tbody>{rows_html}</tbody></table>",
            unsafe_allow_html=True,
        )

    # --- 오른쪽: 판정 입력
    with right:
        with st.form(f"form_{qid}", border=True):
            st.markdown("#### ✍️ 판정 입력")
            for m in METRICS:
                grade_radio(m.replace("_", " "), f"{qid}::{m}", hm[m])
            st.divider()
            grade_radio("**최종 HUMAN 평가**", f"{qid}::final", hm["최종_HUMAN_평가"])
            ck = f"{qid}::comment"
            st.text_area("코멘트", key=ck, height=110,
                         **({} if ck in st.session_state else {"value": hm.get("human_comment", "")}))
            b1, b2 = st.columns(2)
            b1.form_submit_button("💾 저장", on_click=save_review, args=(qid, False))
            b2.form_submit_button("💾 저장 후 다음 ▶", on_click=save_review, args=(qid, True),
                                  type="primary")
        st.caption(f"참고 · 현재 세부 지표 기준 규칙 종합: {icon(rule_overall(hm))}")
        st.button("↺ 자동 판정으로 되돌리기", on_click=reset_to_auto, args=(qid,))

    # --- 근거 자료
    st.markdown("#### 📂 근거 자료")
    for n, ev in enumerate(r.get("evidence_sources", []), 1):
        with st.expander(f"#{n} {ev['title']}  ·  {ev['view_id']}", expanded=(n == 1)):
            st.caption(f"{ev['survey_nm']} > {ev['tbl_nm']} · 수록기간 {ev['prd_range']} · 단위 {ev['unit'] or '없음'}")
            l1, l2 = st.columns([1, 3])
            l1.link_button("🌐 KOSIS 원본", ev["kosis_url"])
            l2.code(f"{ev['raw_csv']}  ({'존재' if ev['csv_exists'] else '없음'})", language=None)
            if ev.get("missing_conditions"):
                st.warning("누락/불일치 조건: " + ", ".join(ev["missing_conditions"]))

            f_col, t_col = st.columns([2, 3])
            with f_col:
                st.markdown("**📊 Facts (핵심 수치)**")
                st.markdown("\n".join(f"- {f}" for f in ev.get("facts_summary", [])) or "_(Facts 없음)_")
                for cv in ev.get("caveats") or []:
                    st.caption(f"ℹ️ {cv}")
            with t_col:
                cond = ev.get("condition_filtered_rows") or []
                if cond:
                    st.markdown(f"**📌 조건 필터링 표** `{ev.get('applied_conditions')}`")
                    st.dataframe(pd.DataFrame(cond), hide_index=True)
                    if chk := recompute(cond):
                        st.info(chk)
                elif ev.get("preview_rows"):
                    st.markdown("**📌 기본 미리보기 표**")
                    st.dataframe(pd.DataFrame(ev["preview_rows"]), hide_index=True)
                else:
                    st.caption("표 데이터 없음")

    with st.expander("🧾 LLM에 들어간 원본 프롬프트 컨텍스트"):
        st.code(r.get("prompt_context_raw", "") or "(없음)", language=None)
