"""
쿼리 모듈 v4 — 질문 → QueryAnalysis (1-1 ~ 1-5 를 순서대로, 단계마다 StepTrace)

  analyze(question)                               HCX 1회 (재작성 v3 슬롯 호출)
  analyze(question, previous=a, selections={…})   되묻기 응답: HCX 다시 안 부르고 고른 값으로 이어서

  단계                                            함수 (노트북에서 따로 불러 실험 가능)
  1-1 재작성(v3, HCX)                             backend.rag.query_analyzer.run_pipeline
      시점 규칙                                   clarify.apply_time_rules
  1-2·1-3 동의어 조회 + 슬롯 접지                 lexicon.Lexicon.resolve · grounding.ground_slots
  1-4 필수 슬롯 확인·되묻기                       clarify.check
  1-5 서브쿼리 분리                               decompose.decompose
  1-1 검색 문장 + View 입력(view_bundle)          search_text.v3_text / llm_text · adapter.to_view_bundle

반환 dict = schemas.query_v4.QueryAnalysis
  status = ok (view_bundle 을 그대로 POST /api/v1/rag/views 로) / needs_clarification (clarifications) / out_of_scope
  state  = 이어서 분석하는 데 필요한 값 (재작성 슬롯·하위 슬롯·의도). 되묻기 응답 때 previous 로 그대로 돌려보냄
"""
from dataclasses import asdict

from backend.core.settings_v4 import with_overrides
from backend.core.tracking import Tracer
from backend.rag.query_analyzer.adapter import is_out_of_scope, sub_intents_of, to_view_bundle
from backend.rag.query_analyzer.v4.clarify import apply_selections, apply_time_rules, check
from backend.rag.query_analyzer.v4.decompose import concepts, decompose
from backend.rag.query_analyzer.v4.grounding import ground_slots
from backend.rag.query_analyzer.v4.search_text import llm_text, v3_text

STRING_SLOTS = ("지역", "전출지", "전입지", "대상", "지표", "성별", "국적", "조건", "이동", "비교축")


def _strip_intent(slots):
    return {k: list(v) if isinstance(v, (list, tuple)) else [v] for k, v in (slots or {}).items() if k != "의도" and v}


def _as_date(today):
    from datetime import date
    return date.fromisoformat(today) if isinstance(today, str) and today else today


def rewrite_v3(question, today=None):
    """1-1 재작성 모듈 v3 (HCX 1회) → state. today: 'YYYY-MM-DD' 또는 date ('작년'·'최근 N년' 기준)"""
    today = _as_date(today)
    from backend.rag.query_analyzer import run_pipeline
    from backend.rag.query_analyzer.sentence import slots_to_sentence
    res = run_pipeline(question, today)
    v = res["valid"]
    subs = [x for x in v.get("sub_slots") or [] if slots_to_sentence(x)]      # sub_intents_of·make_bundle 과 같은 기준
    return {"bundle": asdict(res["bundle"]), "raw_slots": _strip_intent(v["slots"]),
            "sub_slots": [_strip_intent(x) for x in subs],
            "intents": list(v["slots"].get("의도") or []), "sub_intents": sub_intents_of(v),
            "hcx_ok": bool(res["slot"].get("parsed")), "hcx_error": res["slot"].get("error") or ""}


def canonical_slots(raw, grounded):
    """접지 결과로 슬롯 문자열 표준화 (View 입력용). 대상·지표는 CSV 이름과 정확·표기 변형으로 맞을 때만 바꿈"""
    out = {k: list(v) for k, v in raw.items()}
    for k in STRING_SLOTS:
        if k not in grounded:
            continue
        vals = []
        for sv in grounded[k]:
            # 대상·지표는 확실할 때만 CSV 이름으로: 사전(rule·learned·term) 또는 CSV 정확 일치(띄어쓰기만 다름).
            # 표기 변형('인구수' → '인구')·포함 일치는 뜻이 바뀔 수 있어 원래 값 유지 (CSV 이름은 slots[].csv 에 근거로 남음)
            sure = sv["grounded"] and (k not in ("대상", "지표") or sv["source"] in ("rule", "learned", "term>csv")
                                       or (sv["source"] == "csv" and sv.get("match") == "exact"))
            vals.append(sv["value"] if sure else sv["raw"])
        out[k] = list(dict.fromkeys(str(v) for v in vals))
    return out


def analyze(question, today=None, *, query_id=None, overrides=None, previous=None, selections=None, tracer=None,
            idx=None, chat_fn=None):
    from backend.rag.csv_index.store import load_index
    from backend.rag.query_analyzer.v4.lexicon import get_lexicon
    s = with_overrides(overrides)
    tr = tracer or Tracer("analyze", params={"settings": s.model_dump(), "question": question}, save=s.save_runs)
    idx = idx or load_index()
    lex = get_lexicon(idx, s)
    notes = []

    with tr.step("1-1 재작성(v3)", reuse_previous=bool(previous)) as st:
        state = dict((previous or {}).get("state") or {}) or rewrite_v3(question, today)
        if not state.get("hcx_ok", True):
            notes.append(f"HCX 슬롯 추출 실패 → 코드 추출 값만 사용: {state.get('hcx_error')}")
        st.output = {"rewritten": state["bundle"].get("rewritten"), "raw_slots": state["raw_slots"],
                     "n_sub": len(state["sub_slots"]), "intents": state["intents"]}

    base = {"question": question, "query_id": query_id, "bundle": state["bundle"], "notes": notes, "applied_rules": [],
            "slots": {}, "clarifications": [], "sub_queries": [], "decompose_reason": "", "search_text": "",
            "view_bundle": None}
    if is_out_of_scope(state["bundle"]):
        tr.save()
        return {**base, "status": "out_of_scope", "state": state, "trace": tr.as_list()}

    raw = state["raw_slots"]
    if selections:
        with tr.step("1-4 되묻기 응답 반영", selections=selections) as st:
            raw = apply_selections(raw, selections)
            st.output = raw
    if not (raw.get("대상") or raw.get("지표")):
        with tr.step("1-2 대상 보충 (질문 문장 × CSV 값 사전)", min_alias_len=s.min_alias_len) as st:
            found = [(k, v, n) for k, v, n in lex.scan(question) if n]
            if found:
                raw = {**raw, "지표": list(dict.fromkeys(v for _, v, _ in found))}
                notes.append(f"재작성 모듈이 대상·지표를 내지 않아 질문 속 CSV 표현으로 채움: {[(k, v) for k, v, _ in found]}")
            st.output = found
    with tr.step("시점 규칙", base_year=s.base_year, trend_years=s.trend_years) as st:
        raw, rules = apply_time_rules(raw, question, state["intents"], s)
        st.output = {"시점": raw.get("시점"), "rules": rules}
    state = {**state, "raw_slots": raw}

    with tr.step("1-2·1-3 동의어 조회 + 슬롯 접지", csv_scope=s.csv_scope, contain_min_len=s.contain_min_len,
                 n_tables=len(idx.table_ids(s.csv_scope))) as st:
        grounded, gnotes = ground_slots(raw, lex)
        st.output = {k: [(v["raw"], v["value"] if not isinstance(v["value"], dict) else str(v["value"]), v["source"],
                          v["n_tables"]) for v in vs] for k, vs in grounded.items()}
        st.notes = gnotes
    notes += gnotes

    with tr.step("1-4 필수 슬롯 확인", required=s.required_slots, n_options=s.n_options) as st:
        clar = check(grounded, raw, lex, s)
        st.output = [{"slot": c["slot"], "reason": c["reason"], "n_options": len(c["options"])} for c in clar]
    base.update(slots=grounded, applied_rules=rules)
    if clar:
        tr.save()
        return {**base, "status": "needs_clarification", "clarifications": clar, "state": state, "trace": tr.as_list()}

    with tr.step("1-5 서브쿼리 분리", split_when_no_common_table=s.split_when_no_common_table,
                 max_sub_queries=s.max_sub_queries) as st:
        subs, reason = decompose(grounded, raw, state["sub_slots"], state["intents"], state["sub_intents"], lex, s)
        st.output = {"reason": reason, "subs": [(x["id"], x["text"]) for x in subs]}

    with tr.step("1-1 검색 문장 + View 입력", mode=s.search_text_mode) as st:
        b = state["bundle"]
        intent = (state["intents"] or [b.get("intent")])[0]
        main_f = canonical_slots(raw, grounded)
        sub_texts, sub_f, sub_intents = [], [], []
        from_v3 = reason.startswith("재작성")
        for i, x in enumerate(subs):
            g, _ = ground_slots(x["slots"], lex)
            sub_f.append(canonical_slots(x["slots"], g))
            sub_texts.append((b.get("sub_questions") or [])[i] if from_v3 and i < len(b.get("sub_questions") or [])
                             else x["text"])
            sub_intents.append(x["intent"])
        rb = {"original": question, "rewritten": b.get("rewritten") or question, "intent": intent, "filters": main_f,
              "sub_questions": sub_texts, "sub_filters": sub_f or None}
        vb, vnotes = to_view_bundle(rb, query_id, "rewritten", sub_intents or None)
        names = [c["name"] for c in concepts(grounded)]
        # 재작성 문장이 슬롯을 담지 못했으면(되묻기로 채운 값, 재작성 실패로 원문 그대로) 슬롯 값으로 검색 문장
        from backend.rag.query_analyzer.query_bundle import slot_text
        weak = bool(selections) or (rb["rewritten"] or "").strip() == question.strip()
        # [Step 4 정리] 의도 값('값 조회'·'추이')은 검색어가 아님 → 슬롯 문장에서 뺌 ('1인가구 값 조회' 가 되던 문제)
        no_intent = {k: v for k, v in (vb.get("filters") or {}).items() if k != "의도"}
        text = v3_text(slot_text(no_intent) if weak else rb["rewritten"], vb.get("filters"), names)
        if s.search_text_mode == "llm":
            try:
                terms = names + [r["name"] for k in ("지표", "대상") for sv in grounded.get(k, []) for r in sv["csv"]]
                text, llm_subs = llm_text(question, sub_texts, terms, chat_fn)
                if len(llm_subs) == len(vb.get("sub_questions") or []):
                    vb["sub_questions"] = llm_subs
            except Exception as e:  # noqa: BLE001
                notes.append(f"검색 문장 LLM 실패 → v3 문장 사용: {e.__class__.__name__}: {str(e)[:120]}")
        vb["search_text"] = text
        st.output = {"search_text": text, "sub_questions": vb.get("sub_questions"), "filters": vb.get("filters")}
        notes += vnotes

    out = {**base, "status": "ok", "sub_queries": subs, "decompose_reason": reason, "search_text": text,
           "view_bundle": vb, "state": state, "trace": tr.as_list()}
    tr.save(out)
    return out
