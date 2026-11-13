"""
[NEW] 계산 불가 사유를 사용자용 문장으로 — 모듈 3 의 CalcResult.note (내부 문구) → 화면 · 답변용

  원문(note)은 CalcResult 에 그대로 남는다 (QA · 개발자용). 여기서는 보여 주는 문장만 바꾼다.
  note 는 여러 사유가 '; ' 로 이어져 있고, 사유 하나는 `{'시점': '2008'}: 한쪽 값 없음` 처럼 앞에 key 사전이 붙기도 한다.
  표에 없는 사유는 바꾸지 않고 원문을 그대로 쓴다 (사유를 지어내지 않는다).
  문구의 출처: chart_calculate/calculate.py · select.py 의 notes.append / errors.append
"""
import ast
import re

from backend.agent.answer_compose.facts import josa, key_text
from backend.agent.chart_calculate.display import strip_unit
from backend.schemas.chart import CalcInput

# (정규식, 문장). 문장의 {1} · {2} 는 정규식 그룹. 위에서부터 처음 맞는 것을 쓴다
_RULES: list[tuple[re.Pattern, str]] = [(re.compile(p), t) for p, t in [
    (r"^기준 시점 (\S+) 값 없음$", "기준 시점인 {1}년 값이 없습니다"),
    (r"^시점 (\S+) 값 없음$", "{1}년 값이 없습니다"),
    (r"^기준값 0$", "기준 값이 0이라 비율을 계산할 수 없습니다"),
    (r"^분모 0$", "분모가 0이라 계산할 수 없습니다"),
    (r"^분모 총계 없음$", "분모로 쓸 총계 값이 없습니다"),
    (r"^한쪽 값 없음$", "한쪽 값이 없어 계산하지 못했습니다"),
    (r"^값 없음 \((.+)\)$", "{1} 값이 없어 계산하지 못했습니다"),
    (r"^키 중복 \((.+?):.*\)$", "{1}에 같은 조건의 값이 여러 개라 계산하지 못했습니다"),
    (r"^키 중복$", "같은 조건의 값이 여러 개라 계산하지 못했습니다"),
    (r"^시점이 하나뿐이라 직전 시점이 없음$", "시점이 하나뿐이라 직전 시점과 비교할 수 없습니다"),
    (r"^단위가 다름: (.+)$", "단위가 달라 비교할 수 없습니다: {1}"),
    (r"^단위가 다른 값을 합칠 수 없음: (.+)$", "단위가 다른 값은 합칠 수 없습니다: {1}"),
    (r"^단위를 확인할 수 없음.*$", "단위를 확인할 수 없어 계산하지 않았습니다"),
    (r"^수록 주기가 다름: (.+)$", "수록 주기가 달라 비교할 수 없습니다: {1}"),
    (r"^수록 주기를 확인할 수 없음.*$", "수록 주기를 확인할 수 없어 계산하지 않았습니다"),
    (r"^join_on 필요.*$", "비교할 시점을 정하지 못했습니다"),
    (r"^결합 열이 View 에 없음.*$", "짝지을 기준 열이 자료에 없습니다"),
    (r"^서로 다른 지표를 합칠 수 없음.*$", "서로 다른 지표는 합칠 수 없습니다"),
    (r"^총계 행이 섞여 두 번 셈.*$", "총계 행이 섞여 있어 두 번 세게 되므로 계산하지 않았습니다"),
    (r"^combine 은 피연산자가 2개 이상 필요$", "합산할 값이 2개 이상 필요합니다"),
    (r"^denominator\.operand 없음.*$", "분모로 쓸 총계를 정하지 못했습니다"),
    (r"^항목 없음: (.+)$", "'{1}' 항목이 자료에 없습니다"),
    (r"^열 없음: (.+)$", "자료에 '{1}' 열이 없습니다"),
    (r"^'값' 열 없음$", "자료에 값 열이 없습니다"),
    (r"^조건에 맞는 값이 없음$", "조건에 맞는 값이 없습니다"),
    (r"^truncated: .*$", "자료의 행이 잘려 있어 계산하지 않았습니다"),
    (r"^시점에 없는 값: (.+)$", "{1}년 자료가 없습니다"),
    (r"^(\S+)에 없는 값: (.+)$", "{1}에 {2}이(가) 없습니다"),
]]
_KEYED = re.compile(r"^(\{.*?\}): (.+)$")        # '{'시점': '2008'}: 한쪽 값 없음'


def _list_text(raw: str) -> str:
    """"['서울', '부산']" → "서울, 부산" (파이썬 목록 표기를 읽을 수 있으면)"""
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return raw
    return ", ".join(map(str, value)) if isinstance(value, (list, tuple)) else raw


def _side_name(group: list[CalcInput]) -> str | None:
    """diff · ratio 한쪽(role a 또는 b)의 이름: '부산광역시 인구수'. 입력마다 다르면 None"""
    names = {" ".join(x for x in (key_text({c: v for c, v in (i.key or {}).items() if c != "시점"}), strip_unit(i.item or "")) if x)
             for i in group}
    return next(iter(names)) if len(names) == 1 else None


def _missing_side(key: dict, inputs: list[CalcInput]) -> str | None:
    """'한쪽 값 없음' 의 어느 쪽인가: 그 key(예: 시점 2008)의 값을 가진 입력이 a · b 중 어느 쪽에 없는지.
    모듈 3 의 note 에는 쪽이 없어 입력(CalcInput.role)으로 찾는다. 알 수 없으면 None"""
    roles = {i.role for i in inputs if i.role in ("a", "b")}
    if roles != {"a", "b"}:
        return None
    present = {i.role for i in inputs if all((i.key or {}).get(c) == v for c, v in key.items()) and i.role in ("a", "b")}
    absent = sorted(roles - present)
    if len(absent) == 2:
        return "양쪽"
    if len(absent) == 1:
        return _side_name([i for i in inputs if i.role == absent[0]])
    return None


def _one(reason: str, inputs: list[CalcInput] | None = None) -> str:
    reason = reason.strip()
    if m := _KEYED.match(reason):
        try:
            key = ast.literal_eval(m.group(1))
        except (ValueError, SyntaxError):
            key = None
        if isinstance(key, dict):
            which, rest = key_text(key), _one(m.group(2), inputs)
            if m.group(2).strip() == "한쪽 값 없음" and inputs and (side := _missing_side(key, inputs)):
                rest = "양쪽 값이 없어 계산하지 못했습니다" if side == "양쪽" else f"{side} 값이 없어 계산하지 못했습니다"
            if rest.endswith("못했습니다"):
                return f"{josa(which, '은')} {rest}"
            return f"{which}: {rest}"
    for pattern, text in _RULES:
        if m := pattern.match(reason):
            args = [None, *m.groups()]                       # text 의 {1} · {2} = 정규식 그룹 번호
            args = [a if not (isinstance(a, str) and a.startswith(("['", '["'))) else _list_text(a) for a in args]
            return text.format(*args)
    return reason


def humanize(note: str | None, inputs: list[CalcInput] | None = None) -> str | None:
    """CalcResult.note → 사용자용 문장. 여러 사유는 '; '로 이어 쓴다.
    inputs(CalcResult.inputs)를 주면 '한쪽 값 없음'이 어느 쪽인지(서울 · 부산 …)까지 밝힌다"""
    if not note:
        return note
    return "; ".join(dict.fromkeys(_one(part, inputs) for part in note.split("; ")))
