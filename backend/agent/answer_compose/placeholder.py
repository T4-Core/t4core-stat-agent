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
_PART = re.compile(r"^(?:(r|in)(\d+)(?:\.(abs|key|rank|dir))?|(abs|key|dir))$")      # [CHANGED 11-17] .dir 추가
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")
DIRECTIONAL = {"growth_rate", "change", "cagr"}            # 부호가 증가·감소를 뜻하는 연산 (diff 는 누가 큰지라 제외)
UP_WORDS = ("증가", "상승", "늘었", "늘어", "올랐", "올라", "확대")
DOWN_WORDS = ("감소", "하락", "줄었", "줄어", "내렸", "내려", "축소", "떨어")
_VALUE_PART = re.compile(r"(?:abs|r\d+(?:\.abs)?)?")                # 결과 값을 뜻하는 자리표시자 (입력값 in · 이름 key · 순위 rank 는 아니다)
_LABEL_THEN_PERCENT = re.compile(r"\{[^{}]*\.(?:key|rank|dir)\}\s*%")      # '{a1.in0.key}%' — 시점 이름을 수치처럼 씀
# '6,092,672명' · '24.8%' · '2021년' · '934만 명' → (큰 수 단위, 단위)
# [CHANGED 11-24] 이전: 숫자 바로 뒤의 단위만 읽었다 → '934만 명' 은 단위를 못 읽어 '{a1}명' 이 '934만 명명' 이 됐다 (골든셋)
_VALUE_WITH_UNIT = re.compile(r"^-?[\d,]+(?:\.\d+)?(?:\s?([만억조]))?\s?([^\d\s,.\-]{1,3})$")
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
    if sub == "dir" and (why := _no_direction(r, src)):
        return f"{{{token}}}: {why}"
    if src == "r":
        value, key, rank = p.get("value"), key_text(p.get("key")), p.get("rank")
        if value is None:                                  # 목록 중 계산하지 못한 점 (예: 한쪽 값이 없는 시점)
            return f"계산하지 못한 값을 인용함: {{{token}}}" + (f" ({key})" if key else "")
        if sub == "dir":
            # [NEW 11-17] 방향은 코드가 채운다: 값 하나짜리 증감은 끝 − 처음, 목록은 그 점의 값 (남은 한계 3, 결정: 방향도 자리표시자로)
            way = f.direction(r) if kind is None and not is_list(r) else value
            if not way:
                return f"{{{token}}}: 변화가 없는 값이라 방향을 쓸 수 없음 — '변화가 없다'고 말로 쓴다"
            return sid, "증가" if way > 0 else "감소"
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


def _no_direction(r, src: str) -> str | None:
    if r.op not in DIRECTIONAL:
        return "증감 계산이 아니라 방향(.dir)이 없음"
    if src == "in":
        return "입력값에는 방향(.dir)이 없음"
    return None


# 계산된 정확한 값 앞뒤의 어림 표현. 앞: "약 317,680명" · 뒤: "317,680명 정도". 단어 경계에서만 ('계약 {a1}' 의 '약' 은 건드리지 않는다)
_APPROX_BEFORE = re.compile(r"(?:(?<=\s)|^)(?:약|대략|거의)\s*$")
# 뒤쪽은 조사가 달라지지 않는 경우만: 공백 · 구두점 · 끝, 또는 받침과 무관한 서술형(입니다 · 이었 · 이다 · 이고 · 이며 · 이라).
# '정도로' · '정도에서' 는 지우면 '건로' 처럼 조사가 어색해져 그대로 둔다 (프롬프트로 막는다)
_APPROX_AFTER = re.compile(r"\s*(?:정도|가량|쯤)(?=[\s.,)]|$|입니다|이었|이다|이고|이며|이라)")
_NUMERIC = re.compile(r"^-?\d")
# 값이 이미 단위로 끝날 때, 템플릿이 같은 뜻으로 또 쓰는 말 (긴 것부터)
_ECHOES = {"%p": ("퍼센트포인트", "포인트", "%p", "%"), "%": ("퍼센트", "%"), "‰": ("퍼밀", "‰")}


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
        if u := _VALUE_WITH_UNIT.match(got):
            # [CHANGED 11-16] 이전: 같은 단위만 지웠다 → '{a1}%' 가 '2.6%p%', '{a1}포인트' 가 '2.6%p포인트' 가 됐다 (검수 M6-05)
            scale, unit = u.groups()
            echoes = ((f"{scale} {unit}", f"{scale}{unit}") if scale else ()) + _ECHOES.get(unit, (unit,))   # '{a1}만 명' 도 한 번만
            echo = next((e for e in echoes if template.startswith(e, pos)), None)
            if echo:
                pos += len(echo)
        if _NUMERIC.match(got) and (a := _APPROX_AFTER.match(template, pos)):     # 숫자 값 뒤의 '정도' · '가량' 도
            pos = a.end()
    out.append(template[pos:])
    return "".join(out)


def fill(template: str, f: Facts, allowed: set[str] | None = None) -> Filled:
    """자리표시자를 값으로 바꾼다. 풀 수 없는 것은 problems 에 모으고 그 자리는 그대로 둔다.
    allowed = 모델에게 **실제로 보여 준** 자리표시자 (write.shown_tokens). 주면 그 밖의 것은 풀 수 있어도 거절한다"""
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


def _allowed_text(f: Facts, caveats: list[Caveat]) -> str:
    b = f.req.query_bundle
    texts = [b.original, b.rewritten or "", *b.sub_questions, *(c.text for c in caveats)]
    for r in f.req.calc_results:
        texts += [r.scope_label or "", f.fixed_text(r)]
        texts += [key_label(i.key) for i in r.inputs] + [i.item or "" for i in r.inputs]
        texts += [key_label(p.get("key")) for p in points(r) if isinstance(p, dict)]
    return " ".join(texts)


def allowed_numbers(f: Facts, caveats: list[Caveat]) -> set[str]:
    """문장에 직접 써도 되는 숫자: 질문 · 하위 질문 · 계산의 키(시점) · 항목 이름 · 주의사항에 이미 나온 것"""
    return _numbers(_allowed_text(f, caveats))


# [NEW 11-16] 숫자 + 수량 단위('2025%', '5배', '2021건'). 연도·나이처럼 이름으로 쓰인 숫자는 허용해도, 수치처럼 쓰면 안 된다 (검수 M6-01)
# 만 · 억 · 조 · 백만 · 천 이 붙은 수량('2025만 건', '3.5억 원', '2천 건')도 본다. 크기 말만 붙은 것('2025만')도 수량이다 (검수 2)
_QUANTITY = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*((?:백만|천만|만|억|조|천)?\s*(?:%p|%|퍼센트|‰|배|명|건|가구|호|개|원|천명당|포인트)|백만|천만|만|억|조)")


def _quantities(text: str) -> set[tuple[str, str]]:
    """{(숫자, 단위)}. 단위의 공백은 뗀다 ('만 건' = '만건')"""
    return {(n.replace(",", ""), re.sub(r"\s+", "", u)) for n, u in _QUANTITY.findall(text)}


# 값 사이가 '나열' 일 뿐이면(쉼표 · 와/과 · 시점) 뒤의 서술어를 같이 쓴다: '2022년 {a1.r0.abs}, 2023년 {a1.r1.abs} 감소했습니다'
_LIST_GAP = re.compile(r"^[\s,·/와과및]*(?:\d{4}년?\s*(?:\d{1,2}월|\d분기|[상하]반기)?)?[\s,·/와과및]*$")


def _directional(token: str, f: Facts) -> tuple[str, float, bool] | None:
    """증감 계산 값을 가리키는 자리표시자 → (이름, 방향 부호, 부호째 음수로 보이는가). 입력값(.inN) · 이름(.key) 등은 None.
    방향: 값 하나짜리는 끝 − 처음(Facts.direction), 목록은 그 점의 값"""
    sid, _, part = token.partition(".")
    r = f.results.get(sid)
    if r is None or r.op not in DIRECTIONAL:
        return None
    absolute = part == "abs" or part.endswith(".abs")
    base = "" if part == "abs" else part.removesuffix(".abs")
    pts = points(r)
    if m := re.fullmatch(r"r(\d+)", base):
        n = int(m.group(1))
        value = pts[n].get("value") if n < len(pts) else None
        name, way = f"{sid}.r{n}", value
    elif base == "" and len(pts) == 1:
        value = pts[0].get("value")
        name, way = sid, (f.direction(r) if not is_list(r) else value)
    else:
        return None
    if not isinstance(way, (int, float)) or isinstance(way, bool) or not way:
        return None
    shown_negative = not absolute and isinstance(value, (int, float)) and f.fmt_result(r, value).startswith("-")
    return name, way, shown_negative


def _words(text: str) -> tuple[bool, bool]:
    text = _NEUTRAL.sub("", text)
    return any(w in text for w in UP_WORDS), any(w in text for w in DOWN_WORDS)


def _predicate(sentence: str, marks: list[re.Match], i: int) -> tuple[bool, bool]:
    """i 번째 자리표시자가 받는 증가 · 감소 낱말: 바로 뒤 서술어(다음 자리표시자 전까지). 나열이면 그 뒤 서술어, 뒤에 없으면 바로 앞"""
    j = i
    while True:
        seg = sentence[marks[j].end(): marks[j + 1].start() if j + 1 < len(marks) else len(sentence)]
        up, down = _words(seg)
        if up or down or j + 1 >= len(marks) or not _LIST_GAP.match(seg):
            break
        j += 1
    if not (up or down):
        up, down = _words(sentence[marks[i - 1].end() if i else 0: marks[i].start()])
    if not (up or down):          # [NEW 11-17] 마지막으로 그 값이 든 절 전체 ('증가세가 이어져 {a1.r0.abs}, {a1.r1.abs}를 기록했습니다', 남은 한계 3)
        up, down = _words(_BRACE.sub(" ", _clause(sentence, marks[i])))
    return up, down


_CLAUSE_END = re.compile(r"(?:고|며|지만|는데|으나|면서)\s+")      # 절을 잇는 어미 + 띄어쓰기


def _clause(sentence: str, mark: re.Match) -> str:
    start = max((m.end() for m in _CLAUSE_END.finditer(sentence) if m.end() <= mark.start()), default=0)
    end = min((m.start() for m in _CLAUSE_END.finditer(sentence) if m.start() >= mark.end()), default=len(sentence))
    return sentence[start:end]


def direction_problems(template: str, f: Facts) -> list[str]:
    """값과 방향 낱말의 모순. [CHANGED 11-17 외부 피드백] 이전: 문장 전체에서 낱말을 찾았다 → 방향이 섞인 문장을 구분하지 못했다
    ('2022년 4.4% 증가했고 2024년 3.6% 감소' 통과, '2022년 -4.4%였고 2024년 3.6% 증가' 거절). 이제 값마다 그 값의 서술어(_predicate)로 본다.
      감소(음수)인데 증가 낱말만 / 증가(양수)인데 감소 낱말만 → 방향이 맞지 않음
      음수 값을 부호째(.abs 없이) 쓰고 그 서술어에 방향 낱말이 있음 → '-4.4% 감소' 는 4.4% 증가로도 읽힌다 (.abs 로 쓴다)"""
    out = []
    for sentence in _SENTENCE.split(template):
        marks = list(_BRACE.finditer(sentence))
        for i, m in enumerate(marks):
            if (got := _directional(m.group(1).strip(), f)) is None:
                continue
            name, way, shown_negative = got
            up, down = _predicate(sentence, marks, i)
            nxt = marks[i + 1] if i + 1 < len(marks) else None
            if nxt and nxt.group(1).strip().endswith(".dir") and not sentence[m.end(): nxt.start()].strip():
                # [NEW 11-17] 바로 옆의 방향 자리표시자도 방향을 말한 것이다: '{a1.r0} {a1.r0.dir}' → '-0.4% 감소' (실제 HCX 재확인, H7)
                owner = nxt.group(1).strip().removesuffix(".dir")
                if owner != name:
                    out.append(f"방향 자리표시자 {{{owner}.dir}} 가 옆의 값 {{{name}}} 이 아니라 다른 값의 방향을 가리킴 — {{{name}.dir}} 를 쓴다")
                if shown_negative:
                    out.append(f"음수 값을 부호째 쓰고 방향 자리표시자를 붙임: {{{name}}} — 방향을 쓸 때는 절댓값 {{{name}.abs}} 를 쓴다")
            if shown_negative and (up or down):
                out.append(f"음수 값을 부호째 쓰고 증가·감소를 말로 함께 씀: {{{name}}} — 방향을 말로 쓸 때는 절댓값 {{{name}.abs}} 를 쓴다")
            if way < 0 and up and not down:
                out.append(f"방향이 맞지 않음: {{{name}}} 은 감소인데 반대로 씀 — 계산에 쓴 두 값의 차이로 방향을 맞춘다")
            elif way > 0 and down and not up:
                out.append(f"방향이 맞지 않음: {{{name}}} 은 증가인데 반대로 씀 — 계산에 쓴 두 값의 차이로 방향을 맞춘다")
    return list(dict.fromkeys(out))


# 답변에는 나오지 않고 프롬프트 · 검사 문구에만 나오는 말 (사용자용 문장에 쓸 일이 없다)
_META_WORDS = ("자리표시자", "절댓값", "미리보기", "[계산 결과]", "[주의사항]")
_RANK_WORD = re.compile(r"(\d+)\s*위")
_BINDS_BEFORE = re.compile(r"\s*(?:으로|로|이|가|은|는|에서)?\s*")     # '{a1.r0}으로 1위' · '{a1.r0.key}가 1위'
_BINDS_AFTER = re.compile(r"\s*[:：]?\s*")                           # '1위 {a1.r0.key}' · '1위: {a1.r0.key}'


def _rank_numbers(template: str, f: Facts) -> tuple[set[str], set[str]]:
    """[NEW 11-17] 'N위' 의 숫자 → (맞는 것, 틀린 것). 같은 줄에서 바로 뒤의 자리표시자(없으면 바로 앞)가 순위 N 인 점을 가리키면 맞다.
    HCX 가 '1위: {a1.r0.key} ({a1.r0})' 처럼 쓴 순위 목록이 두 번 다 날숫자로 거절됐다 (보고서 11.3 H5, 실제 HCX)"""
    ok, bad = set(), set()
    for line in template.splitlines():
        marks = list(_BRACE.finditer(line))
        for m in _RANK_WORD.finditer(line):
            after = next((t for t in marks if t.start() >= m.end()), None)
            before = next((t for t in reversed(marks) if t.end() <= m.start()), None)
            # [CHANGED 11-17] 이전: 바로 뒤 자리표시자를 먼저 봤다 → '{a1.r0}으로 1위를 차지하였고, 그 뒤를 이어 {a1.r1.key}' 가
            #   2위 값에 맞춰져 거절됐다 (실제 HCX 재확인). 문법으로 묶인 쪽을 본다: '{값}으로 N위' 는 앞, 'N위 {이름}' · 'N위: {이름}' 은 뒤.
            #   둘 다 아니면 글자 거리로 가까운 쪽
            to_before = before is not None and _BINDS_BEFORE.fullmatch(line[before.end(): m.start()])
            to_after = after is not None and _BINDS_AFTER.fullmatch(line[m.end(): after.start()])
            if to_after:
                near = after
            elif to_before:
                near = before
            else:
                gap_after = after.start() - m.end() if after else None
                gap_before = m.start() - before.end() if before else None
                near = after if gap_before is None or (gap_after is not None and gap_after <= gap_before) else before
            (ok if _rank_of(near, f) == int(m.group(1)) else bad).add(m.group(1))
    return ok, bad


def _rank_of(mark: re.Match | None, f: Facts) -> int | None:
    if mark is None:
        return None
    sid, _, part = mark.group(1).strip().partition(".")
    r = f.results.get(sid)
    if r is None or not (m := re.match(r"r(\d+)", part)):
        return None
    pts = points(r)
    n = int(m.group(1))
    return pts[n].get("rank") if n < len(pts) else None


def _point_names(pts: list[dict]) -> list[set[str]]:
    """점마다 그 점을 다른 점과 구분하는 이름들 (값이 달라지는 key 열만). 4자리 시점은 '2024년' 도 이름이다"""
    cols = [c for c in dict.fromkeys(c for p in pts for c in (p.get("key") or {}))
            if len({str((p.get("key") or {}).get(c)) for p in pts}) > 1]
    out = []
    for p in pts:
        names = set()
        for c in cols:
            v = str((p.get("key") or {}).get(c))
            names.add(v)
            if c == "시점" and re.fullmatch(r"\d{4}", v):
                names.add(f"{v}년")
        out.append(names)
    return out


def name_problems(template: str, f: Facts) -> list[str]:
    """[NEW 11-17] 값 자리표시자 바로 앞(앞 자리표시자 뒤부터)에 직접 쓴 이름이 그 값의 이름인가.
    HCX 가 '경기도가 {a1.r0}' 처럼 이름을 {a1.r0.key} 없이 쓴다 (실제 HCX, 보고서 12.3). 가장 가까운 이름 하나로 판단한다"""
    out = []
    for sentence in _SENTENCE.split(template):
        marks = list(_BRACE.finditer(sentence))
        for i, m in enumerate(marks):
            token = m.group(1).strip()
            sid, _, part = token.partition(".")
            r = f.results.get(sid)
            if r is None or not is_list(r) or not (mm := re.fullmatch(r"r(\d+)(?:\.abs)?", part)):
                continue
            k, pts = int(mm.group(1)), points(r)
            if len(pts) < 2 or k >= len(pts):
                continue
            names = _point_names(pts)
            seg = sentence[marks[i - 1].end() if i else 0: m.start()]
            best = None                                   # (끝 위치, 길이, 점 번호, 이름): 가장 가까운(뒤쪽) · 긴 이름
            for j, ns in enumerate(names):
                for n in ns:
                    for occ in re.finditer(re.escape(n), seg):
                        cand = (occ.end(), len(n), j, n)
                        best = cand if best is None or cand[:2] > best[:2] else best
            if best and best[2] != k and best[3] not in names[k]:
                own = key_text({c: v for c, v in (pts[k].get("key") or {}).items() if str(v) in names[k]})
                out.append(f"{{{token}}} 의 이름은 {own} 인데 {best[3]} 로 씀 — 이름은 {{{sid}.r{k}.key}} 를 쓴다")
    return out


# [NEW 11-18] F14: '17.5% 로 전국 대비 {a1.r0.key}' — 비교 대상 이름 자리에 이름표(.key = 점의 시점이나 지역)를 썼다 (Q28 '전국 대비 2021년'). 숫자는 맞아서 다른 검사를 통과했다
_VS_KEY = re.compile(r"(?:대비|에\s*비해|에\s*비하여)\s*\{([^{}]*)\.key\}")
_OMITTED = re.compile(r"외\s*(\d+)\s*개")


def vs_key_problems(template: str, f: Facts) -> list[str]:
    """'… 대비' 뒤 이름 자리에 이름표(.key)를 썼는데 그 이름표가 **시점**일 때 (share 결과). 지역이 이름표인 문장은 정상이다:
    '서울 대비 {a1.r0.key} 의 차이'(diff), '전국 대비 {a1.r0.key} 의 비중'(지역별 share)  (검토 8)"""
    out = []
    for m in _VS_KEY.finditer(template):
        sid, _, part = m.group(1).strip().partition(".")
        r = f.results.get(sid)
        if r is None or r.op != "share":
            continue
        pts = points(r)
        idx = re.fullmatch(r"(r|in)(\d+)", part or "")
        src = (r.inputs if idx and idx.group(1) == "in" else pts)
        key = (src[int(idx.group(2))] if idx and int(idx.group(2)) < len(src) else (src[0] if src else {}))
        key = key.get("key") if isinstance(key, dict) else getattr(key, "key", None)
        if set(key or {}) == {"시점"}:
            out.append("'… 대비' 뒤에 시점 이름표(.key)를 씀 — 이름표는 그 값의 시점이라 비교 대상이 아니다. 비교 대상(전국 등)은 질문에 나온 말 그대로 쓴다")
    return out


def coverage_problems(template: str, f: Facts) -> tuple[list[str], set[str]]:
    """[NEW 11-18] F15: 목록 결과(여러 시점 · 지역)의 일부만 나열했는가 → (문제, 허용할 생략 개수). 현재는 앞 LIST_PREVIEW 개만 인용할 수 있어
    전체 나열을 강제하지 않는다. 둘 이상 나열하면서 일부를 뺐다면 ① 뺀 개수를 '외 N개' 로 **정확히** 말하고 ② 상세는 표에 있다고 안내해야 한다
    (Q31: 1981~1990 만 서술하고 1991~1999 누락). '외 N개' 가 있다는 이유만으로 통과시키지 않는다. 순위 · 극값은 상위 몇 개만 말해도 되는 질문이다"""
    out, allowed = [], set()
    plain = _BRACE.sub(" ", template)
    stated = {int(n) for n in _OMITTED.findall(plain)}
    for r in f.ok_results:
        pts = [p for p in points(r) if p.get("value") is not None] if is_list(r) else []
        if len(pts) < 2 or r.op in ("rank", "extreme"):
            continue
        cited = {int(m.group(1)) for m in re.finditer(r"\{" + re.escape(r.step_id) + r"\.r(\d+)(?:\.\w+)?\}", template)}
        omitted = len(pts) - len(cited)
        if not cited or omitted <= 0 or cited != set(range(len(cited))):
            continue                  # 앞에서부터 이어서 나열하다 만 경우만 본다 (r0, r2 처럼 골라 말한 것은 의도한 선택). 첫 값 하나만 말하고 뺀 것을 밝히지 않은 경우도 포함한다 (검토 7)
        allowed.add(str(omitted))
        if omitted in stated and "표" in plain:
            continue
        out.append(f"{r.step_id}: 결과 {len(pts)}개 중 {len(cited)}개만 서술함 — 전부 쓰거나, 뺀 {omitted}개를 '외 {omitted}개'로 밝히고 상세는 표에 있다고 안내한다")
    return out, allowed


def chart_claim_problems(template: str) -> list[str]:
    """[NEW 11-20 KOS-41] 차트 상태 서술을 거절한다. 모듈 6 은 모듈 5 와 병렬이라 답변 시점에는 렌더링 결과를 모른다 (성공 서술이 M5 실패와 충돌).
    차트 안내는 agent/chart_notice.py 가 최종 상태 기준으로 따로 만든다. 이름이 문장에 들어 있다는 이유만으로는 거절하지 않는다
    ('운동지도자 수는 …' 의 지도). 판정은 요청 추출과 같은 함수(chart_type_preference.chart_claims)를 쓴다"""
    from backend.agent.chart_decision.chart_decision_module.chart_type_preference import chart_claims
    plain = _BRACE.sub(" ", template or "")
    found = chart_claims(plain)
    if not found:
        return []
    words = ", ".join(dict.fromkeys(w for _, _, w in found))
    return [f"차트·그래프의 유형이나 생성 여부를 서술함 ({words}) — 차트에 대한 말을 쓰지 않고 숫자와 의미만 쓴다"]


_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+|\n+")
_REASON = re.compile(r"하지\s*못|수\s*없|없어|없습니다|않았|불가")


def reference_problems(template: str, f: Facts) -> list[str]:
    """[NEW 11-20] 참고 결과(보류된 요청을 대신 보여 주는 값)는 **그 값을 쓰는 문장마다** '참고로' 로 시작해야 하고, 그 앞에 계산하지 못한 사유 문장이 있어야 한다.
    답변 어딘가에 '참고' 라는 말이 있다는 것만 보면 '참고 자료는 아래 표에 있습니다. 비율은 1,404가구입니다' 가 통과한다 (M6-2)"""
    subs = [r.step_id for r in f.ok_results if f.role_of(r) == "대체"]
    if not subs:
        return []
    sentences = [x.strip() for x in _SENTENCE_END.split(template) if x.strip()]
    out = []
    for sid in subs:
        mark = re.compile(r"\{" + re.escape(sid) + r"[.}]")
        at = [i for i, x in enumerate(sentences) if mark.search(x)]
        if not at:
            continue
        if any(not re.match(r"참고로", sentences[i]) for i in at):
            out.append(f"참고 결과({sid})를 쓰는 문장이 '참고로'로 시작하지 않음 — 질문의 답처럼 읽힌다. 그 값은 '참고로 …' 문장에만 쓴다")
        elif not any(_REASON.search(x) for x in sentences[:at[0]]):
            out.append(f"참고 결과({sid}) 앞에 요청한 계산을 하지 못한 사유가 없음 — 먼저 계산하지 못한 사유를 밝히고, 그 값은 '참고로 …' 문장에 쓴다")
    return out


def check(template: str, filled: Filled, f: Facts, caveats: list[Caveat]) -> list[str]:
    """fill 의 problems 에 더해 자리표시자 밖 숫자 · 인용 누락을 찾는다"""
    problems = list(filled.problems)
    if not template.strip():
        return ["답변이 비어 있음"]
    ok_ranks, bad_ranks = _rank_numbers(template, f)
    coverage = coverage_problems(template, f)                 # [NEW 11-18] 뺀 개수('외 N개')의 N 은 자리표시자 밖 숫자로 걸리지 않게 허용 (F15)
    stray = sorted(_numbers(_BRACE.sub("", template)) - allowed_numbers(f, caveats) - (ok_ranks - bad_ranks) - coverage[1])
    if stray:
        hint = ""
        if bad_ranks & set(stray) and (sid := next((r.step_id for r in f.ok_results if any("rank" in p for p in points(r))), None)):
            hint = f" (순위는 '{{{sid}.r0.rank}}위' 처럼 순위 자리표시자로 쓴다)"      # [NEW 11-17] 재시도 안내 (H5)
        problems.append(f"자리표시자 밖에 숫자를 직접 씀: {', '.join(stray)} — 숫자는 자리표시자로만 쓴다{hint}")
    # 이미 '자리표시자 밖 숫자' 로 걸린 숫자는 한 번만 알린다
    if quantities := sorted(q for q in _quantities(_BRACE.sub(" ", template)) - _quantities(_allowed_text(f, caveats))
                            - {(n, "개") for n in coverage[1]} if q[0] not in stray):       # '외 3개' 의 3개는 생략 개수 안내라 허용 (검토 7)
        problems.append("숫자와 단위를 직접 씀: " + ", ".join(f"{n}{u}" for n, u in quantities)
                        + " — 연도·나이가 아닌 수치는 자리표시자로만 쓴다")
    if meta := sorted({w for w in _META_WORDS if w in _BRACE.sub(" ", template)}):
        # [NEW 11-17] 재시도에서 HCX 가 답변 대신 고칠 점을 옮겨 적었고 다른 검사는 모두 통과했다 (보고서 11.3 H8, 실제 HCX)
        problems.append(f"답변이 아니라 지시문을 옮겨 적음 ({', '.join(meta)}) — 질문에 대한 답변 문장만 쓴다")
    problems += direction_problems(template, f)
    problems += name_problems(template, f)
    problems += vs_key_problems(template, f)
    problems += coverage[0]
    problems += chart_claim_problems(template)
    if _LABEL_THEN_PERCENT.search(template):
        problems.append("시점·이름 자리표시자 뒤에 %를 붙임 — 수치는 결과 값 자리표시자({a1} 등)로 쓴다")
    # [NEW 11-20] 참고 결과(보류된 요청을 대신 보여 주는 값)를 인용했는데 답변에 '참고' 가 없으면 그 값이 질문의 답처럼 읽힌다 (M6-2)
    problems += reference_problems(template, f)
    missing = [r.step_id for r in f.ok_results if r.step_id not in filled.value_used]
    if missing:
        problems.append(f"인용하지 않은 계산 결과: {', '.join(missing)} — 입력값·시점이 아니라 **결과 값**({{{missing[0]}}} 등)을 한 번은 인용한다")
    return problems
