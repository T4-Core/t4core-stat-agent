"""
[NEW] 규칙 템플릿 답변 — HCX 가 실패했거나 두 번 다 검사를 통과하지 못했을 때의 마지막 수단 (HCX 를 부르지 않는다)

  연산마다 정해진 문장 틀에 CalcResult 를 채운다. 자연스러움보다 '항상 맞는 숫자'가 우선이다.
  계산하지 못한 결과는 "계산하지 못했습니다(사유)"로 밝힌다. 주의사항(caveats)은 마지막에 "※" 줄로 덧붙인다.
"""
import re

from backend.agent.answer_compose.facts import _YEAR, Facts, has_value, josa, key_text, points
from backend.agent.answer_compose.reasons import humanize
from backend.agent.chart_calculate.display import strip_unit
from backend.schemas.answer import Caveat
from backend.schemas.chart import CalcInput, CalcResult

MAX_LIST = 5       # 목록 결과를 문장에 풀어 쓰는 최대 개수
SUMMARY_FROM = 10  # [NEW 11-20] 이보다 긴 목록은 나열하지 않고 개수 · 최댓값 · 최솟값으로 요약한다 (write.LIST_PREVIEW 와 같은 한도 — 그 뒤는 HCX 가 인용할 수 없다)
MAX_SCOPE = 3      # 합계 · 평균의 범위(지역 등)를 이름으로 풀어 쓰는 최대 개수 (넘으면 'N개 행정구역')
RATE_LIKE = {"%", "%p", "천명당", "‰", "index"}      # '많은/적은' 이 아니라 '높은/낮은' 을 쓰는 단위
PLACE_HINTS = ("행정구역", "지역", "시도", "시군구")


def _moved(amount: str, v: float, head: str) -> str:
    """head 뒤에 '24.8% 증가했습니다' 를 붙인다. 0 이면 변화 없음"""
    if not v:
        return f"{head}변화가 없습니다."
    if not re.search(r"[1-9]", amount):         # [NEW 11-16] 표시하면 0.0% 인 값에 증가·감소를 붙이지 않는다 (검수 M6-11)
        # [CHANGED 11-17] 이전: f"{head}{amount}로 변화가 거의 없습니다." — '…100,003건으로 0.0%로 …' 처럼 '으로' 가 겹쳤다 (자체 검토 A-8)
        if head.rstrip().endswith("로"):         # '…에서 2025년 100,003건으로' 뒤
            return f"{head.rstrip()}, 변화가 거의 없습니다({amount})."
        return f"{head}변화가 거의 없습니다({amount})."
    return f"{head}{amount} {'증가' if v > 0 else '감소'}했습니다."


def _name(i: CalcInput, drop: dict | None = None) -> str:
    """입력 하나의 이름: '서울특별시 2009년 인구수' (어디의 · 언제의 · 무엇). drop = 두 입력이 공유해 앞에서 한 번만 쓴 key"""
    rest = {c: v for c, v in (i.key or {}).items() if c not in (drop or {})}
    return f"{key_text(rest)} {strip_unit(i.item or '')}".strip()


def _shared(a: CalcInput, b: CalcInput) -> dict:
    """두 입력에서 값이 같은 key 열 (같은 시점 · 같은 지역). 문장 앞에 한 번만 쓴다"""
    kb = b.key or {}
    return {c: v for c, v in (a.key or {}).items() if kb.get(c) == v}


def _side(group: list[CalcInput]) -> tuple[str, str] | None:
    """diff 한쪽(role a 또는 b)의 (지역 등, 항목). 시점을 뺀 key 와 항목이 입력마다 같지 않으면 None"""
    if not group:
        return None
    sides = {(key_text({c: v for c, v in (i.key or {}).items() if c != "시점"}), strip_unit(i.item or "")) for i in group}
    return next(iter(sides)) if len(sides) == 1 else None


def _diff_list(f: Facts, r: CalcResult) -> str | None:
    """시점별 diff: '서울특별시 인구수가 부산광역시보다 2008년 6,307,034명, 2009년 6,339,579명 큽니다.'
    누가 누구보다 큰지(a − b)를 말하고, 부호가 섞이면 식으로 쓴다. 계산 못 한 시점은 문장 끝에 밝힌다. 한쪽을 특정할 수 없으면 None"""
    a, b = _side([i for i in r.inputs if i.role == "a"]), _side([i for i in r.inputs if i.role == "b"])
    pts = points(r)
    ok = [p for p in pts if isinstance(p.get("value"), (int, float))]
    if not (a and b and ok):
        return None
    na = " ".join(x for x in a if x)
    nb = b[0] if b[0] and a[1] == b[1] else " ".join(x for x in b if x)          # 항목이 같으면 '부산광역시보다'
    miss = [key_text(p.get("key")) for p in pts if p not in ok]
    tail = f" ({josa(', '.join(miss), '은')} 계산할 수 없습니다)" if miss else ""
    signs = {v > 0 for v in (p["value"] for p in ok) if v}
    if len(signs) > 1:
        shown = ", ".join(f"{key_text(p.get('key'))} {f.fmt_result(r, p['value'])}" for p in ok)
        return f"{josa(f'{na} − ' + ' '.join(x for x in b if x) + ' 차이', '은')} {shown}입니다.{tail}"
    larger = True in signs or not signs
    shown = ", ".join(f"{key_text(p.get('key'))} {f.fmt_result(r, p['value'], absolute=True)}" for p in ok)
    return f"{josa(na, '이')} {nb}보다 {shown} {'큽니다' if larger else '작습니다'}.{tail}"


def _scope(inputs: list[CalcInput]) -> str:
    """합계 · 평균이 무엇을 합쳤는지: 입력 key 의 열마다 값을 모은다. '서울특별시·부산광역시', '2000~2009년', '17개 행정구역'"""
    cols: dict[str, list] = {}
    for i in inputs:
        for c, v in (i.key or {}).items():
            if v not in cols.setdefault(c, []):
                cols[c].append(v)
    parts = []
    for c, vals in cols.items():
        if c == "시점" and len(vals) > 1 and all(_YEAR.fullmatch(str(v)) for v in vals):
            parts.append(f"{min(vals)}~{max(vals)}년")
        elif len(vals) <= MAX_SCOPE:
            parts.append("·".join(key_text({c: v}) for v in vals))
        else:
            parts.append(f"{len(vals)}개 {c.removesuffix('별')}")
    return " ".join(parts)


def _common_key(pts: list[dict]) -> dict:
    """모든 점에서 값이 같은 key 열 (예: 지역별 순위의 시점 2025). 문장 앞에 한 번만 쓴다.
    모든 열이 같으면 점을 구분할 이름이 사라지므로 묶지 않는다"""
    first = pts[0].get("key") or {}
    common = {c: v for c, v in first.items() if all((p.get("key") or {}).get(c) == v for p in pts)}
    return common if len(pts) > 1 and len(common) < len(first) else {}


def _range_sentence(f: Facts, r: CalcResult, pts: list[dict], common: dict, label: str | None) -> str:
    """[NEW 11-20] 한도(MAX_LIST)를 넘는 목록은 앞 몇 개만 나열하고 '외 N개' 로 줄이지 않고, 코드로 센 개수 · 최댓값 · 최솟값으로 요약한다 (M6-1 ②).
    나열은 질문에 답하지 못하고(앞 10개는 임의의 순서), 요약값은 모두 계산 결과에서 직접 읽는다 — 모델이 요약하지 않는다"""
    vals = [p for p in pts if isinstance(p.get("value"), (int, float)) and not isinstance(p.get("value"), bool)]
    hi, lo = max(vals, key=lambda p: p["value"]), min(vals, key=lambda p: p["value"])
    name = lambda p: key_text({c: v for c, v in (p.get("key") or {}).items() if c not in common})  # noqa: E731
    head = " ".join(x for x in (key_text(common), f.fixed_text(r), label or f.label(r)) if x)
    den = f" (분모: {f.denominator(r)})" if f.denominator(r) else ""
    if hi["value"] == lo["value"]:
        body = f"{len(vals)}개 값이 모두 {f.fmt_result(r, hi['value'])}입니다"
    else:
        body = (f"{len(vals)}개 중 가장 큰 값은 {name(hi)} {f.fmt_result(r, hi['value'])}, "
                f"가장 작은 값은 {name(lo)} {f.fmt_result(r, lo['value'])}입니다")
    return f"{josa(head, '은')} {body}.{den} 전체 값은 아래 표에서 확인할 수 있습니다."


def _list_sentence(f: Facts, r: CalcResult, label: str | None = None) -> str:
    pts = points(r)
    common = _common_key(pts)
    if len(pts) > SUMMARY_FROM and r.op != "rank" and any(isinstance(p.get("value"), (int, float)) for p in pts):
        return _range_sentence(f, r, pts, common, label)
    parts = []
    for p in pts[:MAX_LIST]:
        rest = {c: v for c, v in (p.get("key") or {}).items() if c not in common}
        text = f"{key_text(rest)} {f.fmt_result(r, p.get('value'))}".strip()
        parts.append(f"{p['rank']}위 {text}" if p.get("rank") is not None else text)
    more = f" 외 {len(pts) - MAX_LIST}개" if len(pts) > MAX_LIST else ""
    den = f" (분모: {f.denominator(r)})" if f.denominator(r) else ""
    head = " ".join(x for x in (key_text(common), f.fixed_text(r), label or f.label(r)) if x)
    return f"{josa(head, '은')} {', '.join(parts)}{more}입니다.{den}"


def _extreme(f: Facts, r: CalcResult, p: dict, item: str) -> str:
    """가장 많은/적은 해 · 곳. 최댓값인지 최솟값인지 모르면(answer_steps 를 못 받음) 방향을 단정하지 않는다

    key 에는 시점이 늘 들어 있다. 비교한 입력 전체의 시점이 하나뿐이면 '2009년 …' 으로 앞에 붙이고 곳을 묻는 문장으로 쓴다.
    """
    key, kind = p.get("key") or {}, f.extreme_kind(r)        # item = 대상이 붙은 이름 ('전국 인구수')
    value, where = f.fmt_result(r, p["value"]), key_text(key)
    if kind is None:
        return f"{item}의 극값(최대 또는 최소)은 {where} {value}입니다."
    low = kind == "min"
    word = ("낮은" if low else "높은") if r.unit in RATE_LIKE else ("적은" if low else "많은")
    others = {c: v for c, v in key.items() if c != "시점"}
    time_fixed = "시점" in key and len({i.key.get("시점") for i in r.inputs if i.key}) <= 1
    if "시점" in key and not others and not time_fixed:
        return f"{josa(item, '이')} 가장 {word} 해는 {josa(where, '으로')}, {value}입니다."
    if len(others) == 1 and any(h in next(iter(others)) for h in PLACE_HINTS) and (time_fixed or "시점" not in key):
        when = key_text({"시점": key["시점"]}) + " " if time_fixed else ""
        return f"{when}{josa(item, '이')} 가장 {word} 곳은 {josa(key_text(others), '으로')}, {value}입니다."
    return f"{item} 중 가장 {'작은' if low else '큰'} 값은 {where} {value}입니다."


def _extreme_tie(f: Facts, r: CalcResult, pts: list[dict], item: str) -> str:
    """최댓값·최솟값이 동점일 때: 방향을 말하고 같은 값인 곳(해)을 모두 쓴다 (검수 M6-09)"""
    low = f.extreme_kind(r) == "min"
    word = ("낮은" if low else "높은") if r.unit in RATE_LIKE else ("적은" if low else "많은")
    wheres = ", ".join(key_text(p.get("key") or {}) for p in pts)
    return f"{josa(item, '이')} 가장 {word} 값은 {f.fmt_result(r, pts[0]['value'])}이며, {josa(wheres, '이')} 같습니다."


def _combine_expr(ins: list[CalcInput]) -> str:
    """합산식: '출생아수 − 사망자수', '서울특별시 + 부산광역시 − 대구광역시 출생아수'. 입력의 role 이 부호(+/-)다"""
    items = {strip_unit(i.item or "") for i in ins}
    same = len(items) == 1
    terms: list[tuple[str, str]] = []
    for i in ins:
        place = key_text({c: v for c, v in (i.key or {}).items() if c != "시점"})
        t = ("-" if i.role == "-" else "+", (place if same else strip_unit(i.item or "")) or strip_unit(i.item or ""))
        if t not in terms:
            terms.append(t)
    expr = ""
    for n, (sign, name) in enumerate(terms):
        expr += ("−" if sign == "-" else "") + name if n == 0 else f" {'−' if sign == '-' else '+'} {name}"
    return f"{expr} {next(iter(items))}" if same and len(terms) > 1 and next(iter(items)) else expr


def _combine_place(ins: list[CalcInput]) -> str:
    """합산하는 항목이 서로 다를 때, 모든 입력이 공유하는 지역 등 (시점 제외). 항목이 같으면 지역이 항 이름이라 쓰지 않는다"""
    if len({strip_unit(i.item or "") for i in ins}) == 1 or not ins:
        return ""
    first = ins[0].key or {}
    return key_text({c: v for c, v in first.items() if c != "시점" and all((i.key or {}).get(c) == v for i in ins)})


def sentence(f: Facts, r: CalcResult) -> str:
    base, pts, ins = f.item(r), points(r), r.inputs
    item = " ".join(x for x in (f.fixed_text(r), base) if x)        # 대상이 하나로 고정돼 있으면 앞에: '전국 인구수'
    if not has_value(r):
        return f"{josa(f.label(r), '을')} 계산하지 못했습니다{f'({humanize(r.note, r.inputs)})' if r.note else ''}."
    if r.op in ("extreme", "rank") and len(pts) == 1:      # [CHANGED 11-17] 한 점짜리 순위(top_n 1)도 '가장 ○○한 곳' 문장 (H6)
        return _extreme(f, r, pts[0], item)
    if r.op == "extreme" and len(pts) > 1 and f.extreme_kind(r) and len({p.get("value") for p in pts}) == 1:
        return _extreme_tie(f, r, pts, item)
    if r.op == "diff" and len(pts) > 1 and (text := _diff_list(f, r)):
        return text
    if r.op == "aggregate" and len(pts) > 1:
        return _list_sentence(f, r, f"{base} {f.agg_name(r)}")
    if r.op == "combine" and len(pts) > 1:
        return _list_sentence(f, r, " ".join(x for x in (_combine_place(ins), _combine_expr(ins)) if x))
    if len(pts) > 1 or r.op in ("rank", "extreme", "index"):
        return _list_sentence(f, r)

    v = pts[0]["value"]
    amount = f.fmt_result(r, v, absolute=True)
    way = f.direction(r)                       # 증가 · 감소는 값의 부호가 아니라 끝 − 처음 (-100 → -50 은 증가)
    if r.op in ("growth_rate", "change") and len(ins) >= 2:
        a, b = ins[0], ins[-1]
        head = f"{josa(item, '은')} {key_text(a.key)} {f.fmt_input(a)}에서 {key_text(b.key)} {josa(f.fmt_input(b), '으로')} "
        return _moved(amount, way, head)
    if r.op == "cagr" and len(ins) >= 2:
        return _moved(amount, way, f"{josa(item, '은')} {key_text(ins[0].key)}부터 {key_text(ins[-1].key)}까지 연평균 ")
    if r.op == "change":
        return _moved(amount, way, f"{josa(item, '은')} ")
    if r.op == "share":
        den = f" (분모: {f.denominator(r)})" if f.denominator(r) else ""
        return f"{item}의 비중은 {f.fmt_result(r, v)}입니다.{den}"
    if r.op in ("diff", "ratio") and len(ins) >= 2:
        a, b = ins[0], ins[1]
        shared = _shared(a, b)                                  # 같은 시점 · 지역은 앞에 한 번만
        front = key_text(shared) + " " if shared else ""
        sa, sb = f"{_name(a, shared)}({f.fmt_input(a)})", f"{_name(b, shared)}({f.fmt_input(b)})"
        if r.op == "ratio":
            return f"{front}{josa(_name(a, shared), '은')} {_name(b, shared)}의 {f.fmt_result(r, v)}입니다."
        if not v:
            return f"{front}{josa(sa, '과')} {josa(sb, '은')} 같습니다."
        return f"{front}{josa(sa, '이')} {sb}보다 {amount} {'큽니다' if v > 0 else '작습니다'}."
    if r.op == "aggregate":
        head = " ".join(x for x in (_scope(ins), f.fixed_text(r), f"{base}의 {f.agg_name(r)}") if x)
        return f"{josa(head, '은')} {f.fmt_result(r, v)}입니다."
    if r.op == "combine":
        times = {i.key.get("시점") for i in ins if i.key}
        when = key_text({"시점": next(iter(times))}) if len(times) == 1 and None not in times else ""
        return f"{josa(' '.join(x for x in (when, _combine_place(ins), _combine_expr(ins)) if x), '은')} {f.fmt_result(r, v)}입니다."
    where = f" {key_text(ins[0].key)}" if ins and ins[0].key else ""        # raw 와 나머지: 값 하나
    return f"{josa(item, '은')}{where} {f.fmt_result(r, v)}입니다."


def compose(f: Facts, caveats: list[Caveat]) -> str:
    # [NEW 11-20] 보류된 하위 질문을 대신 보여 주는 값(대체 결과)은 보류 사유를 먼저 말하고 '참고로' 로 이어 쓴다 (M6-2).
    #   '보증부월세는 1,404가구입니다' 가 비율 질문의 답처럼 읽히지 않게 한다. 독립 결과(다른 하위 질문)는 그대로 정식 문장이다
    sentences, said_held = [], set()
    for r in f.req.calc_results:
        if has_value(r) and f.role_of(r) == "대체":
            for w in f.req.withheld:
                if w.sub_question_id == r.sub_question_id and w.text not in said_held:
                    said_held.add(w.text)
                    sentences.append(w.text)
            sentences.append(f"참고로 {sentence(f, r)}")
        else:
            sentences.append(sentence(f, r))
    body = " ".join(sentences)
    # [CHANGED 11-17] 본문이 이미 '…을 계산하지 못했습니다(사유)' 라고 말한 계산의 주의사항은 ※ 줄로 다시 쓰지 않는다 (보고서 12.3).
    #   Module6Output.caveats 에는 그대로 남는다 (화면 · 모듈 7)
    said = {r.step_id for r in f.req.calc_results if not has_value(r)}
    return "\n".join([body, *(f"※ {c.text}" for c in caveats
                              if not (c.source == "calc_note" and c.ref in said) and c.text not in said_held)])
