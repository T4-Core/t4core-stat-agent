"""
팀 평가 기준 C1~C5 채점 (EVAL_CRITERIA.md). LLM 호출 없음 — e2e_eval.py 가 answer() 결과와 재현한 문맥을 넘긴다.

C1 검색 적합성      최종 검색 상위 k 에서 '맞는 뷰'(정답 칸·지표를 모두 담은 뷰)의 순위. 표만 맞으면 0.5
C2 원본 수치 추출   맞는 뷰의 facts 가 raw 와 같은가 (build_gold 의 정적 판정, LLM 과 무관)
C3 Context 충분성   문맥에 필요한 원시 수치(칸)와 질문 지표에 맞는 facts 가 있는가 — raw / facts 따로
C4 변화율 응답 완성도 metrics 마다 답변에 맞게 나왔는가 (반올림·만 단위 허용, %p 규칙, 순위는 이름)
C5 자동 환각 검증    답변 숫자를 맞음/틀림/확인 불가로 나누고 verify_numbers 표시와 대조 → TP·FN·FP·TN

점수: 1 통과 · 0.5 부분 · 0 실패 · None 해당 없음
"""
import math
import re

NEG_WORDS = re.compile(r"순유출|유출|감소|줄|빠져|마이너스|하락")
NUM_TOKEN = re.compile(r"([-−]\s*)?(\d[\d,]*(?:\.\d+)?)\s*(조|천억|억|천만|백만|만|천|백)?(%\s*p|%\s*포인트|퍼센트\s*포인트|%P|%|퍼센트)?")
MULT = {"조": 10 ** 12, "천억": 10 ** 11, "억": 10 ** 8, "천만": 10 ** 7, "백만": 10 ** 6, "만": 10 ** 4, "천": 10 ** 3, "백": 10 ** 2, None: 1}
# 계산식 상수: '×100', '÷ 1,000', '100을 곱' 처럼 연산 기호·곱하기 말 바로 옆의 100·1000 은 답변 속 '주장하는 값'이 아니다
OP_BEFORE = re.compile(r"(?:[×xX*÷/]|곱하기|곱한|곱해|나누기|나눈)\s*$")
OP_AFTER = re.compile(r"^\s*(?:을|를)?\s*(?:곱|나누|나눠)")
METRIC_VALUE_KEYS = ("start", "end", "diff", "pct", "diff_pp", "a", "b", "top1", "bottom1", "peak_value")


def extract_tokens(text):
    """문장 속 숫자 → 토큰 dict 목록 (v 값, tol 허용오차, unit '%'·'%p'·'', 위치).
    허용오차는 표기 자릿수의 반(반올림 허용).
    '988만 1,726' 처럼 큰 단위 뒤에 작은 수가 이어지면 합친 값(merged)도 토큰으로 넣는다.
    합쳐진 조각은 part, 가장 길게 합친 값은 final 로 표시한다."""
    text = str(text)
    toks = []
    for m in NUM_TOKEN.finditer(text):
        s = m.group(2).replace(",", "")
        try:
            v = float(s)
        except ValueError:
            continue
        mult = MULT[m.group(3)]
        dec = len(s.split(".")[1]) if "." in s else 0
        unit = re.sub(r"\s", "", m.group(4) or "")
        unit = "" if not unit else "%p" if unit.lower().endswith("p") or "포인트" in unit else "%"
        const = (mult == 1 and v in (100, 1000)
                 and bool(OP_BEFORE.search(text[:m.start()]) or OP_AFTER.search(text[m.end():m.end() + 8])))
        toks.append({"v": (-1 if m.group(1) else 1) * v * mult, "tol": 0.5 * 10 ** -dec * mult, "mult": mult,
                     "unit": unit, "start": m.start(), "end": m.end(), "const": const,
                     "merged": False, "part": False, "final": False})
    merged, consumed = [], set()
    for i, a in enumerate(toks):
        if a["mult"] == 1:
            continue
        acc, cur, chain, n0 = a["v"], a["mult"], [i], len(merged)
        for j in range(i + 1, len(toks)):          # 1억 2,000만 5,000 처럼 단위가 이어지는 만큼 누적
            c = toks[j]
            if c["mult"] >= cur or text[toks[j - 1]["end"]:c["start"]].strip():
                break
            acc += math.copysign(c["v"], acc or 1)
            chain.append(j)
            merged.append({"v": acc, "tol": c["tol"], "mult": c["mult"], "unit": c["unit"], "start": a["start"],
                           "end": c["end"], "merged": True, "part": False, "final": False})
            if c["mult"] == 1:
                break
            cur = c["mult"]
        if len(merged) > n0 and i not in consumed:  # 이미 앞 묶음에 든 토큰에서 시작한 묶음은 final 이 아니다
            merged[-1]["final"] = True
            consumed.update(chain)
    for i in consumed:
        toks[i]["part"] = True
    return toks + merged


def extract_numbers(text, merge=False):
    """문장 속 숫자 → [(값, 허용오차)]. 기본은 조각과 합친 값을 모두 후보로 돌려준다(정답 찾기용).
    merge=True 는 합쳐진 조각과 계산식 상수(×100)를 빼고 최종 합친 값만 남긴다 (숫자를 하나씩 세는 C5용)."""
    toks = extract_tokens(text)
    if merge:
        toks = [t for t in toks if not t["merged"] and not t["part"] and not t["const"]] + [t for t in toks if t["final"]]
    return [(t["v"], t["tol"]) for t in toks]


def matches(nums, gold, extra_tol=0.0):
    """정답과 같은 숫자 (크기 기준, 부호는 따로 본다)"""
    return [v for v, tol in nums if abs(abs(v) - abs(gold)) <= max(tol, extra_tol) + 1e-9]


def answer_text(res):
    return " ".join([res.get("answer") or "", res.get("summary") or ""] + list(res.get("key_points") or []))


def tol_of(g, key):
    t = g.get("tolerance")
    if isinstance(t, dict):
        return t.get("pct", 0.1) if key == "pct" else t.get("value", 0)
    return t or 0


def name_variants(name):
    import kosis_rag_qa as qa
    s = str(name).strip()
    return {s, qa.short_name(s)} - {""}


# 순위 역할어. 순유출처럼 방향이 뒤집히는 표현(가장 많이 빠져나간 = 최하위)을 앞에 둬서 먼저 잡는다.
ROLE = re.compile(r"(?P<bot>가장\s*많이\s*(?:빠져|유출|감소|줄)|순유출\s*(?:이\s*|은\s*)?(?:가장\s*)?(?:많|큰|1위)"
                  r"|최하위|꼴찌|최소|최저|(?:가장|제일)\s*(?:적|낮|작))"
                  r"|(?P<top>1위|최대|최고|(?:가장|제일)\s*(?:많|높|크|큰))")
SENT_SPLIT = re.compile(r"[;\n]|(?<!\d)\.|\.(?!\d)")     # 숫자 사이의 . , 는 나누지 않는다 (71.3, 76,309)
COMMA_SPLIT = re.compile(r"(?<!\d),|,(?!\d)")


def clauses(text):
    """문장은 마침표로, 절은 쉼표로 나눈다. '각각' 이 든 문장은 쉼표로 나누지 않는다 (역할어와 이름이 쉼표 너머에 있음)."""
    out, s = [], 0
    for m in list(SENT_SPLIT.finditer(text)) + [None]:
        e = m.start() if m else len(text)
        if "각각" in text[s:e]:
            out.append((s, e))
        else:
            p = s
            for c in COMMA_SPLIT.finditer(text[s:e]):
                out.append((p, s + c.start()))
                p = s + c.end()
            out.append((p, e))
        if m:
            s = m.end()
    return out


def rank_roles(text, names):
    """names {지표: 이름 표기들} → {지표: [그 이름이 나온 곳마다의 역할 'top'|'bot'|None]}.
    같은 절 안에서 이름에 가장 가까운 역할어를 그 이름의 역할로 본다 (동률이면 앞에 온 쪽)."""
    spans = []
    for k, vs in names.items():
        taken = []
        for n in sorted(vs, key=len, reverse=True):          # '서울특별시' 를 먼저 잡아 '서울' 이 겹쳐 세지지 않게
            for m in re.finditer(re.escape(n), text):
                if not any(m.start() < e and s < m.end() for s, e in taken):
                    taken.append((m.start(), m.end()))
                    spans.append((m.start(), m.end(), k))
    roles = {k: [] for k in names}
    for a, b in clauses(text):
        rs = [(m.start() + a, m.end() + a, "bot" if m.group("bot") else "top") for m in ROLE.finditer(text[a:b])]
        ss = sorted(s for s in spans if a <= s[0] < b)
        if "각각" in text[a:b] and rs and len(rs) == len(ss):  # '1위와 최하위는 각각 A, B' → 순서대로 짝짓기
            for (_, _, k), (_, _, role) in zip(ss, rs):
                roles[k].append(role)
            continue
        for s, e, k in ss:
            near = min(rs, key=lambda r: (r[0] - e if r[0] >= e else s - r[1], r[0] >= e), default=None)
            roles[k].append(near[2] if near else None)
    return roles


# ── 문맥: 필요한 칸 ────────────────────────────────────────────
def cells(g):
    """필요한 칸 = (이름, 값, 허용오차, 그 행이나 블록 머리말에 있어야 할 말들)"""
    e, typ = g["expect"], g.get("type", "lookup")
    dims = list(e.get("dims", {}).values())
    if typ == "lookup":
        toks = dims + [e["prd_de"][:4]] + ([f"{int(e['prd_de'][4:])}/4"] if e["prd_se"] == "Q" else [])
        return [("정답 칸", g["gold_value"], tol_of(g, "value"), toks)]
    gm, tv = g["gold_metrics"], tol_of(g, "value")
    if typ == "change":
        return [(k, gm[k]["value"], tv, dims + [gm[k]["period"][:4]]) for k in ("start", "end")]
    if typ == "rank":
        return [(k, gm[k]["value"], tv, dims + [gm[k]["name"], e["prd_de"][:4]])
                for k in ("top1", "bottom1") if k in g["metrics"]]
    if typ == "peak":
        return [("peak", gm["peak_value"]["value"], tv, dims + [str(gm["peak_period"]["value"])[:4]])]
    return [(k, gm[k]["value"], tv, dims + [gm[k]["name"], e["prd_de"][:4]]) for k in ("a", "b")]


def cell_in(text, value, tol, toks):
    lines = text.splitlines()
    header = " ".join(l for l in lines if " | " not in l)
    return any(" | " in line and matches(extract_numbers(line), value, tol)
               and all(t in line or t in header for t in toks) for line in lines)


def facts_lines(texts):
    return [l for t in texts.values() for l in t.splitlines() if l.startswith("핵심 수치")]


def facts_for_question(g, texts):
    """질문 지표에 맞는 facts 가 문맥에 있나 (None: 이 유형에는 대응하는 facts 가 없음)"""
    typ = g.get("type", "lookup")
    if typ in ("lookup", "compare"):
        return None
    fl, gm = facts_lines(texts), g["gold_metrics"]
    if typ == "rank":
        return any(f"1위 {n}" in l for l in fl for n in name_variants(gm["top1"]["name"]))
    if typ == "peak":
        return any(f"최대 {gm['peak_period']['value']}" in l for l in fl)
    want = [gm[k]["value"] for k in ("pct", "diff") if k in g["metrics"] or k == "diff"]
    return any(matches(extract_numbers(l), w, max(tol_of(g, "pct"), 0.05)) for l in fl for w in want if w is not None)


# ── 기준별 채점 ───────────────────────────────────────────────
def c1(g, retrieved_ids):
    gold = set(g["gold_ids"])
    fit = [v["id"] for v in (g.get("answerable_views") if g.get("type", "lookup") == "lookup" else g.get("fit_views")) or []]
    t_rank = next((i + 1 for i, x in enumerate(retrieved_ids) if x in gold), None)
    f_rank = next((i + 1 for i, x in enumerate(retrieved_ids) if x in set(fit)), None)
    if not fit:
        return {"score": 1.0 if t_rank else 0.0, "table_rank": t_rank, "fit_rank": None,
                "note": "맞는 뷰 없음(조건 적용으로만 답 가능) → 표 기준"}
    return {"score": 1.0 if f_rank else 0.5 if t_rank else 0.0, "table_rank": t_rank, "fit_rank": f_rank, "note": ""}


def c2(g):
    if g.get("type", "lookup") == "lookup":
        hv = [v for v in g.get("answerable_views") or [] if v.get("value") is not None]
        if not hv:
            return {"score": None, "note": "답할 수 있는 뷰 없음"}
        ok = all(math.isclose(v["value"], g["gold_value"], abs_tol=1e-9) for v in hv)
        return {"score": 1.0 if ok else 0.0, "note": "뷰 값 = raw" if ok else "뷰 값 ≠ raw"}
    fc = g.get("facts_check", "")
    if "불일치" in fc or "단위 %" in fc:
        s = 0.0
    elif "기간 다름" in fc:
        s = 0.5
    elif "일치" in fc:
        s = 1.0
    else:
        s = None
    return {"score": s, "note": fc}


def c3(g, texts):
    need = cells(g)
    got = [n for n, v, tol, toks in need if any(cell_in(t, v, tol, toks) for t in texts.values())]
    raw = len(got) / len(need) if need else None
    facts = facts_for_question(g, texts)
    score = None if raw is None else raw if facts is None else (raw + (1.0 if facts else 0.0)) / 2
    return {"score": score, "raw": raw, "facts": facts, "cells_found": got,
            "cells_missing": [n for n, *_ in need if n not in got]}


def c4(g, res):
    if g.get("type", "lookup") == "lookup":
        return {"score": None, "items": {}}
    text, gm = answer_text(res), g["gold_metrics"]
    toks = extract_tokens(text)
    nums = [(t["v"], t["tol"]) for t in toks]
    # 지표별로 숫자 옆에 와야 하는 단위 (허용 단위, 안내문). %와 %p, 개수와 %를 섞어 쓰면 틀린 답이다.
    unit_rule = {"pct": ({"%"}, "%"), "diff": ({""}, "% 없는 증감량")}
    if g.get("unit_rule") == "pp":
        unit_rule["diff_pp"] = ({"%p"}, "%p")
    rank_keys = [k for k in ("top1", "bottom1") if k in g["metrics"]]
    roles = rank_roles(text, {k: name_variants(gm[k]["name"]) for k in rank_keys}) if rank_keys else {}
    items = {}
    for k in g["metrics"]:
        m = gm[k]
        if k in ("top1", "bottom1"):
            want, rs = ("top", "1위") if k == "top1" else ("bot", "최하위"), roles[k]
            if not rs:
                items[k] = f"이름 없음 (기대 {m['name']})"
            elif want[0] in rs or all(r is None for r in rs):     # 역할어가 없으면(표 형식 등) 판단하지 않고 통과
                items[k] = True
            else:
                items[k] = f"순위 역할 불일치 ({m['name']} 은(는) {want[1]} 여야 함)"
            continue
        if k == "peak_period":
            items[k] = str(m["value"]) in text or f"시점 없음 (기대 {m['value']})"
            continue
        v, tol = m["value"], tol_of(g, k)
        hit = matches(nums, v, tol)
        if not hit:
            # 참고 표시일 뿐 점수는 같다: 단위가 분명한 지표(%, %p)에서 같은 단위의 다른 숫자가 있으면 계산 오류, 없으면 누락
            same_unit = [t for t in toks if k in ("pct", "diff_pp") and k in unit_rule and not t["const"]
                         and t["unit"] in unit_rule[k][0]]
            if same_unit:
                shown = ", ".join(dict.fromkeys(f"{t['v']:,.4g}{unit_rule[k][1]}" for t in same_unit))
                items[k] = f"다른 값 (답변 {shown}, 기대 {v:,.4g})"
            else:
                items[k] = f"값 없음 (계산 누락, 기대 {v:,.4g})" if k in ("pct", "diff_pp") else f"값 없음 (기대 {v:,.4g})"
        elif v < 0 and not (any(x < 0 for x in hit) or NEG_WORDS.search(text)):
            items[k] = "부호(감소)를 밝히지 않음"
        elif k in unit_rule and not matches([(t["v"], t["tol"]) for t in toks if t["unit"] in unit_rule[k][0]], v, tol):
            items[k] = f"단위 혼동 (기대 {unit_rule[k][1]})"
        else:
            items[k] = True
    for grp in g.get("must_mention", []):
        items["언급:" + "/".join(grp)] = any(w in text for w in grp) or "필수 언급 없음"
    if res.get("insufficient"):
        items["insufficient"] = "모델이 자료 부족으로 답함"
    ok = [x is True for x in items.values()]
    return {"score": sum(ok) / len(ok) if ok else None, "items": items}


def gold_values(g):
    """정답 숫자 [(값, 허용오차)]. 조회형은 정답 칸 하나, 지표형은 지표별 정답"""
    if g.get("type", "lookup") == "lookup":
        return [(g["gold_value"], tol_of(g, "value"))]
    return [(m["value"], tol_of(g, k)) for k, m in g["gold_metrics"].items()
            if k in METRIC_VALUE_KEYS and isinstance(m.get("value"), (int, float))]


def wrong_flags(g, res):
    """verify_numbers 경고 중 '정답 지표값이 아닌' 것. 정답을 계산해서 낸 값(예: 72.9-58.1=14.8)은 문맥에 그대로
    없어 경고가 뜨지만 틀린 숫자가 아니므로 뺀다 (C5 에서는 오탐 FP). 지표형 관문 3 이 이것만 실패로 본다"""
    golds, keep = gold_values(g), []
    for s in res.get("unverified_numbers") or []:
        ns = extract_numbers(s, merge=True)
        if ns and all(any(matches([n], gv, gt) for gv, gt in golds) for n in ns):
            continue
        keep.append(s)
    return keep


def c5(g, res, texts):
    """맞음: 정답 값·지표와 일치 / 틀림: 정답도 아니고 문맥에도 없음 / 확인 불가: 문맥에는 있으나 묻지 않은 숫자.
    verify_numbers 는 1~2자리 숫자를 검사하지 않으므로, 틀린 숫자 중 그런 것은 'out_of_scope' 로 따로 센다."""
    q_nums = {v for v, _ in extract_numbers(g["question"])}
    golds = gold_values(g)
    ctx =[n for t in texts.values() for n in extract_numbers(t)]
    flagged = [n for s in res.get("unverified_numbers") or [] for n in extract_numbers(s, merge=True)]
    silent = set(res.get("_silent_values") or [])
    out = {"TP": 0, "FN": 0, "FP": 0, "TN": 0, "unknown": 0, "out_of_scope": 0, "wrong": [], "false_alarm": []}
    seen = set()
    for v, tol in extract_numbers(answer_text(res), merge=True):
        if v in q_nums or (v.is_integer() and 1900 <= v <= 2100) or round(v, 6) in seen:
            continue
        seen.add(round(v, 6))
        is_flag = bool(matches(flagged, v, tol))
        if any(matches([(v, tol)], gv, gt) for gv, gt in golds):
            out["FP" if is_flag else "TN"] += 1
            if is_flag:
                out["false_alarm"].append(v)
        elif matches(ctx, v, tol) and v not in silent:
            out["unknown"] += 1
        else:
            out["TP" if is_flag else "FN"] += 1
            out["wrong"].append(v)
            if not is_flag and len(re.sub(r"\D", "", f"{abs(v):g}")) <= 2:   # verify_numbers 와 같은 기준
                out["out_of_scope"] += 1
    return out


def score_all(g, res, texts, retrieved_ids):
    return {"C1": c1(g, retrieved_ids), "C2": c2(g), "C3": c3(g, texts), "C4": c4(g, res), "C5": c5(g, res, texts)}


def mark(s):
    return "-" if s is None else "O" if s >= 1 else "X" if s <= 0 else "△"
