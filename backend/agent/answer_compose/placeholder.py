"""
[NEW] 자리표시자 — HCX 는 숫자를 쓰지 않고 '{a1}' 같은 빈칸만 쓴다. 코드가 CalcResult 로 채우고, 못 믿을 문장은 걸러낸다

  문법 (a1 = CalcResult.step_id)
    {a1}            계산 결과 값. 결과가 하나(스칼라 또는 한 점짜리 목록)일 때
    {a1.abs}        같은 값의 절댓값 ("감소했습니다 {a1.abs}" 처럼 방향을 말로 쓸 때)
    {a1.key}        한 점짜리 목록(극값 등)의 이름 (예: 의성군)
    {a1.rN}         목록 결과의 N번째 값 (N 은 0부터)     {a1.rN.abs} · {a1.rN.key} · {a1.rN.rank}
    {a1.inN}        계산에 쓴 N번째 입력값                {a1.inN.abs} · {a1.inN.key} (예: 2021)

  검사 4가지 (check)
    1. 풀 수 없는 자리표시자 (없는 ID · 값 없는 계산 · 범위 밖 번호)
    2. 자리표시자 밖의 숫자 (질문 · 계산 결과 · 주의사항에 나온 숫자는 허용 — 연도 · 지역 이름 속 숫자)
    3. 값이 있는 계산인데 한 번도 인용하지 않음 ("계산한 데이터가 대답에 쓰여야 한다")
    4. 부호와 방향 단어가 반대 (음수 증감률인데 "증가했습니다")
"""
import re
from dataclasses import dataclass, field

from backend.agent.answer_compose.facts import Facts, has_value, is_list, key_label, key_text, points
from backend.schemas.answer import Caveat

_BRACE = re.compile(r"\{([^{}]*)\}")
_PART = re.compile(r"^(?:(r|in)(\d+)(?:\.(abs|key|rank))?|(abs|key))$")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")
DIRECTIONAL = {"growth_rate", "change", "cagr"}            # 부호가 증가·감소를 뜻하는 연산 (diff 는 누가 큰지라 제외)
UP_WORDS = ("증가", "상승", "늘었", "늘어", "올랐", "올라", "확대")
DOWN_WORDS = ("감소", "하락", "줄었", "줄어", "내렸", "내려", "축소", "떨어")
_VALUE_PART = re.compile(r"(?:abs|r\d+(?:\.abs)?)?")                # 결과 값을 뜻하는 자리표시자 (입력값 in · 이름 key · 순위 rank 는 아니다)
_LABEL_THEN_PERCENT = re.compile(r"\{[^{}]*\.(?:key|rank)\}\s*%")      # '{a1.in0.key}%' — 시점 이름을 수치처럼 씀
_VALUE_WITH_UNIT = re.compile(r"^-?[\d,]+(?:\.\d+)?\s?([^\d\s,.\-]{1,3})$")    # '6,092,672명' · '24.8%' · '2021년' → 단위 부분
_NEUTRAL = re.compile(r"(?:증가|감소|상승|하락|증감)(?:율|폭)")   # '증가율은 -2.4%' 처럼 방향을 말하지 않는 낱말


@dataclass
class Filled:
    text: str
    problems: list[str] = field(default_factory=list)
    used: list[str] = field(default_factory=list)      # 인용한 step_id (처음 나온 순서)
    value_used: list[str] = field(default_factory=list)   # 그중 **결과 값**을 인용한 step_id (입력값 · 시점 · 이름만 인용한 것은 빠진다)


def _resolve(f: Facts, token: str) -> tuple[str, str] | str:
    """'{...}' 안쪽 → (step_id, 채울 문자열). 풀 수 없으면 사유 문자열"""
    sid, _, part = token.strip().partition(".")
    r = f.results.get(sid)
    if r is None:
        return f"없는 계산 ID: {{{token}}}"
    pts = points(r)
    if not has_value(r):
        return f"계산하지 못한 값을 인용함: {{{token}}}"
    if not part:                                          # {a1}
        if len(pts) != 1:
            return f"{{{token}}}: 값이 {len(pts)}개라 번호가 필요함 ({{{sid}.r0}} …)"
        return sid, f.fmt_result(r, pts[0]["value"])
    m = _PART.match(part)
    if not m:
        return f"알 수 없는 자리표시자: {{{token}}}"
    kind, n, sub, bare = m.group(1), m.group(2), m.group(3), m.group(4)
    sub = sub or bare
    if kind is None:                                      # {a1.abs} · {a1.key}
        if len(pts) != 1:
            return f"{{{token}}}: 값이 {len(pts)}개라 번호가 필요함 ({{{sid}.r0}} …)"
        p, src = pts[0], "r"
    else:
        n, src = int(n), kind
        seq = pts if src == "r" else r.inputs
        if n >= len(seq):
            return f"{{{token}}}: {n}번째가 없음 (총 {len(seq)}개)"
        p = seq[n]
    if src == "r":
        value, key, rank = p.get("value"), key_text(p.get("key")), p.get("rank")
        if value is None:                                  # 목록 중 계산하지 못한 점 (예: 한쪽 값이 없는 시점)
            return f"계산하지 못한 값을 인용함: {{{token}}}" + (f" ({key})" if key else "")
        if sub == "key":
            return (sid, key) if key else f"{{{token}}}: 이름(key)이 없음"
        if sub == "rank":
            return (sid, str(rank)) if rank is not None else f"{{{token}}}: 순위가 없음"
        return sid, f.fmt_result(r, value, absolute=sub == "abs")
    if sub == "key":
        return (sid, key_text(p.key)) if p.key else f"{{{token}}}: 이름(key)이 없음"
    if sub == "rank":
        return f"{{{token}}}: 입력값에는 순위가 없음"
    return sid, f.fmt_input(p, absolute=sub == "abs")


# 계산된 정확한 값 앞뒤의 어림 표현. 앞: "약 317,680명" · 뒤: "317,680명 정도". 단어 경계에서만 ('계약 {a1}' 의 '약' 은 건드리지 않는다)
_APPROX_BEFORE = re.compile(r"(?:(?<=\s)|^)(?:약|대략|거의)\s*$")
# 뒤쪽은 조사가 달라지지 않는 경우만: 공백 · 구두점 · 끝, 또는 받침과 무관한 서술형(입니다 · 이었 · 이다 · 이고 · 이며 · 이라).
# '정도로' · '정도에서' 는 지우면 '건로' 처럼 조사가 어색해져 그대로 둔다 (프롬프트로 막는다)
_APPROX_AFTER = re.compile(r"\s*(?:정도|가량|쯤)(?=[\s.,)]|$|입니다|이었|이다|이고|이며|이라)")
_NUMERIC = re.compile(r"^-?\d")


def _fill_text(template: str, replace) -> str:
    """자리표시자를 바꾼다. 채운 값이 이미 단위로 끝나는데('6,092,672명') 템플릿이 그 단위를 또 쓰면('{a1}명') 한 번만 남긴다.
    HCX 가 '{a1}명' 이라고 써서 '6,092,672명명' 이 되던 문제 (실제 HCX 시험에서 확인)"""
    out, pos = [], 0
    for m in _BRACE.finditer(template):
        before = template[pos:m.start()]
        got = replace(m)
        if _NUMERIC.match(got):                       # 숫자 값 앞의 '약' · '대략' 은 뺀다
            before = _APPROX_BEFORE.sub("", before)
        out.append(before)
        out.append(got)
        pos = m.end()
        if (u := _VALUE_WITH_UNIT.match(got)) and template.startswith(u.group(1), pos):
            pos += len(u.group(1))
        if _NUMERIC.match(got) and (a := _APPROX_AFTER.match(template, pos)):     # 숫자 값 뒤의 '정도' · '가량' 도
            pos = a.end()
    out.append(template[pos:])
    return "".join(out)


def fill(template: str, f: Facts, allowed: set[str] | None = None) -> Filled:
    """자리표시자를 값으로 바꾼다. 풀 수 없는 것은 problems 에 모으고 그 자리는 그대로 둔다.
    allowed = 모델에게 **실제로 보여 준** 자리표시자 (write.allowed_tokens). 주면 그 밖의 것은 풀 수 있어도 거절한다"""
    out = Filled(text="")

    def sub(m: re.Match) -> str:
        token = m.group(1).strip()
        if allowed is not None and token not in allowed:
            out.problems.append(f"프롬프트에 없는 자리표시자: {{{token}}} — [계산 결과]에 적힌 것만 쓴다")
            return m.group(0)
        got = _resolve(f, token)
        if isinstance(got, str):
            out.problems.append(got)
            return m.group(0)
        if got[0] not in out.used:
            out.used.append(got[0])
        if _VALUE_PART.fullmatch(token.partition(".")[2]) and got[0] not in out.value_used:
            out.value_used.append(got[0])
        return got[1]
    out.text = _fill_text(template, sub)
    if "{" in _BRACE.sub("", template) or "}" in _BRACE.sub("", template):
        out.problems.append("짝이 맞지 않는 중괄호")
    out.problems = list(dict.fromkeys(out.problems))
    return out


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUM.findall(text)}


def allowed_numbers(f: Facts, caveats: list[Caveat]) -> set[str]:
    """문장에 직접 써도 되는 숫자: 질문 · 하위 질문 · 계산의 키(시점) · 항목 이름 · 주의사항에 이미 나온 것"""
    b = f.req.query_bundle
    texts = [b.original, b.rewritten or "", *b.sub_questions, *(c.text for c in caveats)]
    for r in f.req.calc_results:
        texts += [r.scope_label or "", f.fixed_text(r)]
        texts += [key_label(i.key) for i in r.inputs] + [i.item or "" for i in r.inputs]
        texts += [key_label(p.get("key")) for p in points(r) if isinstance(p, dict)]
    return _numbers(" ".join(texts))


def direction_problems(template: str, f: Facts) -> list[str]:
    """부호와 방향 단어의 모순: 감소(음수) 계산을 '증가했습니다'로, 증가(양수)를 '감소했습니다'로 쓴 문장

    문장마다 방향 계산(growth_rate · change · cagr)이 정확히 하나일 때만 본다 (둘 이상이면 어느 단어가 어느 계산 것인지 알 수 없다).
    """
    out = []
    for sentence in _SENTENCE.split(template):
        ids = {tok.partition(".")[0].strip() for tok in _BRACE.findall(sentence)}
        dirs = [r for i in ids if (r := f.results.get(i)) and r.op in DIRECTIONAL and not is_list(r) and f.direction(r)]
        if len(dirs) != 1:
            continue
        r, text = dirs[0], _NEUTRAL.sub("", _BRACE.sub("", sentence))
        up, down = any(w in text for w in UP_WORDS), any(w in text for w in DOWN_WORDS)
        way = f.direction(r)                       # 끝 − 처음 (음수 기준값의 증감률은 부호가 거꾸로일 수 있어 값의 부호가 아니다)
        if (way < 0 and up and not down) or (way > 0 and down and not up):
            out.append(f"방향이 맞지 않음: {{{r.step_id}}} 은 {'감소' if way < 0 else '증가'}인데 반대로 씀 — 계산에 쓴 두 값의 차이로 방향을 맞춘다")
    return out


def check(template: str, filled: Filled, f: Facts, caveats: list[Caveat]) -> list[str]:
    """fill 의 problems 에 더해 자리표시자 밖 숫자 · 인용 누락을 찾는다"""
    problems = list(filled.problems)
    if not template.strip():
        return ["답변이 비어 있음"]
    stray = sorted(_numbers(_BRACE.sub("", template)) - allowed_numbers(f, caveats))
    if stray:
        problems.append(f"자리표시자 밖에 숫자를 직접 씀: {', '.join(stray)} — 숫자는 자리표시자로만 쓴다")
    problems += direction_problems(template, f)
    if _LABEL_THEN_PERCENT.search(template):
        problems.append("시점·이름 자리표시자 뒤에 %를 붙임 — 수치는 결과 값 자리표시자({a1} 등)로 쓴다")
    missing = [r.step_id for r in f.ok_results if r.step_id not in filled.value_used]
    if missing:
        problems.append(f"인용하지 않은 계산 결과: {', '.join(missing)} — 입력값·시점이 아니라 **결과 값**({{{missing[0]}}} 등)을 한 번은 인용한다")
    return problems
