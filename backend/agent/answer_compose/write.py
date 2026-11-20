"""
[NEW] 답변 작성 (HCX) — 질문 + 계산 결과(자리표시자 목록) + 주의사항 → 자리표시자가 든 답변 초안

  HCX 에게는 '값 미리보기'를 보여 준다(증가·감소 방향을 판단해야 해서). 그래도 문장에 숫자를 쓰면 placeholder.check 가 걸러낸다.
  실패해도 예외를 던지지 않는다. 호출 오류는 (None, 사유)로 돌려주고, 그 뒤 처리(재시도·템플릿)는 graph.py 가 한다.
  (키가 없을 때 core.llm 이 내는 SystemExit 는 설정 오류라 잡지 않는다.)
"""
import json
import re
from typing import Any, Callable

from backend.agent.answer_compose.reasons import humanize
from backend.agent.answer_compose.facts import Facts, has_value, is_list, key_text, points
from backend.agent.answer_compose.placeholder import DIRECTIONAL
from backend.agent.prompts import ANSWER_COMPOSE_SCHEMA, ANSWER_COMPOSE_SYS
from backend.schemas.answer import Caveat
from backend.schemas.chart import CalcResult
from backend.agent.chart_calculate.planner import sub_question_ids

MAX_TOKENS = 1200
LIST_PREVIEW = 10        # 목록 결과에서 프롬프트에 자리표시자를 보여 줄 개수. 그 뒤는 표에만 있고 인용할 수 없다 (shown_tokens)


def _dir_hint(token: str, way, r: CalcResult) -> str:
    """[NEW 11-17] 증감 계산 값에 방향 자리표시자 ({a1.dir} · {a1.r0.dir}). 변화가 0 이면 주지 않는다 (남은 한계 3)"""
    if r.op not in DIRECTIONAL or not isinstance(way, (int, float)) or not way:
        return ""
    return f", 방향 {{{token}.dir}} (미리보기: {'증가' if way > 0 else '감소'})"


def _result_lines(f: Facts, r: CalcResult) -> list[str]:
    kind = {"min": " (최솟값)", "max": " (최댓값)"}.get(f.extreme_kind(r) or "", "") if r.op == "extreme" else ""   # [CHANGED 11-16] 이전: 방향을 모르면 None 글자가 프롬프트에 들어갔다 (검수 M6-04)
    role = " | 참고 결과 (요청한 계산을 하지 못해 대신 보이는 값)" if f.role_of(r) == "대체" and has_value(r) else ""     # [NEW 11-20]
    head = f"{r.step_id} | {f.label(r)}{kind}{role}"
    pts = points(r)
    if not has_value(r):
        return [f"{head} | 계산 불가" + (f" (사유: {humanize(r.note, r.inputs)})" if r.note else "")]
    if not is_list(r):
        lines = [f"{head} | 값 {{{r.step_id}}} (미리보기: {f.fmt_result(r, pts[0]['value'])}){_dir_hint(r.step_id, f.direction(r), r)}"]
    elif len(pts) == 1:
        p = pts[0]
        lines = [f"{head} | 값 {{{r.step_id}}} (미리보기: {f.fmt_result(r, p['value'])}), 이름 {{{r.step_id}.key}} (미리보기: {key_text(p.get('key'))})"]
    else:
        lines = [f"{head} | 값 {len(pts)}개"]
        for n, p in enumerate(pts[:LIST_PREVIEW]):
            base = f"{r.step_id}.r{n}"
            if p.get("value") is None:                     # 계산하지 못한 점은 자리표시자를 주지 않는다 (인용하면 검사에서 걸린다)
                lines.append(f"    {key_text(p.get('key'))}: 계산 불가 (자리표시자 없음)")
                continue
            rank = f", 순위 {{{base}.rank}}" if p.get("rank") is not None else ""
            lines.append(f"    {{{base}}} (미리보기: {f.fmt_result(r, p['value'])}){_dir_hint(base, p['value'], r)}, 이름 {{{base}.key}} (미리보기: {key_text(p.get('key'))}){rank}")
        if len(pts) > LIST_PREVIEW:
            lines.append(f"    … 외 {len(pts) - LIST_PREVIEW}개는 아래 표에 있다 (자리표시자 없음)")
    if den := f.denominator(r):
        idx = next((n for n, i in enumerate(r.inputs) if i.role == "total"), None)
        value = f" (분모 값 {{{r.step_id}.in{idx}}}, 미리보기: {f.fmt_input(r.inputs[idx])})" if idx is not None else ""
        lines.append(f"    분모: {den}{value}")
    if fixed := f.fixed_text(r):
        lines.append(f"    대상: {fixed}")
    if r.inputs and not (is_list(r) and len(pts) > 1):
        ins = [f"{{{r.step_id}.in{n}}}(미리보기: {key_text(i.key)} {f.fmt_input(i)}), 이름 {{{r.step_id}.in{n}.key}}"
               for n, i in enumerate(r.inputs[:4])]
        lines.append("    계산에 쓴 값: " + " / ".join(ins) + (f" … 외 {len(r.inputs) - 4}개" if len(r.inputs) > 4 else ""))
    if r.note:
        lines.append(f"    참고: {humanize(r.note, r.inputs)}")
    return lines


_TOKEN = re.compile(r"\{([^{}]*)\}")
_NOT_A_VALUE = (".key", ".rank", ".abs", ".dir")


def shown_tokens(f: Facts) -> set[str]:
    """[NEW 11-16] 모델에게 보여 준 자리표시자를 결과 줄에서 직접 모은다. 프롬프트 글자를 '[계산 결과]' 로 잘라 찾으면 질문 문장에
    그 표지가 들어 있을 때 엉뚱한 곳을 잘라 정상 답변이 모두 거절된다 (검수 M6-06). .abs 는 값을 뜻하는 것에만 허용"""
    shown = {t.strip() for r in f.req.calc_results for line in _result_lines(f, r) for t in _TOKEN.findall(line)
             if re.fullmatch(r"[\w\-]+(?:\.[\w\-]+)*", t.strip())}
    return shown | {t + ".abs" for t in shown if not t.endswith(_NOT_A_VALUE)}


def build_prompt(f: Facts, caveats: list[Caveat]) -> str:
    b = f.req.query_bundle
    lines = ["[질문]", b.original]
    if len(b.sub_questions) > 1:
        lines += ["[하위 질문]", *(f"- {sid}: {text}" for sid, text in sub_question_ids(b))]
    lines += ["", "[계산 결과]  (값은 자리표시자로만 쓴다. '미리보기'는 방향 판단용이다)"]
    for r in f.req.calc_results:
        lines += _result_lines(f, r)
    lines += ["", "[주의사항]", *(f"- {c.text}" for c in caveats)] if caveats else ["", "[주의사항]", "(없음)"]
    return "\n".join(lines)


def initial_messages(f: Facts, caveats: list[Caveat]) -> list[dict[str, str]]:
    return [{"role": "system", "content": ANSWER_COMPOSE_SYS}, {"role": "user", "content": build_prompt(f, caveats)}]


def retry_messages(messages: list[dict[str, str]], draft: str, problems: list[str]) -> list[dict[str, str]]:
    """첫 시도의 대화 + 초안 + 무엇이 틀렸는지 → 한 번 더 쓰게 한다"""
    # [CHANGED 11-17] 이전: '다음 문제를 고쳐서 처음부터 다시 작성하라' 뒤에 문제만 나열 → 실제 HCX 가 답변 대신 문제 목록을 옮겨 적었다 (H8)
    fix = ("아래는 앞 답변에서 시스템이 찾은 문제다. 문제를 고친 **사용자용 답변 문장만** 처음부터 다시 쓴다. "
           "이 목록이나 규칙 설명을 답변에 옮겨 적지 않는다.\n" + "\n".join(f"- {p}" for p in problems))
    return [*messages[:2], {"role": "assistant", "content": json.dumps({"answer": draft}, ensure_ascii=False)},
            {"role": "user", "content": fix}]


def parse_answer(raw: Any) -> str:
    """chat 의 반환({'answer': …} · {'_raw': …} · 문자열)에서 답변 문장만"""
    if isinstance(raw, dict):
        raw = raw.get("answer") or raw.get("_raw") or ""
    return str(raw or "").strip()


def _short(e: Exception) -> str:
    return str(e)[:120]


def ask(messages: list[dict[str, str]], chat: Callable[..., Any] | None = None) -> tuple[Any, str | None, str | None]:
    """HCX 호출 → (원 응답, 답변 초안, 오류 사유). 오류면 초안은 None"""
    if chat is None:
        from backend.core.llm import chat      # HCX 를 실제로 부를 때만 import (테스트는 HCX 설정 없이 돈다)
    try:
        raw = chat(messages, schema=ANSWER_COMPOSE_SCHEMA, max_tokens=MAX_TOKENS)
    except Exception as e:  # noqa: BLE001  (HcxError, 네트워크 오류 — 답변 전체를 멈추지 않는다)
        return None, None, f"HCX 호출 실패: {_short(e)}"
    return raw, parse_answer(raw), None
