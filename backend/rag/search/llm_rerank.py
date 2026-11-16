"""(선택) LLM 재정렬 — 합친 순위의 상위 top_n 표를 '표 구조 요약'으로 다시 줄 세운다

왜 필요한가   retrieval_golden 89문항에서 v5[hcx] 는 Hit@10 0.82 인데 Hit@1 0.49 — 정답이 10위 안에는 있는데 1위가 아닌 경우가 많다.
              형제 표(시도판/시군구판, 연도판, 세부 교차표) 사이의 선택은 점수 합보다 '이 표의 행·열로 답이 되는가' 를 읽는 쪽이 낫다.
무엇을 주는가 표마다 한 줄: 제목 · 조사 · 항목(열) · 분류(행) · 지역 수준 · 수록 연도 · 가능성 계수가 깎인 이유
              (LLM 설명문을 미리 만들어 두지 않는다 — 구조에서 그때 조립하므로 표가 바뀌어도 다시 만들 것이 없음)
안전장치     번호만 받는다(JSON). 빠진 번호·모르는 번호·오류는 원래 순서를 유지. top_n 밖은 건드리지 않음. 같은 질문·후보는 캐시
비용         질의 단위마다 HCX 1회 (입력 약 1.5~3천 자)
[NEW 11-16] (P3) 형제 표(siblings.py 의 무리)는 카드에 '형제 A: 성별 … · 수준 …' 로 표시하고, 상위 5개 무리의 빠진 형제를
             후보에 끼워 넣어(router._with_siblings) 나란히 비교하게 한다. LLM 뒤에 형제 규칙을 한 번 더 적용 (무리 안의 선택)
"""
from __future__ import annotations

import threading

SYS = ("너는 국가통계(KOSIS) 표를 고르는 사서다. [질문]에 답하는 데 쓸 표를 [후보] 중에서 적합한 순서로 고른다.\n"
       "판단 기준 (위에서부터 중요):\n"
       "1) 질문이 묻는 것(항목)이 그 표의 항목·분류에 실제로 있는가\n"
       "2) 질문의 지역 수준(전국·시도·시군구·읍면동)과 조건(성별·연령·기타 분류)을 그 표가 나눌 수 있는가\n"
       "3) 질문의 연도를 담는가. 일부만 담아도 후보로 두되 전부 담는 표를 앞에\n"
       "4) 조건을 모두 맞춘 표가 여럿이면 분류가 적은 단순한 표를 앞에, 연도를 묻지 않았으면 최신 자료가 있는 표를 앞에\n"
       "5) '형제' 표시가 같은 표들은 같은 통계의 (계)/(남)/(여) 분할·지역 수준판·연도판이다. 질문에 성별이 없으면 (계),"
       " 남성·여성을 물으면 그 성별 표, 질문의 지역 수준(전국·시도·시군구)에 맞는 판, 질문 연도를 담는 판을 앞에\n"
       "6) '같은 값 묶음' 표시가 같은 표들은 합계 값이 같은 다른 표다. 질문의 조건(분류)을 그대로 나눌 수 있는 표를 앞에\n"
       "후보 번호만 적합한 순서대로 모두 나열한다. 설명은 쓰지 않는다. JSON 만.")
SCHEMA = {"type": "object", "properties": {"order": {"type": "array", "items": {"type": "integer"}}}, "required": ["order"]}
_cache, _lock = {}, threading.Lock()


def card(n, h, f, sib_of=None, con_of=None):
    """표 하나 → 한 줄 구조 요약. sib_of: {tbl_id: 형제 무리 번호} (같은 번호 = 형제), con_of: 같은 값 묶음 번호"""
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
    if sib_of and h["tbl_id"] in sib_of:                 # [NEW 11-16] (P3) 형제 사이의 차이를 한눈에
        from backend.rag.search.siblings import table_level, table_sex
        sib = f" | 형제 {sib_of[h['tbl_id']]}: 성별 {table_sex(f.tbl_nm) or '분할 없음'} · 수준 {table_level(f)}"
    if con_of and h["tbl_id"] in con_of:                 # [NEW 11-16] (P5) 개념 카탈로그
        sib += f" | 같은 값 묶음 {con_of[h['tbl_id']]}"
    return (f"[{n}] {f.tbl_nm} | 조사: {f.survey_nm} | 항목: {', '.join(f.items[:12])}{' …' if len(f.items) > 12 else ''}"
            f" | 분류: {' / '.join(dims) or '없음'} | 지역: {geo} | 연도: {years} | 주기: {''.join(sorted(f.cycles))}"
            + sib + (f" | 주의: {notes}" if notes else ""))


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


def rerank(question, qv, hits, facets, top_n=12, chat_fn=None, sib=None, concept_of=None):
    """→ (다시 줄 세운 hits, 메모). 실패하면 hits 그대로. sib: SiblingResolver (있으면 카드에 형제 표시)"""
    head, tail = hits[:top_n], hits[top_n:]
    if len(head) < 2:
        return hits, None
    key = (question, tuple(h["tbl_id"] for h in head))
    with _lock:
        order = _cache.get(key)
    note = "cache"
    if order is None:
        cond = (f"연도 {qv.years or '지정 없음(최신)'} · 시도 {qv.sido or '-'} · 시군구 {qv.subs or '-'} · "
                f"지역 수준 {qv.axis or '-'} · 연령 {'물음' if qv.want_age else '-'} · 성별 {'물음' if qv.want_sex else '-'}")
        sib_of, con_of = sibling_numbers(head, sib), concept_numbers(head, concept_of)
        user = (f"[질문] {question}\n[읽어 낸 조건] {cond}\n[후보]\n"
                + "\n".join(card(n, h, facets[h["tbl_id"]], sib_of, con_of) for n, h in enumerate(head, 1)))
        try:
            if chat_fn is None:
                from backend.core.llm import chat as chat_fn
            out = chat_fn([{"role": "system", "content": SYS}, {"role": "user", "content": user}], schema=SCHEMA,
                          max_tokens=200)
            order = [int(x) for x in (out or {}).get("order") or [] if str(x).lstrip("-").isdigit()]
            note = "llm"
        except Exception as e:  # noqa: BLE001  (재정렬은 보조 단계 — 실패해도 검색 결과는 그대로)
            return hits, f"실패: {e.__class__.__name__}: {str(e)[:100]}"
        order = list(dict.fromkeys(n for n in order if 1 <= n <= len(head)))
        if not order:
            return hits, "빈 응답 → 원래 순서"
        with _lock:
            if len(_cache) > 5000:
                _cache.clear()
            _cache[key] = order
    order = order + [n for n in range(1, len(head) + 1) if n not in order]     # 빠진 번호는 원래 순서로 뒤에
    out = []
    for r, n in enumerate(order, 1):
        h = dict(head[n - 1])
        h["stages"] = {**h.get("stages", {}), "llm": {"rank": r, "score": None}, "fused": {"rank": h["rank"], "score": h["score"]}}
        h["rank"] = r
        out.append(h)
    return out + tail, note
