"""④-1 차트 요청 · 데이터 모양 점수 (고도화 3단계) — 규칙, HCX 호출 없음

  requested_chart(texts)                → (차트, 찾은 말) 질문 속 차트 이름. 없으면 (None, None)
  shape_score(chart, profile, measure)  → (점수, 근거) 데이터 모양에 얼마나 잘 맞는지

  - 차트 이름은 원 질문 → 하위질문 → 재작성 순서로 찾는다 (재작성에서 '지도로' 같은 말이 빠질 수 있어서)
  - 점수는 2단계 profile 의 category_axis · series_axis · dims 를 쓴다
"""
import re

from .chart_type_rules import CHART_WORDS, SHAPE_SCORES

TIME = "시점"
CHANGE_MEASURES = ("change", "growth_rate")     # [NEW 11-27] 시점마다 늘고 준 폭 · 비율 → 막대


def _ns(s):
    return re.sub(r"\s+", "", str(s or ""))


def requested_chart(texts):
    """texts(문장 목록, 앞쪽이 우선)에서 차트 이름 찾기 → (차트, 찾은 말)"""
    words = sorted(CHART_WORDS, key=lambda w: -len(_ns(w)))       # 긴 말부터
    for text in texts:
        t = _ns(text)
        if not t:
            continue
        hits = []
        for w in words:
            k = _ns(w)
            pos = t.find(k)
            if pos >= 0:
                hits.append((pos, w))
                t = t.replace(k, "□" * len(k))                      # 찾은 부분은 지워 짧은 말이 다시 걸리지 않게
        if hits:
            pos, w = min(hits)                                       # 문장에서 가장 앞에 나온 차트 이름
            return CHART_WORDS[w], w
    return None, None


def shape_score(chart, profile, measure):
    """차트 하나의 데이터 모양 점수 → (점수, 근거 문장)"""
    cat = profile.get("category_axis") or {}
    ser = profile.get("series_axis") or {}
    dims = profile.get("dims") or []
    n_cat = profile.get("n_categories", 0)
    if chart == "pyramid" and cat.get("axis") == "연령" and ser.get("axis") == "성별" and ser.get("n") == 2:
        return SHAPE_SCORES["pyramid_age_sex"], "범주 = 연령, 계열 = 성별 2개"
    # [CHANGED 11-27] 증감 · 증감률(시점마다 늘고 준 폭)은 0 을 기준으로 위아래 막대가 읽기 쉽다 → 꺾은선 점수를 주지 않는다 (막대 1순위).
    #   '최근 5년 혼인건수 매년 증감률' 이 꺾은선(점수 3)으로 나왔다. 시점이 많아 막대가 20개를 넘으면 모듈 3 이 꺾은선으로 대체한다
    if chart == "line" and cat.get("axis") == TIME and cat.get("n", 0) >= 3 and measure not in CHANGE_MEASURES:
        return SHAPE_SCORES["line_time"], f"범주 = 시점 {cat.get('n')}개"
    if chart == "heatmap":
        non_time = [d for d in dims if d.get("axis") != TIME]
        if len(non_time) >= 2 and all(d.get("n", 0) >= 3 for d in non_time[:2]):
            return SHAPE_SCORES["heatmap_two_axes"], f"나눔 2개 ({non_time[0]['col']} × {non_time[1]['col']})"
    if chart == "donut" and measure == "share" and n_cat <= 5:
        return SHAPE_SCORES["donut_small_share"], f"비중 · 범주 {n_cat}개"
    if chart == "bar":
        if measure == "rank":
            return SHAPE_SCORES["bar_rank"], "순위"
        return SHAPE_SCORES["bar_base"], "기본"
    return 0, ""


# ── [NEW 11-20 KOS-41] 차트 지정 요청 해석 ────────────────────────────────────────
# 순서: ① 후보 추출 → ② 문맥·범위 해석 → ③ 긍정/제외 분류. 문맥을 먼저 걸면 '막대 말고 원그래프로', '막대나 원그래프로',
# '서울은 막대, 부산은 꺾은선으로' 의 막대가 탈락하므로 제외 표지 · 대안 연결 · 절별 지정도 차트 용법으로 인정한다.
# requested_chart() 는 기존 호출을 위해 그대로 둔다 (노드 · 파이프라인은 parse_chart_request 를 쓴다).
from .chart_type_rules import (  # noqa: E402
    ALTERNATIVE_CONNECTORS, AMBIGUOUS_CHART_WORDS, NAME_TRAILERS, NEGATION_MARKS, UNSUPPORTED_CHART_WORDS,
    USAGE_PREDICATES, USAGE_SUFFIXES,
)

_HANGUL = re.compile(r"[가-힣]")
_PRED = "|".join(map(re.escape, USAGE_PREDICATES))
_USE = re.compile(rf"(?:으로|로|처럼|위에|상에)\s*.{{0,20}}?(?:{_PRED})")      # '막대로 보여줘', '지도 위에 … 보여줘'
_USE_END = re.compile(r"(?:으로|로)\s*(?:$|[,.;!?)\]])")                      # '꺾은선으로' (문장 끝)
_NEG = re.compile(rf"(?:은|는|를|을|도)?\s*(?:{'|'.join(map(re.escape, NEGATION_MARKS))})")
_TOPIC = re.compile(r"([가-힣A-Za-z0-9]+)(?:은|는)\s*$")                       # '서울은 막대' 의 서울


def _candidates(text):
    """① 후보 추출: 지원·미지원 이름의 모든 출현 (긴 이름부터, 찾은 곳은 지워 짧은 이름이 다시 걸리지 않게). 단어 경계만 본다"""
    names = [(w, c, True) for w, c in CHART_WORDS.items()] + [(w, None, False) for w in UNSUPPORTED_CHART_WORDS]
    masked, out = text, []
    for w, code, sup in sorted(names, key=lambda x: -len(x[0])):
        start = 0
        while (i := masked.find(w, start)) >= 0:
            j = start = i + len(w)
            masked = masked[:i] + "\0" * len(w) + masked[j:]
            prev, rest = (text[i - 1] if i else ""), text[j:]
            if w in AMBIGUOUS_CHART_WORDS and _HANGUL.match(prev):               # '운동지도' 의 지도: 다른 말의 일부
                continue
            if rest and _HANGUL.match(rest[0]) and not rest.startswith(NAME_TRAILERS + USAGE_SUFFIXES):   # '지도자', '막대기'
                continue
            out.append({"name": w, "code": code, "supported": sup, "start": i, "end": j,
                        "strong": w not in AMBIGUOUS_CHART_WORDS})
    return sorted(out, key=lambda c: c["start"])


def _resolve(text):
    """② 문맥·범위 해석: 후보마다 용법 여부, 대안 묶음(group), 절별 지정(topic)을 정한다"""
    cands = _candidates(text)
    for k, c in enumerate(cands):
        gap = text[cands[k - 1]["end"]:c["start"]].strip() if k else ""
        c["group"] = (cands[k - 1]["group"] + (0 if (k and gap in ("",) + ALTERNATIVE_CONNECTORS) else 1)) if k else 0
        rest = text[c["end"]:].lstrip()
        flags = set()
        if rest.startswith(USAGE_SUFFIXES):
            flags.add("suffix")
        if _USE.match(rest) or _USE_END.match(rest):
            flags.add("use")
        if _NEG.match(rest):
            flags.add("neg")
        if c["strong"]:
            flags.add("strong")
        m = _TOPIC.search(text[:c["start"]])
        c["topic"], c["flags"] = (m.group(1) if m else None), flags
    multi = len({c["group"] for c in cands}) >= 2
    for c in cands:
        c["bound"] = bool(multi and c["topic"])            # 절별 지정: 그 주제(서울)를 말하는 하위 질문에만 적용
        if c["bound"]:
            c["flags"].add("topic")
    confirmed = {c["group"] for c in cands if c["flags"] & {"suffix", "use", "neg", "strong", "topic"}}
    for c in cands:
        c["confirmed"] = c["group"] in confirmed
        c["role"] = "excluded" if "neg" in c["flags"] else "preferred"      # ③ 분류
    return cands


def _name(c):
    return {"text": c["name"], "code": c["code"], "supported": c["supported"]}


def parse_chart_request(sub_question, original, rewritten):
    """질문 속 차트 지정 요청 → ChartRequestInfo 모양의 dict. 요청이 없으면 None.
    하위 질문 → 원 질문 → 재작성 순서로 찾는다 (재작성에서 '지도로' 같은 말이 빠질 수 있다).
    원 질문의 절별 지정('서울은 막대, 부산은 꺾은선으로')은 주제(서울)가 하위 질문에 있을 때만 적용하고,
    어느 하위 질문의 것인지 정할 수 없으면 요청을 적용하지 않고 ambiguous_scope 로 남긴다 (첫 이름을 모든 차트에 쓰지 않는다)"""
    sub = " ".join(str(sub_question or "").split())
    for text in (sub, original, rewritten):
        text = " ".join(str(text or "").split())
        if not text:
            continue
        cands = [c for c in _resolve(text) if c["confirmed"]]
        if not cands:
            continue
        keep, topic_groups = [], set()
        for c in cands:
            if c["bound"]:
                if c["role"] == "preferred":
                    topic_groups.add(c["group"])
                if text != sub and c["topic"] and c["topic"] in sub:
                    keep.append(c)
                continue
            keep.append(c)
        pref = [c for c in keep if c["role"] == "preferred"]
        exc = [c for c in keep if c["role"] == "excluded"]
        ambiguous = len({c["group"] for c in pref}) >= 2 or (not pref and len(topic_groups) >= 2)
        if not (pref or exc or ambiguous):
            continue
        stage = {"reason": None, "selected": None, "applied": True}
        if ambiguous:
            pref, stage["reason"], stage["applied"] = [], "ambiguous_scope", False
        elif pref and not pref[0]["supported"]:
            stage["reason"] = "unsupported_type"
        return {"preferred": [_name(c) for c in pref], "excluded": [_name(c) for c in exc], "scope": "all", "stage": stage}
    return None


def requested_codes(info):
    """선택 단계에 넘길 (요청 코드 목록, 제외 코드 집합). 미지원 이름은 가장 가까운 지원 차트로 바꿔 후보 앞에 둔다"""
    if not info:
        return [], set()
    codes = []
    for n in info["preferred"]:
        code = n["code"] if n["supported"] else UNSUPPORTED_CHART_WORDS.get(n["text"])
        if code and code not in codes:
            codes.append(code)
    return codes, {n["code"] for n in info["excluded"] if n["code"]}


def record_selection(info, result, block=None):
    """선택 단계의 결과와 사유를 info['stage'] 에 구조화해 남긴다 (설명 문장이 아니라 코드). info 가 None 이면 None.
    block: View 적합도로 차트를 막은 이유 (차단 분기에서도 요청을 기록하기 위해 pick_chart 없이 부른다)"""
    if info is None:
        return None
    st = info["stage"]
    if block:
        st["selected"], st["reason"] = None, "view_blocked"
        return info
    st["selected"] = result["chart_type"]
    if st["reason"] is None:
        req = result.get("request")
        if req and not req["ok"]:
            st["reason"] = "data_mismatch"
        elif result["chart_type"] is None and (info["preferred"] or info["excluded"]):
            st["reason"] = "no_candidate"
    return info


_GENERIC_CLAIM = re.compile(rf"(?:그래프|차트|도표)(?:를|을|로|으로|는|은|가|이|에서|와)?\s*.{{0,12}}?(?:{_PRED}|참고|확인|첨부|제공)")
_NAME_DATA = re.compile(r"\s*(?:데이터|자료|결과)")


def chart_claims(text):
    """[NEW 11-20 KOS-41] 문장 속 차트 서술(차트 용법 + 생성·표시 서술)의 위치 목록 [(시작, 끝, 찾은 말)].
    요청 추출과 같은 후보·용법 판정을 쓴다 — 정의가 둘이면 한쪽만 오탐을 고쳐도 다른 쪽에서 재발한다.
      · 이름이 용법으로 확정(뒤에 그래프·차트 또는 '로 보여줘')된 것
      · 차트 전용 이름 뒤에 데이터·자료·결과 ('히스토그램 데이터는')
      · 일반어 그래프·차트·도표 뒤에 보여·그려·표시·참고 같은 서술
    '지도자' · '막대기' · '도넛 가게' 처럼 다른 말의 일부이거나 용법이 없는 이름은 포함하지 않는다"""
    text = " ".join(str(text or "").split())
    out = []
    for c in _resolve(text):
        used = c["flags"] & {"suffix", "use"}
        data = c["strong"] and _NAME_DATA.match(text[c["end"]:])
        if used or data:
            out.append((c["start"], c["end"], c["name"]))
    out += [(m.start(), m.end(), m.group(0)) for m in _GENERIC_CLAIM.finditer(text)]
    return sorted(out)
