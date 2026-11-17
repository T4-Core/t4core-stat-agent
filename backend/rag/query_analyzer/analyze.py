"""
질의 분석 — 질문 → QueryAnalysis (단계마다 trace)

  analyze(question)                               HCX 1회 (재작성 슬롯 추출)
  analyze(question, previous=a, selections={…})   되묻기 응답: HCX 다시 안 부르고 고른 값으로 이어서

  단계                                  함수
  재작성 (HCX)                          rewrite.run_pipeline → rewrite_state
  지역 칸 바로잡기 · 대상 보충           fix_region_slots · lexicon.Lexicon.scan
  시점 규칙                             clarify.apply_time_rules
  동의어 조회 + 슬롯 접지                lexicon.Lexicon.resolve · grounding.ground_slots
  필수 슬롯 확인 · 되묻기 (또는 가정)    clarify.check · soft_fill
  서브쿼리 분리                         decompose.decompose
  검색 문장 + View 입력(view_bundle)     search_text.rule_text / llm_text · adapter.to_view_bundle · roles.add_role_units

반환 dict = schemas.query.QueryAnalysis
  status = ok (view_bundle → 검색·View) / needs_clarification (clarifications) / out_of_scope
  state  = 이어서 분석하는 데 필요한 값 (재작성 슬롯·하위 슬롯·의도). 되묻기 응답 때 previous 로 그대로 돌려보냄
"""
import re
from dataclasses import asdict

from backend.core.settings import with_overrides
from backend.core.tracking import Tracer
from backend.rag.csv_index.store import norm
from backend.rag.query_analyzer.adapter import is_out_of_scope, sub_intents_of, to_view_bundle
from backend.rag.query_analyzer.clarify import apply_selections, apply_time_rules, check
from backend.rag.query_analyzer.decompose import REGION_SLOTS, _numeric, concepts, decompose
from backend.rag.query_analyzer.grounding import ground_slots
from backend.rag.query_analyzer.search_text import llm_text, rule_text

STRING_SLOTS = ("지역", "전출지", "전입지", "대상", "지표", "성별", "국적", "조건", "이동", "비교축")


def _strip_intent(slots):
    return {k: list(v) if isinstance(v, (list, tuple)) else [v] for k, v in (slots or {}).items() if k != "의도" and v}


def _as_date(today):
    from datetime import date
    return date.fromisoformat(today) if isinstance(today, str) and today else today


def rewrite_state(question, today=None):
    """재작성 (HCX 1회) → state. today: 'YYYY-MM-DD' 또는 date ('작년'·'최근 N년' 기준)"""
    today = _as_date(today)
    from backend.rag.query_analyzer.rewrite import run_pipeline
    from backend.rag.query_analyzer.sentence import slots_to_sentence
    res = run_pipeline(question, today)
    v = res["valid"]
    subs = [x for x in v.get("sub_slots") or [] if slots_to_sentence(x)]  # sub_intents_of·make_bundle 과 같은 기준
    # 재작성이 코드로 지표별로 나눈 하위 질문(sub_source=code)은 쓰지 않음 → 서브쿼리 분리가 CSV 표 기준으로 판단
    code_split = v.get("sub_source") == "code"
    if code_split:
        subs = []
    return {"bundle": asdict(res["bundle"]), "raw_slots": _strip_intent(v["slots"]),
            "sub_slots": [_strip_intent(x) for x in subs],
            "intents": list(v["slots"].get("의도") or []), "sub_intents": [] if code_split else sub_intents_of(v),
            "hcx_ok": bool(res["slot"].get("parsed")), "hcx_error": res["slot"].get("error") or ""}


def tidy_text(text):
    """검색 문장 다듬기 — resolve.tidy_query 와 같음 (숫자 조각·같은 단어 반복·더 긴 단어에 든 단어 빼기)"""
    from backend.rag.search.resolve import tidy_query
    return tidy_query(text)


def rule_state(question, today=None, error=""):
    """HCX 없이 코드 추출만으로 만든 state — 재작성이 실패·오류·'범위 밖' 일 때의 대체
    시점·지역·성별·연령·조건은 rule_extract, 의도는 질문의 단어로. 대상·지표는 비워 두고 대상 보충 단계(CSV 값 사전)가 채움"""
    from backend.rag.query_analyzer.extract import rule_extract
    q2, found, _ = rule_extract(question, _as_date(today) or __import__("datetime").date.today())
    intent = next((v for k, v in (("추이", "추이"), ("변화", "추이"), ("순위", "순위"), ("가장", "순위"), ("비교", "비교"),
                                  ("별로", "비교"), ("비율", "구성비"), ("비중", "구성비")) if k in question), "값 조회")
    slots = {k: list(v) for k, v in found.items() if v}
    return {"bundle": {"original": question, "rewritten": question, "intent": intent, "sub_questions": []},
            "raw_slots": slots, "sub_slots": [], "intents": [intent], "sub_intents": [],
            "hcx_ok": False, "hcx_error": error or "코드 추출만 사용"}


def domain_terms(question, lex):
    """질문에 통계 용어가 있는가 — CSV 값 사전 표현 + 일상어 사전(결혼→혼인, 이사→인구이동)
    '범위 밖' 판정을 뒤집을 근거이자, 대상·지표가 비었을 때 채울 값"""
    out = [v for k, v, n in lex.scan(question) if n and not _numeric(k) and len(norm(k)) >= 2]
    try:
        from backend.rag.search.query import synonyms
        out += [t for t in synonyms(question) if t not in out]
    except Exception:  # noqa: BLE001  (검색 패키지가 없어도 분석은 계속)
        pass
    return list(dict.fromkeys(out))


AXIS_WORDS = (("읍면동", "읍면동"), ("시군구", "시군구"), ("시도", "시도"), ("지역별", "지역"), ("행정구역", "행정구역"))


def soft_fill(raw, question, lex):
    """soft 모드: 필수 슬롯이 비어도 검색할 수 있게 채움 → (슬롯, 가정 메모)
      대상·지표 없음 → 질문의 통계 용어(domain_terms). 그것도 없으면 그대로 (검색 문장은 원문)
      비교축 없음   → '시도별'·'시군구별' 같은 말이 있으면 그 수준
      시점·지역 없음 → 채우지 않음 (View 단계 기본값: 최신 연도 · 전국 합계)"""
    out, memo = {k: list(v) for k, v in raw.items()}, []
    if not (out.get("대상") or out.get("지표")):
        terms = domain_terms(question, lex)
        if terms:
            out["지표"] = terms[:4]
            memo.append(f"대상·지표를 질문의 통계 용어로 채움: {terms[:4]}")
    if not out.get("비교축"):
        ax = next((v for k, v in AXIS_WORDS if k in question.replace(" ", "")), None)
        if ax and re.search(r"별|단위|마다", question):
            out["비교축"] = [ax]
            memo.append(f"비교축 '{ax}' (질문의 '…별')")
    if not out.get("시점"):
        memo.append("시점이 없어 최신 연도로 봄")
    if not out.get("지역") and not out.get("비교축"):
        memo.append("지역이 없어 전국으로 봄")
    return out, memo


_BASE_YEAR = {}


def data_base_year(idx, scope="selected", today=None):
    """CSV 값 사전의 최신 연도 (오늘 이후 연도 = 추계는 제외). 값 사전마다 한 번만 계산"""
    upto = (_as_date(today) or __import__("datetime").date.today()).year
    key = (id(idx), scope, upto)
    if key not in _BASE_YEAR:
        try:
            _BASE_YEAR[key] = idx.latest_year(scope=scope, upto=upto)
        except Exception:  # noqa: BLE001  (값 사전이 옛 모양이면 설정값)
            _BASE_YEAR[key] = None
    return _BASE_YEAR[key]


REGION_SHAPE = re.compile(r"^[가-힣]{1,6}(?:특별시|광역시|자치시|자치도|도|시|군|구|읍|면|동)$")


def region_shaped(v):
    """'안동군'·'부산진구' 처럼 지역 이름 모양인가 ('인구'·'가구'·'다시' 같은 말은 아님 — search.query 와 같은 예외)"""
    from backend.rag.search.query import NOT_REGION, NOT_REGION_WORDS
    t = str(v or "").split()[-1] if str(v or "").split() else ""
    return bool(REGION_SHAPE.match(t)) and not NOT_REGION.search(t) and t not in NOT_REGION_WORDS \
        and not re.search(r"(?:가구|주택|인구|세대|건수|명수|호수|평균|비율|이동|전입|전출|혼인|이혼|출생|사망)", t)


def fix_region_slots(raw, lex):
    """지역·전출지·전입지 칸의 값 중 지역으로는 CSV 근거가 없고 지표로는 근거가 있는 값 → 지표로 옮김
    (HCX 가 '혼인건수' 를 지역 칸에 넣은 경우. 재작성 모듈 검증을 지나쳐도 여기서 한 번 더). 반환: (슬롯, 옮긴 값 목록)"""
    from backend.rag.ingestion.normalize import std_geo_name
    out, moved = {k: list(v) for k, v in raw.items()}, []
    for k in REGION_SLOTS:
        keep = []
        for v in out.get(k) or []:
            rg = lex.best(std_geo_name(v), k)
            shaped = region_shaped(v)
            hi = None if (rg and rg.grounded) or _numeric(v) or shaped else lex.best(v, "지표")
            if hi and hi.grounded and hi.source != "contains":  # 포함 일치만으로는 옮기지 않음 (뜻이 달라질 수 있음)
                moved.append((k, v))
            else:
                keep.append(v)
        if k in out:
            out[k] = keep
    for _, v in moved:
        out.setdefault("지표", [])
        if v not in out["지표"]:
            out["지표"].append(v)
    return {k: v for k, v in out.items() if v}, moved


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
    from backend.rag.query_analyzer.lexicon import get_lexicon
    s = with_overrides(overrides)
    idx = idx or load_index()
    if getattr(s, "base_year_mode", "fixed") == "data" and not (overrides or {}).get("base_year"):
        by = data_base_year(idx, s.csv_scope, today)  # '요즘' = 자료의 최신 연도 (2026 고정 대신)
        if by and by != s.base_year:
            s = s.model_copy(update={"base_year": by})
    tr = tracer or Tracer("analyze", params={"settings": s.model_dump(), "question": question}, save=s.save_runs)
    lex = get_lexicon(idx, s)
    notes = []

    with tr.step("재작성", reuse_previous=bool(previous)) as st:
        soft = getattr(s, "clarify_mode", "strict") == "soft"
        state = dict((previous or {}).get("state") or {})
        if not state:
            try:
                state = rewrite_state(question, today)
            except Exception as e:  # noqa: BLE001 soft: 재작성 단계의 오류로 분석 전체가 죽지 않게
                if not soft:
                    raise
                state = rule_state(question, today, f"{e.__class__.__name__}: {str(e)[:120]}")
                notes.append(f"재작성 단계 오류 → 코드 추출 값으로 진행: {state['hcx_error']}")
        if soft and is_out_of_scope(state["bundle"]):  # '범위 밖' 이라도 통계 용어가 있으면 검색
            terms = domain_terms(question, lex)
            if terms:
                state = rule_state(question, today, "범위 밖 판정을 뒤집음")
                notes.append(f"재작성 모듈은 '범위 밖' 이라 했지만 질문에 통계 용어 {terms[:5]} 가 있어 검색함")
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
        with tr.step("되묻기 응답 반영", selections=selections) as st:
            raw = apply_selections(raw, selections)
            st.output = raw
    with tr.step("지역 칸 바로잡기 (지역으로 접지 안 되고 지표로 접지되는 값 → 지표)") as st:
        raw, moved = fix_region_slots(raw, lex)
        st.output = moved
        if moved:
            notes.append(f"지역 칸의 지표 이름을 지표로 옮김: {moved}")
    if not (raw.get("대상") or raw.get("지표")):
        with tr.step("대상 보충 (질문 문장 × CSV 값 사전)", min_alias_len=s.min_alias_len) as st:
            times = " ".join(str(t) for t in raw.get("시점") or [])
            found = [(k, v, n) for k, v, n in lex.scan(question)
                     if n and not _numeric(k) and not _numeric(v) and norm(k) not in norm(times)]
            if found:
                raw = {**raw, "지표": list(dict.fromkeys(v for _, v, _ in found))}
                notes.append(f"재작성 모듈이 대상·지표를 내지 않아 질문 속 CSV 표현으로 채움: {[(k, v) for k, v, _ in found]}")
            st.output = found
    with tr.step("시점 규칙", base_year=s.base_year, trend_years=s.trend_years) as st:
        raw, rules = apply_time_rules(raw, question, state["intents"], s)
        st.output = {"시점": raw.get("시점"), "rules": rules}
    state = {**state, "raw_slots": raw}

    with tr.step("동의어 조회 + 슬롯 접지", csv_scope=s.csv_scope, contain_min_len=s.contain_min_len,
                 n_tables=len(idx.table_ids(s.csv_scope))) as st:
        grounded, gnotes = ground_slots(raw, lex)
        st.output = {k: [(v["raw"], v["value"] if not isinstance(v["value"], dict) else str(v["value"]), v["source"],
                          v["n_tables"]) for v in vs] for k, vs in grounded.items()}
        st.notes = gnotes
    notes += gnotes

    with tr.step("필수 슬롯 확인", required=s.required_slots, n_options=s.n_options) as st:
        clar = check(grounded, raw, lex, s)
        st.output = [{"slot": c["slot"], "reason": c["reason"], "n_options": len(c["options"])} for c in clar]
    base.update(slots=grounded, applied_rules=rules)
    if clar and not soft:
        tr.save()
        return {**base, "status": "needs_clarification", "clarifications": clar, "state": state, "trace": tr.as_list()}
    if clar:  # soft: 멈추지 않고 가정으로 진행
        with tr.step("되묻기 대신 가정 (soft)", missing=[c["slot"] for c in clar]) as st:
            raw, memo = soft_fill(raw, question, lex)
            grounded, _ = ground_slots(raw, lex)
            state = {**state, "raw_slots": raw}
            st.output = memo
        base.update(slots=grounded, clarifications=clar)
        notes += [f"[가정] {m}" for m in memo]

    with tr.step("서브쿼리 분리", split_policy=s.split_policy, split_when_no_common_table=s.split_when_no_common_table,
                 max_sub_queries=s.max_sub_queries) as st:
        subs, reason = decompose(grounded, raw, state["sub_slots"], state["intents"], state["sub_intents"], lex, s)
        st.output = {"reason": reason, "subs": [(x["id"], x["text"]) for x in subs]}

    with tr.step("검색 문장 + View 입력", mode=s.search_text_mode) as st:
        b = state["bundle"]
        intent = (state["intents"] or [b.get("intent")])[0]
        main_f = canonical_slots(raw, grounded)
        sub_texts, sub_f, sub_intents = [], [], []
        from_rewrite = reason.startswith("재작성")
        for i, x in enumerate(subs):
            g, _ = ground_slots(x["slots"], lex)
            sub_f.append(canonical_slots(x["slots"], g))
            sub_texts.append((b.get("sub_questions") or [])[i] if from_rewrite and i < len(b.get("sub_questions") or [])
                             else x["text"])
            sub_intents.append(x["intent"])
        rb = {"original": question, "rewritten": b.get("rewritten") or question, "intent": intent, "filters": main_f,
              "sub_questions": sub_texts, "sub_filters": sub_f or None}
        vb, vnotes = to_view_bundle(rb, query_id, "rewritten", sub_intents or None)
        names = [c["name"] for c in concepts(grounded)]
        # 재작성 문장이 슬롯을 담지 못했으면(되묻기로 채운 값, 재작성 실패로 원문 그대로) 슬롯 값으로 검색 문장
        from backend.rag.query_analyzer.values import slot_text
        weak = bool(selections) or (rb["rewritten"] or "").strip() == question.strip()
        # 의도 값('값 조회'·'추이')은 검색어가 아님 → 슬롯 문장에서 뺌 ('1인가구 값 조회' 가 되던 문제)
        no_intent = {k: v for k, v in (vb.get("filters") or {}).items() if k != "의도"}
        text = rule_text(slot_text(no_intent) if weak else rb["rewritten"], vb.get("filters"), names)
        if not text.strip() or (clar and weak):  # 슬롯이 거의 없으면 원문에서 지역·시점만 뺀 문장
            text = rule_text(question, vb.get("filters"), names) or question
        if s.search_text_mode == "llm":
            try:
                terms = names + [r["name"] for k in ("지표", "대상") for sv in grounded.get(k, []) for r in sv["csv"]]
                text, llm_subs = llm_text(question, sub_texts, terms, chat_fn)
                if len(llm_subs) == len(vb.get("sub_questions") or []):
                    vb["sub_questions"] = llm_subs
            except Exception as e:  # noqa: BLE001
                notes.append(f"검색 문장 LLM 실패 → 규칙 문장 사용: {e.__class__.__name__}: {str(e)[:120]}")
        # 원문에 있는데 슬롯에 담기지 않은 CSV 표현 → 검색 문장 끝에 더하고, View 보조 단어(원문표현)로 넘김
        if getattr(s, "question_terms", True) and vb.get("filters") is not None:
            covered = [str(v) for k in ("대상", "지표", "조건", "국적", "성별", "지역", "전출지", "전입지", "연령", "시점")
                       for v in (raw.get(k) or [])]
            qterms = lex.question_terms(question, covered, s.question_terms_max_share, s.question_terms_max)
            if qterms:
                text = " ".join([text, *[t for t in qterms if norm(t) not in norm(text)]]).strip()
                vb["filters"]["원문표현"] = qterms
                for sf, st_ in zip(vb.get("sub_filters") or [], vb.get("sub_questions") or []):
                    own = [t for t in qterms if norm(t) in norm(st_)]  # 하위 질의는 그 문장에 있는 표현만
                    if sf is not None and own:
                        sf["원문표현"] = own
                notes.append(f"원문 표현 보충 (슬롯에 없던 CSV 표현): {qterms}")
        vb["search_text"] = text
        if getattr(s, "role_units", False):  # 분모·조건 단위
            from backend.rag.query_analyzer.roles import add_role_units
            n0 = len(vb.get("sub_questions") or [])
            added = add_role_units(question, vb, lex, max(s.max_sub_queries, 2) + 1)
            if added:
                n_new = len(vb["sub_questions"])
                if n0 == 0:  # 본 질의를 첫 단위로 옮겼으면 그 단위도 기록
                    subs = [{"id": "S1", "text": vb["sub_questions"][0], "slots": raw, "intent": intent,
                             "reason": "본 질의 (역할 단위와 함께 검색)", "candidate_tables": []}]
                subs = list(subs) + [{"id": f"S{i}", "text": vb["sub_questions"][i - 1],
                                      "slots": {**{k: v for k, v in raw.items() if k not in ("대상", "지표")},
                                                "지표": [vb["sub_questions"][i - 1]]},
                                      "intent": intent, "reason": f"{r} (원문 규칙)", "candidate_tables": []}
                                     for i, (r, _) in zip(range(n_new - len(added) + 1, n_new + 1), added)]
                notes.append(f"역할 단위 추가: {added}")
        text = tidy_text(text)  # 임계값 잔여물('0명')·반복 단어 빼기
        if vb.get("sub_questions"):
            vb["sub_questions"] = [tidy_text(t) or t for t in vb["sub_questions"]]
        vb["search_text"] = text
        st.output = {"search_text": text, "sub_questions": vb.get("sub_questions"), "filters": vb.get("filters")}
        notes += vnotes

    out = {**base, "status": "ok", "sub_queries": subs, "decompose_reason": reason, "search_text": text,
           "view_bundle": vb, "state": state, "trace": tr.as_list()}
    tr.save(out)
    return out
