"""(선택) LLM 재정렬 — 합친 순위의 상위 top_n 표를 '표 구조 요약'으로 다시 줄 세운다

왜 필요한가   정답이 10위 안에는 있는데 1위가 아닌 경우가 많다 (retrieval_golden 89문항: Hit@10 0.82 · Hit@1 0.49).
              형제 표(시도판/시군구판, 연도판, 세부 교차표) 사이의 선택은 점수 합보다 '이 표의 행·열로 답이 되는가' 를 읽는 쪽이 낫다.
무엇을 주는가 표마다 한 줄: 제목 · 조사 · 항목(열) · 분류(행) · 지역 수준 · 수록 연도 · 가능성 계수가 깎인 이유
              (LLM 설명문을 미리 만들어 두지 않는다 — 구조에서 그때 조립하므로 표가 바뀌어도 다시 만들 것이 없음)
안전장치     번호만 받는다(JSON). 빠진 번호·모르는 번호·오류는 원래 순서를 유지. top_n 밖은 건드리지 않음. 같은 질문·후보는 캐시
비용         질의 단위마다 HCX 1회 (입력 약 1.5~3천 자)
형제 표        siblings.py 의 무리는 카드에 '형제 A: 성별 … · 수준 …' 로 표시하고, 상위 5개 무리의 빠진 형제를
              상위 top_n 뒤에 붙여(engine._with_siblings) 나란히 비교하게 한다. LLM 뒤에 형제 규칙을 한 번 더 적용
하위 단위     그 단위가 찾는 것을 [찾는 것]으로, 원래 질문은 맥락으로 준다 (원래 질문 기준으로 줄 세우면 분모·조건 표가 밀림).
              분모 단위는 규칙(engine._denominator)이 고른 순서를 그대로 둔다 (llm_rerank.skip_roles)
OKF (llm_rerank.okf)   카드에 표의 정의(KOSIS 주석: 개념·집계 대상·산식)와 질문에 걸린 승인된 개념(별칭·같은 뜻 아님)을 덧붙임
              (search/okf_terms.rerank_notes). 표 이름만으로는 못 가르는 형제 — '당해연도 혼인 비율'(초혼 경험자/인구) ↔
              '누적 혼인 비율'(혼인 경험자/인구), '장기국제이동'(1년 초과) ↔ '국제이동'(90일 초과) — 을 정의로 가르게
불확실 (llm_rerank.keep_if_unsure)   LLM 이 맨 앞 표를 정할 근거가 없다고 하면(sure=false) 원래 순서를 그대로 둠
              (11/18 실험: 근거 없이 같은 값의 표들 사이에서 순서만 바꿔 완화 hit@1 이 떨어짐)
              엔진은 이때 형제 규칙을 다시 돌리지 않음 → 결과가 LLM 없는 검색과 같음 (11/24: 다시 돌려 오히려 밀리던 버그)
구분 줄 (llm_rerank.traits)   후보끼리 다른 성질만 '구분:' 줄로 (총괄표·비율 직접·성별·연령·주기) + 형제 차이 + 집계 기준
              (search/traits.py — 표 메타데이터·OKF 정의에서, 골든셋을 보지 않음)
추론 (llm_rerank.thinking: low|medium|high)   HCX-007 추론을 켬. 구조화 출력과 함께 못 써서 형식을 프롬프트로 주고 글에서
              JSON 을 뽑음. 느림(질의 단위마다 수십 초) · 추론 토큰 비용. 실패·빈 답이면 추론 없이 한 번 더 (메모 '추론 실패 → 일반').
              추론 글은 파일 캐시(llm_rerank_cache.jsonl)의 why 에 남김 — 왜 그 순서인지 사람이 볼 수 있게
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

SYS = ("너는 국가통계(KOSIS) 표를 고르는 사서다. [질문]에 답하는 데 쓸 표를 [후보] 중에서 적합한 순서로 고른다.\n"
       "판단 기준 (위에서부터 중요):\n"
       "1) 질문이 묻는 것(항목)이 그 표의 항목·분류에 실제로 있는가\n"
       "2) 질문의 지역 수준(전국·시도·시군구·읍면동)과 조건(성별·연령·기타 분류)을 그 표가 나눌 수 있는가\n"
       "3) 질문의 연도를 담는가. 일부만 담아도 후보로 두되 전부 담는 표를 앞에\n"
       "4) 조건을 모두 맞춘 표가 여럿이면 분류가 적은 단순한 표를 앞에, 연도를 묻지 않았으면 최신 자료가 있는 표를 앞에\n"
       "5) '형제' 표시가 같은 표들은 같은 통계의 (계)/(남)/(여) 분할·지역 수준판·연도판이다. 질문에 성별이 없으면 (계),"
       " 남성·여성을 물으면 그 성별 표, 질문의 지역 수준(전국·시도·시군구)에 맞는 판, 질문 연도를 담는 판을 앞에\n"
       "6) '같은 값 묶음' 표시가 같은 표들은 합계 값이 같은 다른 표다. 질문의 조건(분류)을 그대로 나눌 수 있는 표를 앞에\n"
       "7) [찾는 것]이 따로 있으면 원래 질문 전체가 아니라 그 부분(예: 비율의 분자·조건을 거는 값)을 담은 표를 고른다\n"
       "후보 번호만 적합한 순서대로 모두 나열한다. 설명은 쓰지 않는다. JSON 만.")
SYS_OKF = ("\n추가 기준 (카드에 '정의'·'개념' 이 있을 때):\n"
           "8) '정의' 는 KOSIS 주석(개념·집계 대상·산식), '개념' 은 검수된 개념 사전이다. 표 이름이 비슷하면 질문의 말이 정의·산식과"
           " 맞는 표를 앞에 (예: '그해 결혼한 비율' ↔ 당해연도 초혼 경험자/인구, '지금까지 결혼한 비율' ↔ 누적 혼인 경험자/인구)\n"
           "9) '주의: 질문의 X 는 이 개념과 같은 뜻이 아님' 이 붙은 표는 뒤로. '질문의 X = 이 개념' 이 붙은 표는 앞으로")
SYS_SURE = ("\n질문만으로 맨 앞 표를 정할 근거가 없으면(둘 이상이 똑같이 맞거나, 질문이 어느 쪽인지 말하지 않음) sure 를 false 로."
            " 근거가 있으면 true. JSON: {\"order\": [번호…], \"sure\": true|false}")
SYS_TRAITS = ("\n추가 기준 (카드에 '구분'·'형제 차이'·'집계 기준' 이 있을 때 — 후보끼리 다른 점만 적혀 있다):\n"
              "10) 질문이 성별·연령·세부 지역을 물으면 그것을 나눌 수 있는 표를 앞에. 총괄표는 여러 통계를 한 표에 담아 세부 분류가 적다\n"
              "11) '집계 기준' 이 다르면(예: 주민등록 등록 외국인 · 귀화자·자녀를 포함한 외국인주민 · 인구총조사) 질문의 말과 맞는 기준의 표를 앞에\n"
              "12) '형제 차이' 는 같은 통계의 판들 사이에서 그 표에만 있는 말이다. 질문에 그 말(성별·연도·지역 수준)이 없으면 가장 일반적인 판을 앞에")
SYS_JSON = "\n충분히 따져 본 뒤, 답은 JSON 한 개만 쓴다 (설명·코드 울타리 없이): "
UNSURE = "불확실 → 원래 순서"
SCHEMA = {"type": "object", "properties": {"order": {"type": "array", "items": {"type": "integer"}}}, "required": ["order"]}
SCHEMA_SURE = {"type": "object", "properties": {"order": {"type": "array", "items": {"type": "integer"}},
                                                "sure": {"type": "boolean"}}, "required": ["order", "sure"]}
_cache, _lock = {}, threading.Lock()
_file = None  # 파일 캐시 (compare 가 실행 폴더에 둠 — 같은 질문·후보·카드면 HCX 를 다시 부르지 않음)


def use_cache_file(path):
    """재정렬 결과를 파일에도 남기고, 있던 결과를 읽어 둠 (jsonl: {key, order, sure})"""
    global _file
    _file = Path(path) if path else None
    if _file is not None and _file.exists():
        with _lock:
            for line in _file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        x = json.loads(line)
                        _cache[x["key"]] = (x["order"], x.get("sure", True))
                    except (ValueError, KeyError):
                        continue


def card(n, h, f, sib_of=None, con_of=None, okf_lines=None):
    """표 하나 → 한 줄 구조 요약. sib_of: {tbl_id: 형제 무리 번호} (같은 번호 = 형제), con_of: 같은 값 묶음 번호
    okf_lines: 이 표의 OKF 정보 줄 ['정의: …', "개념 '…' …"] — 카드 아래 줄로 붙음"""
    dims = []
    for obj, _, names in f.dims[:6]:
        dims.append(f"{obj}({', '.join(str(x) for x in names[:8])}{' …' if len(names) > 8 else ''})")
    geo = "·".join(g for g in ("시도", "시군구", "읍면동", "동읍면부") if g in f.geo) or "전국만"
    if f.years:
        ys = sorted(f.years)
        years = f"{ys[0]}~{ys[-1]}" + (f" ({', '.join(map(str, ys))})" if len(ys) <= 12 else "")
    else:
        years = ", ".join(f"{a}~{b}" for a, b in f.spans) or "?"
    notes = "; ".join(h.get("feas_notes") or [])
    sib = ""
    if sib_of and h["tbl_id"] in sib_of:  # 형제 사이의 차이를 한눈에
        from backend.rag.search.siblings import table_level, table_sex
        sib = f" | 형제 {sib_of[h['tbl_id']]}: 성별 {table_sex(f.tbl_nm) or '분할 없음'} · 수준 {table_level(f)}"
    if con_of and h["tbl_id"] in con_of:  # 개념 카탈로그
        sib += f" | 같은 값 묶음 {con_of[h['tbl_id']]}"
    return (f"[{n}] {f.tbl_nm} | 조사: {f.survey_nm} | 항목: {', '.join(f.items[:12])}{' …' if len(f.items) > 12 else ''}"
            f" | 분류: {' / '.join(dims) or '없음'} | 지역: {geo} | 연도: {years} | 주기: {''.join(sorted(f.cycles))}"
            + sib + (f" | 주의: {notes}" if notes else "")
            + "".join(f"\n    {x}" for x in (okf_lines or [])))


def sibling_numbers(head, sib):
    """후보 중 형제끼리 같은 번호 (형제가 둘 이상 후보에 있을 때만) → {tbl_id: 'A'…}"""
    if sib is None:
        return {}
    by = {}
    for h in head:
        g = sib.of.get(h["tbl_id"])
        if g:
            by.setdefault(g, []).append(h["tbl_id"])
    out = {}
    for k, (_, ts) in enumerate(sorted(((g, ts) for g, ts in by.items() if len(ts) >= 2), key=lambda x: x[1][0])):
        for t in ts:
            out[t] = chr(ord("A") + k % 26)
    return out


def concept_numbers(head, concept_of):
    """후보 중 같은 개념이 둘 이상이면 같은 번호 → {tbl_id: 'C1'…}"""
    by = {}
    for h in head:
        k = (concept_of or {}).get(h["tbl_id"])
        if k is not None:
            by.setdefault(k, []).append(h["tbl_id"])
    return {t: f"C{n}" for n, ts in enumerate((ts for ts in by.values() if len(ts) >= 2), 1) for t in ts}


def _ask(chat_fn, sys_prompt, user, schema, thinking, think_tokens):
    """→ (dict, 메모 덧붙임, 추론 글). 추론이면 형식을 프롬프트로 주고, 실패·빈 답이면 추론 없이 한 번 더"""
    if thinking:
        fmt = json.dumps({"order": [3, 1, 2], **({"sure": True} if "sure" in schema["properties"] else {})})
        try:
            out = chat_fn([{"role": "system", "content": sys_prompt + SYS_JSON + fmt}, {"role": "user", "content": user}],
                          schema=schema, max_tokens=think_tokens or 0, thinking=thinking, with_thinking=True)
            if isinstance(out, dict) and out.get("order"):
                return out, f"+think:{thinking}", str(out.get("_thinking") or "")
            why = f"빈 답({(out or {}).get('_finish') or '-'})" if isinstance(out, dict) else "형식 오류"
        except Exception as e:  # noqa: BLE001  (시간 초과 등 — 추론 없이 다시)
            why = e.__class__.__name__
        out = chat_fn([{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}], schema=schema,
                      max_tokens=200)
        return out, f" 추론 실패({why}) → 일반", ""
    out = chat_fn([{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}], schema=schema,
                  max_tokens=200)
    return out, "", ""


def rerank(question, qv, hits, facets, top_n=12, chat_fn=None, sib=None, concept_of=None, context=None, role=None,
           okf_notes=None, keep_if_unsure=False, traits=False, traits_own_defs=True, thinking=None, think_tokens=None):
    """→ (다시 줄 세운 hits, 메모). 실패하면 hits 그대로. sib: SiblingResolver (있으면 카드에 형제 표시)
    context: 하위 검색 단위일 때 원래 질문 (question 은 그 단위가 찾는 것), role: 분모·조건
    okf_notes: {tbl_id: [줄]} (okf_terms.rerank_notes) — 있으면 카드에 붙이고 기준 8·9 를 더함
    keep_if_unsure: LLM 이 sure=false 면 원래 순서 (메모 끝이 UNSURE — 엔진은 이때 형제 규칙을 다시 돌리지 않음)
    traits: 구분 줄 (traits.py) · traits_own_defs=False 면 표 자신의 정의는 빼고 조사 공통만 (okf_notes 의 '정의:' 와 겹치지 않게)
    thinking: 'low'|'medium'|'high' — HCX-007 추론 (chat_fn 에 thinking·with_thinking 인자를 넘김)"""
    head, tail = hits[:top_n], hits[top_n:]
    if len(head) < 2:
        return hits, None
    okf_notes = {k: v for k, v in (okf_notes or {}).items() if v}
    sib_of, con_of = sibling_numbers(head, sib), concept_numbers(head, concept_of)
    if traits:
        from backend.rag.search.traits import traits_lines
        tl = traits_lines(head, facets, sib_of, own_defs=traits_own_defs)
        for k, v in tl.items():
            okf_notes[k] = list(okf_notes.get(k, [])) + v
    thinking = thinking if thinking and str(thinking).lower() != "none" else None
    key = json.dumps([question, context, role, [h["tbl_id"] for h in head],
                      sorted([k, v] for k, v in okf_notes.items() if k in {h["tbl_id"] for h in head}), bool(keep_if_unsure)]
                     + ([thinking] if thinking else []), ensure_ascii=False)
    with _lock:
        got = _cache.get(key)
    order, sure = got if got else (None, True)
    note = "cache"
    if order is None:
        cond = (f"연도 {qv.years or '지정 없음(최신)'} · 시도 {qv.sido or '-'} · 시군구 {qv.subs or '-'} · "
                f"지역 수준 {qv.axis or '-'} · 연령 {'물음' if qv.want_age else '-'} · 성별 {'물음' if qv.want_sex else '-'}")
        ask = (f"[찾는 것] {question}{f' (역할: {role})' if role else ''}\n[원래 질문] {context}" if context
               else f"[질문] {question}")
        user = (f"{ask}\n[읽어 낸 조건] {cond}\n[후보]\n"
                + "\n".join(card(n, h, facets[h["tbl_id"]], sib_of, con_of, okf_notes.get(h["tbl_id"]))
                            for n, h in enumerate(head, 1)))
        has_okf = any(x.startswith(("정의", "개념")) for v in okf_notes.values() for x in v)
        sys_prompt = SYS + (SYS_OKF if has_okf else "") + (SYS_TRAITS if traits else "") + (SYS_SURE if keep_if_unsure else "")
        why = ""
        try:
            if chat_fn is None:
                from backend.core.llm import chat as chat_fn
            out, extra, why = _ask(chat_fn, sys_prompt, user, SCHEMA_SURE if keep_if_unsure else SCHEMA, thinking,
                                   think_tokens)
            out = out if isinstance(out, dict) else {}
            order = [int(x) for x in out.get("order") or [] if str(x).lstrip("-").isdigit()]
            sure = out.get("sure") is not False  # 빠지면 확실한 것으로 (기존 동작)
            note = "llm" + ("+okf" if has_okf else "") + ("+traits" if traits else "") + extra
        except Exception as e:  # noqa: BLE001  (재정렬은 보조 단계 — 실패해도 검색 결과는 그대로)
            return hits, f"실패: {e.__class__.__name__}: {str(e)[:100]}"
        order = list(dict.fromkeys(n for n in order if 1 <= n <= len(head)))
        if not order:
            return hits, "빈 응답 → 원래 순서"
        with _lock:
            if len(_cache) > 5000:
                _cache.clear()
            _cache[key] = (order, sure)
            if _file is not None:
                with _file.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"key": key, "order": order, "sure": sure, "note": note,
                                         **({"why": why[:3000]} if why else {})}, ensure_ascii=False) + "\n")
    if keep_if_unsure and not sure:
        return hits, f"{note} {UNSURE}"
    order = order + [n for n in range(1, len(head) + 1) if n not in order]  # 빠진 번호는 원래 순서로 뒤에
    out = []
    for r, n in enumerate(order, 1):
        h = dict(head[n - 1])
        h["stages"] = {**h.get("stages", {}), "llm": {"rank": r, "score": None}, "fused": {"rank": h["rank"], "score": h["score"]}}
        h["rank"] = r
        out.append(h)
    return out + tail, note
