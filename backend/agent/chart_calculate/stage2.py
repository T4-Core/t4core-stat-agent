"""
[NEW 11-27] 2차 계산 — 1차 계산(하위 질문마다의 질문용 계산) 결과를 표 하나로 묶고, 그 표 안에서 다시 계산한다

  '2024년 출생아수에서 사망자수를 뺀 값은?' 은 질의 분석이 하위 질문 둘(출생아수 · 사망자수)로 나눠, 세트마다 따로 계산하는
  모듈 3 은 두 값을 조회만 하고 빼지 못했다 (골든 one_20261127_153624). 질의 분석(backend/rag)은 고치지 않고 모듈 3 안에서 푼다.

  흐름 (graph.py answer_steps 노드 끝)
    1. HCX 가 첫 계획에서 2차 계산을 적는다: answers 에 record_id = STAGE1_ID('1차결과'), item = 하위 질문 ID, sub_question_id ""
       → make_plan 은 건너뛰고(planner.is_stage2) 여기서 1차 실행 뒤에 만든다
    2. [CHANGED 11-27] 판별기(find_expressions): 원 질문에서 '하위 질문끼리의 계산 표현'을 찾는다
       ('A에서 B를 뺀' · 'A와 B의 합 · 차이' · 'A가 B보다 얼마나' · 'A는 B의 몇 배'. A · B 는 서로 다른 하위 질문 id 에 하나씩 대응)
       - HCX 2차가 있으면 검사: 표현이 없으면 버림 · 표현과 같으면 그대로 · 다르면(연산 · 순서 · 대상) 규칙 것으로 바꿈
       - HCX 2차가 없으면 안전망: 표현이 있으면 규칙이 만든다 · 없으면 아무것도 안 함
       이전: 질문에 계산 낱말(뺀 · 합계 · 대비 …)이 하나라도 있으면 HCX 2차를 통과시켰다 → '혼인건수 합계와 이혼건수 합계' 도 통과
    3. 1차 결과 → 표 [시점, 항목, 값]. 항목 = 결과 이름 + 단위 ('출생아수(명)') → 단위 검사 · 계산은 기존 연산(combine · diff · ratio) 그대로
    4. 2차 단계(b1, b2 …) 계획 · 실행 → 결과의 표 id 는 1차 계산이 쓴 실제 View 로 바꿔 내보낸다 (모듈 5 · 6 · QA 는 그대로)
    5. 계산할 수 없으면(1차 결과 없음 · 결과가 여럿이라 모호함 · 단위가 다름) 보류 + 이유 (withheld · warnings)
    6. 2차 결과 차트 (s1 …): stage2_chart
"""
import re
from dataclasses import dataclass, field
from typing import Any

from backend.agent.chart_calculate.calculate import TIME_COL, run_answer_steps
from backend.agent.chart_calculate.content import build_chart
from backend.agent.chart_calculate.display import format_value, strip_unit
from backend.agent.chart_calculate.planner import STAGE1_ID, STAGE2_OPS, AnswerDecision, Pick, _Planner, is_stage2, sub_question_ids
from backend.agent.chart_calculate.select import ITEM_COL, VALUE_COL
from backend.schemas.chart import CalcResult, ChartContent, ChartPlan, Display, Plan, Step, Withheld
from backend.schemas.query import QueryBundle
from backend.schemas.record import Record

OP_NAME = {"combine": "더하기·빼기", "diff": "차이", "ratio": "몇 배(비율)", "share": "비중", "growth_rate": "증감률",
           "change": "증감", "aggregate": "합계", "rank": "순위", "extreme": "최댓값·최솟값", "index": "지수", "cagr": "연평균 증감률"}
# 보류 사유의 종류 → 사용자에게 보여 줄 말 (자세한 사유는 notes 에만)
_USER_WHY = {"missing": "필요한 값 중 일부가 없어", "ambiguous": "어느 값을 써야 할지 정할 수 없어",
             "many": "값이 여러 개라 하나로 짝지을 수 없어", "op": "이 계산은 아직 지원하지 않아", "few": "계산할 값이 모자라"}
_RESULT_NAME = {"change": "증감", "growth_rate": "증감률", "cagr": "연평균 증감률", "index": "지수", "share": "비중",
                "diff": "차이", "ratio": "비율", "rank": "순위", "extreme": "최댓값·최솟값", "combine": "합산"}
# ── 판별기: 하위 질문끼리의 계산 표현 ─────────────────────────────
# 원 질문(띄어쓰기 없앤 것)에서 하위 질문을 가리키는 말(그 하위 질문에만 있는 지표 · 대상 · 지역 · 성별 값, 하위 질문 문장의 낱말)의
# 위치를 찾고, 이웃한 두 말(서로 다른 하위 질문) 사이 · 뒤의 글로 표현을 알아본다. 사이 · 뒤의 짧은 낱말(인구 · 수)은 허용하되
# 계산 낱말(합 · 차이 · 증감 · 비율 …)이 끼면 그 낱말은 각 대상에 붙은 것이다 ('혼인건수 합계와 이혼건수 합계') → 표현이 아니다
_REGION_SUFFIX = ("특별자치시", "특별자치도", "특별시", "광역시", "도")
_FILLER_CALC = re.compile(r"합|차이|차는|증감|비율|비중|배|평균|대비|률|율")
_SUB_BETWEEN = re.compile(r"(.{0,6}?)에서(?:는)?")
_SUB_AFTER = re.compile(r"(.{0,6}?)(?:을|를)?(?:뺀|빼면|빼기|빼고|빼서|뺄|차감)")
_CONNECT_BETWEEN = re.compile(r"(.{0,6}?)(?:와|과|랑|이랑|하고|및|,)")
_DIFF_AFTER = re.compile(r"(.{0,6}?)의?(?:차이|격차|차는|차가)")
_SUM_AFTER = re.compile(r"(.{0,6}?)(?:(?:을|를)?(?:더한|더하면|더하기|합친|합치면|합한|합하면)|의?(?:합계|합산|총합|합)(?!계?출산))")   # 합계출산율 제외
_SUBJ_BETWEEN = re.compile(r"(.{0,6}?)(?:이|가|은|는)")
_MORE_AFTER = re.compile(r"(.{0,6}?)보다(?:얼마나|몇)(?!배)")
_TIMES_AFTER = re.compile(r"(.{0,6}?)(?:의|보다)몇배")


@dataclass(frozen=True)
class Expr:
    """하위 질문끼리의 계산 표현 하나. terms = ((하위 질문 ID, 부호), …) — diff · ratio 는 (A, +), (B, +) 순서"""
    op: str
    terms: tuple[tuple[str, str], ...]
    phrase: str

    @property
    def shape(self) -> tuple:
        """같은 계산인지 비교할 모양: 더하기 · 빼기 · 차이 = {(ID, 부호)} (순서 무관, A − B ≠ B − A), 몇 배 = (A, B)"""
        if self.op == "ratio":
            return ("ratio", tuple(s for s, _ in self.terms))
        signs = self.terms if self.op == "combine" else ((self.terms[0][0], "+"), (self.terms[1][0], "-"))
        return ("pm", frozenset(signs))


def _compact(s: str) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def _marks(bundle: QueryBundle) -> dict[str, set[str]]:
    """하위 질문 ID → 그 하위 질문에만 있는 말 (다른 하위 질문에도 있는 말은 가리키지 못한다: 2024년 · 전국)"""
    subs = sub_question_ids(bundle)
    filters = bundle.sub_filters or []
    words: dict[str, set[str]] = {}
    for i, (sid, text) in enumerate(subs):
        f = filters[i] if i < len(filters) else None
        ws = {w for t in str(text).split() if len(w := _compact(t)) >= 2 and not re.fullmatch(r"[\d~.\-년월]+", w)}
        for slot in ("지표", "대상", "지역", "성별"):
            for v in (getattr(f, slot, None) or []) if f is not None else []:
                v = _compact(v)
                if len(v) >= 2:
                    ws.add(v)
                if slot == "지역":                     # 서울특별시 → 서울 (질문에는 짧게 쓴다)
                    ws |= {v[:-len(x)] for x in _REGION_SUFFIX if v.endswith(x) and len(v) - len(x) >= 2}
        words[sid] = ws
    return {sid: {w for w in ws if not any(w in o for s, o in words.items() if s != sid)} for sid, ws in words.items()}


def _mentions(q: str, marks: dict[str, set[str]]) -> list[tuple[int, int, str]]:
    """질문 속 하위 질문 말의 위치 [(시작, 끝, ID)]. 겹치면 앞 · 긴 것, 같은 하위 질문이 바로 이어지면 하나로"""
    found = sorted(((m.start(), m.end(), sid) for sid, ws in marks.items() for w in ws for m in re.finditer(re.escape(w), q)),
                   key=lambda x: (x[0], x[0] - x[1]))
    out: list[tuple[int, int, str]] = []
    for s, e, sid in found:
        if out and s < out[-1][1]:
            continue
        if out and out[-1][2] == sid and s - out[-1][1] <= 3:
            out[-1] = (out[-1][0], e, sid)
            continue
        out.append((s, e, sid))
    return out


def _clean(m: re.Match | None) -> bool:
    """사이 · 뒤의 짧은 낱말에 계산 낱말이 없는가"""
    return bool(m) and not _FILLER_CALC.search(m.group(1))


def find_expressions(bundle: QueryBundle) -> list[Expr]:
    """원 질문의 하위 질문끼리 계산 표현 (A · B 가 서로 다른 하위 질문 ID 에 하나씩 대응할 때만)"""
    q = _compact(bundle.original)
    ms = _mentions(q, _marks(bundle))
    out: list[Expr] = []
    for (s1, e1, a), (s2, e2, b) in zip(ms, ms[1:]):
        if a == b:
            continue
        between, after = q[e1:s2], q[e2:e2 + 16]
        found = None
        if _clean(_SUB_BETWEEN.fullmatch(between)) and _clean(m := _SUB_AFTER.match(after)):
            found = ("combine", ((a, "+"), (b, "-")), m)                                  # A에서 B를 뺀
        elif between in ("-", "−", "–") and (m := re.match("", after)) is not None:
            found = ("combine", ((a, "+"), (b, "-")), m)                                  # A − B
        elif _clean(_CONNECT_BETWEEN.fullmatch(between)):
            if _clean(m := _DIFF_AFTER.match(after)):
                found = ("diff", ((a, "+"), (b, "+")), m)                                 # A와 B의 차이
            elif _clean(m := _SUM_AFTER.match(after)):
                found = ("combine", ((a, "+"), (b, "+")), m)                              # A와 B의 합
        elif _clean(_SUBJ_BETWEEN.fullmatch(between)):
            if _clean(m := _TIMES_AFTER.match(after)):
                found = ("ratio", ((a, "+"), (b, "+")), m)                                # A는 B의 몇 배
            elif _clean(m := _MORE_AFTER.match(after)):
                found = ("diff", ((a, "+"), (b, "+")), m)                                 # A가 B보다 얼마나
        if found:
            op, terms, m = found
            out.append(Expr(op, terms, q[s1:e2 + m.end()]))
    return out


def _decision(e: Expr) -> AnswerDecision:
    """표현 → HCX 와 같은 모양의 2차 결정"""
    if e.op == "combine":
        ops = [Pick(role="term", record_id=STAGE1_ID, item=s, sign=sign) for s, sign in e.terms]
    else:
        ops = [Pick(role=r, record_id=STAGE1_ID, item=s) for r, (s, _) in zip(("a", "b"), e.terms)]
    return AnswerDecision(op=e.op, operands=ops)


def _hcx_shape(a: AnswerDecision, table: "Stage1Table", text_of: dict[str, str]) -> tuple | None:
    """HCX 2차 결정의 모양 (Expr.shape 와 같은 꼴). 하위 질문을 알 수 없거나 같은 하위 질문을 두 번 가리키면 None"""
    label_sid = {lab: sid for sid, labs in table.items_of.items() for lab in labs}
    by_text = {t: s for s, t in text_of.items()}
    sids = []
    for p in a.operands:
        item = p.item or next((str(v) for v in p.select.get(ITEM_COL) or []), "")
        sids.append(item if item in text_of else label_sid.get(item) or by_text.get(item))
    if len(sids) < 2 or None in sids or len(set(sids)) < len(sids):
        return None
    if a.op == "combine":
        return ("pm", frozenset((s, p.sign or "+") for s, p in zip(sids, a.operands)))
    order = [s for s, p in sorted(zip(sids, a.operands), key=lambda x: x[1].role != "a")]
    if a.op == "diff" and len(order) == 2:
        return ("pm", frozenset(((order[0], "+"), (order[1], "-"))))
    if a.op == "ratio" and len(order) == 2:
        return ("ratio", tuple(order))
    return None


def reconcile(hcx: list[AnswerDecision], exprs: list[Expr], table: "Stage1Table",
              text_of: dict[str, str]) -> tuple[list[AnswerDecision], list[str]]:
    """HCX 2차 결정 × 질문 표현 → (쓸 2차 결정, 메모)
      HCX 있음: 표현 없음 → 버림 · 표현과 같음 → HCX 것 · 다름 → 규칙 것으로 바꿈 (남는 HCX 결정은 버림)
      HCX 없음: 표현 있음 → 규칙이 만듦 (안전망)"""
    notes, out, left = [], [], list(exprs)
    for a in hcx:
        sh = _hcx_shape(a, table, text_of)
        same = next((e for e in left if e.shape == sh), None)
        if same is not None:
            out.append(a)
            left.remove(same)
        elif left:
            e = left.pop(0)
            out.append(_decision(e))
            notes.append(f"HCX 2차({a.op})가 질문 표현 '{e.phrase}' 와 달라 규칙 것({e.op})으로 바꿈")
        else:
            notes.append(f"질문에 하위 질문끼리의 계산 표현이 없어 HCX 2차({a.op})를 쓰지 않음")
    for e in left:                                    # 안전망 (HCX 가 적지 않은 표현)
        out.append(_decision(e))
        notes.append(f"안전망 규칙으로 2차 계산 추가 ({e.op}, 표현 '{e.phrase}')")
    return out, notes


def split_stage2(answers: list[AnswerDecision]) -> list[AnswerDecision]:
    """HCX 결정 중 2차 계산(1차결과 표를 쓰는 것)"""
    return [a for a in answers if is_stage2(a)]


@dataclass
class Stage1Table:
    """1차 결과를 묶은 표 + 하위 질문 ID → 항목 이름 + 항목 이름 → 실제 View id"""
    record: Record
    items_of: dict[str, list[str]] = field(default_factory=dict)      # 하위 질문 ID → 그 질문의 결과 항목 이름들
    real_ids: dict[str, list[str]] = field(default_factory=dict)      # 항목 이름 → 1차 계산이 쓴 View id
    skipped: dict[str, str] = field(default_factory=dict)             # 하위 질문 ID → 표에 넣지 못한 이유

    @property
    def has_time(self) -> bool:
        return TIME_COL in self.record.table.columns and len({r[0] for r in self.record.table.rows}) > 1

    def translate(self, picks: list[Pick], text_of: dict[str, str]) -> tuple[list[Pick], tuple[str, str] | None]:
        """HCX 피연산자(item = 하위 질문 ID 또는 표의 항목 이름) → 표의 항목. 못 바꾸면 ([], (종류, 자세한 이유))"""
        items = list(self.real_ids)
        by_text = {t: s for s, t in text_of.items()}
        out = []
        for pk in picks:
            if pk.record_id != STAGE1_ID:
                return [], ("missing", f"2차 계산 재료 '{pk.record_id}' 는 1차결과 표가 아님")
            want = pk.item or next((str(v) for v in pk.select.get(ITEM_COL) or []), None)
            sid = want if want in self.items_of or want in self.skipped else by_text.get(want or "")
            if want in items:
                name = want
            elif sid in self.items_of and len(self.items_of[sid]) == 1:
                name = self.items_of[sid][0]
            elif sid in self.items_of:
                return [], ("ambiguous", f"하위 질문 {sid} 의 1차 결과가 여럿이라 ({self.items_of[sid]}) 어느 값을 쓸지 모호함")
            elif sid in self.skipped:
                return [], ("many", self.skipped[sid])
            else:
                return [], ("missing", f"1차결과 표에 '{want}' 가 없음 (1차 결과가 없는 하위 질문)")
            sel = {c: v for c, v in pk.select.items() if c != ITEM_COL and c in self.record.table.columns}
            out.append(pk.model_copy(update={"item": name, "select": sel}))
        return out, None

    def to_real(self, r: CalcResult) -> CalcResult:
        """2차 결과의 표 id(1차결과) → 1차 계산이 쓴 실제 View (모듈 5 · 6 · QA 가 아는 id). key 의 항목 열은 뺀다"""
        def real(item):
            return (self.real_ids.get(item or "") or [STAGE1_ID])[0]
        inputs = [i.model_copy(update={"record_id": real(i.item), "key": {k: v for k, v in i.key.items() if k != ITEM_COL}})
                  for i in r.inputs]
        ids = list(dict.fromkeys(x for i in r.inputs for x in self.real_ids.get(i.item or "", [])))
        return r.model_copy(update={"inputs": inputs, "record_ids": ids or r.record_ids})


def _result_name(r: CalcResult, step: Step | None, sub_text: str) -> str:
    """1차 결과의 이름 (단위 없이): 입력 항목이 하나면 그 이름, 아니면 단계의 항목 → 하위 질문 문장. 연산 이름을 붙인다 (raw · aggregate 합계 제외)"""
    items = list(dict.fromkeys(strip_unit(i.item) for i in r.inputs if i.item))
    if len(items) == 1:
        base = items[0]
    elif step and step.operands and step.operands[0].item:
        base = strip_unit(step.operands[0].item)
    else:
        base = sub_text or r.step_id
    if r.op == "aggregate":
        word = "평균" if r.agg == "mean" else ""
    else:
        word = "" if r.op == "raw" else _RESULT_NAME.get(r.op, "")
    return " ".join(x for x in (base, word) if x)


def _place(step: Step | None) -> dict[str, str]:
    """1차 단계가 하나로 고정한 조건 (시점 · 항목 제외) — 이름이 겹칠 때 구분에 쓴다 (서울특별시 · 부산광역시)"""
    out: dict[str, str] = {}
    for o in (step.operands or []) if step else []:
        for c, vals in (o.select or {}).items():
            if c not in (TIME_COL, ITEM_COL) and len(vals) == 1:
                out.setdefault(c, str(vals[0]))
    return out


def stage1_table(results: list[CalcResult], steps: list[Step], bundle: QueryBundle) -> Stage1Table:
    """1차 결과(하위 질문이 있고 값이 있는 질문용 계산) → 표 [시점?, 항목, 값]"""
    text_of = dict(sub_question_ids(bundle))
    step_of = {s.step_id: s for s in steps}
    table = Stage1Table(record=Record(id=STAGE1_ID, lexical_text="1차 계산 결과", parent_id=f"table::{STAGE1_ID}",
                                      table={"columns": [ITEM_COL, VALUE_COL], "rows": []}))
    entries = []          # (하위 질문 ID, 결과, 이름, [(시점, 값)])
    for r in results:
        sid = r.sub_question_id
        if sid is None or r.value is None:
            continue
        if isinstance(r.value, list):
            pts = [p for p in r.value if isinstance(p, dict)]
            others = {c for p in pts for c in (p.get("key") or {}) if c != TIME_COL}
            if others or any(TIME_COL not in (p.get("key") or {}) for p in pts):
                table.skipped[sid] = f"하위 질문 {sid} 의 1차 결과가 {sorted(others) or '시점 없는'} 값 여러 개라 2차 계산 재료로 쓰지 않음"
                continue
            vals = [(str(p["key"][TIME_COL]), p.get("value")) for p in pts if p.get("value") is not None]
        else:
            times = {str(i.key[TIME_COL]) for i in r.inputs if TIME_COL in (i.key or {})}
            vals = [(times.pop() if len(times) == 1 else None, r.value)]
        name = _result_name(r, step_of.get(r.step_id), text_of.get(sid, ""))
        entries.append((sid, r, name, vals))
    # 이름이 겹치면(서울 인구 · 부산 인구 → 둘 다 '총인구수') 서로 다른 고정 조건을 앞에 붙이고, 그래도 겹치면 하위 질문 ID
    names = [e[2] for e in entries]
    for k, (sid, r, name, vals) in enumerate(entries):
        if names.count(name) > 1:
            mine = _place(step_of.get(r.step_id))
            others = [_place(step_of.get(e[1].step_id)) for j, e in enumerate(entries) if j != k and names[j] == name]
            diff = [v for c, v in mine.items() if any(o.get(c) != v for o in others)]
            entries[k] = (sid, r, " ".join([*diff, name]) if diff else f"{name} [{sid}]", vals)
    with_time = [e for e in entries if all(t is not None for t, _ in e[3])]
    use_time = bool(entries) and len(with_time) == len(entries)
    if not use_time and with_time and any(len(e[3]) > 1 for e in with_time):
        # 여러 해인 결과와 시점 없는 결과가 섞이면 짝지을 수 없다 → 시점 없는 결과를 뺀다
        for sid, r, name, vals in [e for e in entries if e not in with_time]:
            table.skipped[sid] = f"하위 질문 {sid} 의 1차 결과에 시점이 없어 다른 결과와 짝지을 수 없음"
        entries, use_time = with_time, True
    rows = []
    for sid, r, name, vals in entries:
        label = f"{name}({r.unit})" if r.unit else name
        table.items_of.setdefault(sid, []).append(label)
        table.real_ids[label] = list(r.record_ids)
        rows += [[t, label, v] if use_time else [label, v] for t, v in vals]
    cols = [TIME_COL, ITEM_COL, VALUE_COL] if use_time else [ITEM_COL, VALUE_COL]
    table.record = table.record.model_copy(update={"table": table.record.table.model_copy(update={"columns": cols, "rows": rows})})
    return table


def run_stage2(bundle: QueryBundle, plan: ChartPlan, displays: dict[str, Display], results: list[CalcResult],
               answers: list[AnswerDecision]) -> tuple[ChartPlan, dict[str, Display], list[CalcResult], list[ChartContent]]:
    """2차 계산 → (2차 단계 · 메모 · 보류를 더한 ChartPlan, displays, 2차 결과를 앞에 둔 calc_results, 2차 결과 차트).
    answers = HCX 가 적은 2차 결정. 질문 표현과 맞춰 본다 (reconcile: 검사 + 안전망). 둘 다 없으면 그대로 돌려준다"""
    exprs = find_expressions(bundle)
    if not answers and not exprs:
        return plan, displays, results, []
    notes, warnings, withheld = [], [], []
    table = stage1_table(results, plan.answer_steps, bundle)
    text_of = dict(sub_question_ids(bundle))
    answers, why = reconcile(answers, exprs, table, text_of)
    notes += [f"2차: {x}" for x in why]
    if not answers:
        return plan.model_copy(update={"notes": [*plan.notes, *notes]}), displays, results, []

    def hold(a: AnswerDecision, kind: str, why: str) -> None:
        """보류: notes 에는 자세한 이유, 사용자에게는(warnings · withheld) 쉬운 말"""
        text = f"{_USER_WHY[kind]} 하위 질문 결과로 하는 {OP_NAME.get(a.op, a.op)} 계산을 하지 못했습니다."
        notes.append(f"2차 보류: {why}")
        warnings.append(text)
        withheld.append(Withheld(op=a.op, text=text))

    p = _Planner([table.record], {})
    p.displays = dict(displays)                          # 표시 설정 번호가 1차와 겹치지 않게 이어서 등록한다
    steps: list[Step] = []
    for n, a in enumerate(answers, 1):
        if a.op not in STAGE2_OPS:
            hold(a, "op", f"2차 계산은 combine · diff · ratio 만 지원 (받은 연산: {a.op})")
            continue
        picks, why = table.translate(a.operands, text_of)
        if why:
            hold(a, *why)
            continue
        if len(picks) < 2:
            hold(a, "few", "2차 계산 재료가 2개 미만")
            continue
        d = a.model_copy(update={"join_on": [TIME_COL]}) if table.has_time else a.model_copy(update={"join_on": None})
        steps.append(p.step(f"b{n}", f"b{n}", a.op, picks, d))
    notes += [f"2차: {x}" for x in p.notes]
    raw = run_answer_steps(steps, [table.record]) if steps else []
    done = [table.to_real(r) for r in raw]
    if steps:
        notes.append(f"2차: 1차결과 표 {table.record.table.columns} {len(table.record.table.rows)}행으로 {[s.step_id for s in steps]} 계산")
    # [NEW 11-27] 2차 결과 차트 (계산이 된 것만). 모듈 2 는 하위 질문마다 차트를 정해 값 하나짜리(2024 출생아수)는 차트가 없었다
    contents = []
    for st, r, real in zip(steps, raw, done):
        content, why = stage2_chart(st, r, table, p, real.record_ids)
        if content is not None:
            contents.append(content)
        notes.append(f"2차 차트: {why}")
    new_plan = plan.model_copy(update={
        "answer_steps": [*steps, *plan.answer_steps], "notes": [*plan.notes, *notes],
        "warnings": list(dict.fromkeys([*plan.warnings, *warnings])), "withheld": [*plan.withheld, *withheld]})
    return new_plan, p.displays, [*done, *results], contents


# ── 2차 결과 차트 ────────────────────────────────────────────────
STAGE2_CHART = "s"         # 2차 차트 번호 앞글자 (b1 → s1). 모듈 2 의 차트(c1 …)와 겹치지 않는다


def _term_names(st: Step) -> list[tuple[str, str]]:
    """2차 단계 피연산자 → [(부호, 이름)] (diff 는 a − b, ratio 는 a ÷ b 순서)"""
    ops = list(st.operands or [])
    if st.op in ("diff", "ratio"):
        ops = sorted(ops, key=lambda o: o.role != "a")
        return [("+", strip_unit(o.item or "")) for o in ops]
    return [(o.sign or "+", strip_unit(o.item or "")) for o in ops]


def _expr(st: Step) -> str:
    """식 이름: '출생아수 − 사망자수' · '출생아수 ÷ 사망자수' · '출생 + 순이동 − 사망'"""
    terms = _term_names(st)
    if st.op == "ratio":
        return f"{terms[0][1]} ÷ {terms[1][1]}"
    out = ""
    for k, (sign, name) in enumerate(terms):
        minus = sign == "-" if st.op == "combine" else k > 0          # diff: a − b
        out += (("−" if minus else "") + name) if k == 0 else f" {'−' if minus else '+'} {name}"
    return out


def _when(times: list[str]) -> str:
    """제목 앞의 기간: '2024년' · '2015~2024년' (시점이 연도가 아니면 그대로)"""
    if not times:
        return ""
    yr = lambda t: f"{t}년" if str(t).isdigit() else str(t)       # noqa: E731
    return yr(times[0]) if len(times) == 1 else f"{times[0]}~{yr(times[-1])}"


def stage2_chart(st: Step, r: CalcResult, table: Stage1Table, p: _Planner, real_ids: list[str]) -> tuple[Any, str]:
    """2차 단계 하나 → (ChartContent | None, 메모)
      시점 하나 · 더하기·빼기 / 차이 → 막대: 1차 값들 + 결과 (결과 막대 강조)
      시점 하나 · 몇 배           → 막대: 1차 값 둘, 제목에 결과 ('… 의 0.7배')
      여러 해 · 더하기·빼기 / 차이  → 막대: 해마다의 결과 (0 기준, 줄어든 해는 빨강 — 모듈 5 부호 색)
      여러 해 · 몇 배             → 꺾은선: 해마다의 결과 (시점이 3개 미만이면 막대)
    1차 값의 차트는 모듈 2 가 하위 질문마다 그리므로(여러 해) 겹쳐 그리지 않는다"""
    if r.value is None:
        return None, f"{st.step_id} 결과가 없어 차트를 만들지 않음"
    cols = table.record.table.columns
    many = isinstance(r.value, list)
    times = [str(x["key"].get(TIME_COL)) for x in r.value] if many else \
        sorted({str(row[0]) for row in table.record.table.rows}) if TIME_COL in cols else []
    expr, unit = _expr(st), r.unit
    emphasis = None
    if many:
        rows = [[str(x["key"].get(TIME_COL)), f"{expr}({unit})" if unit else expr, x["value"]] for x in r.value]
        chart_cols = [TIME_COL, ITEM_COL, VALUE_COL]
        chart_type, measure = ("line", "ratio") if st.op == "ratio" else ("bar", st.op)
        title = f"{_when(times)} {expr}" if st.op != "ratio" else f"{_when(times)} {expr}(배)"
        ref = st.display_ref
    else:
        ii, vi = cols.index(ITEM_COL), cols.index(VALUE_COL)
        value_of = {str(row[ii]): row[vi] for row in table.record.table.rows}
        ordered = sorted(st.operands or [], key=lambda o: o.role != "a") if st.op in ("diff", "ratio") else list(st.operands or [])
        rows = [[o.item, value_of.get(o.item or "")] for o in ordered]
        chart_cols, chart_type, measure = [ITEM_COL, VALUE_COL], "bar", "raw"
        ref = p.ref("raw", [ordered[0].unit if ordered else None], p.source_digits(
            "raw", [(table.record.id, o.item, o.select) for o in ordered], ordered[0].unit if ordered else None))
        if st.op == "ratio":
            shown = format_value(r.value, p.displays[st.display_ref]) if st.display_ref in p.displays else f"{r.value:.1f}배"
            title = " ".join(x for x in (_when(times), f"{_term_names(st)[0][1]}는 {_term_names(st)[1][1]}의 {shown}") if x)
        else:
            rows.append([f"{expr}({unit})" if unit else expr, r.value])
            emphasis = [expr]
            title = " ".join(x for x in (_when(times), expr) if x)
    rec = Record(id=f"{STAGE1_ID}::{st.step_id}", lexical_text=title, parent_id=f"table::{STAGE1_ID}",
                 table={"columns": chart_cols, "rows": rows})
    plan = Plan(chart_id=STAGE2_CHART + st.step_id[1:], record_id=rec.id, chart_type=chart_type, measure=measure,
                steps=[Step(step_id="s1", op="raw", display_ref=ref)], title=title,
                fallback_charts=["bar"] if chart_type == "line" else [])
    content, check = build_chart(plan, [rec], None, p.displays)
    if content is None:
        why = "; ".join(check.original.reasons) or "검증 실패"
        return None, f"{plan.chart_id} 를 만들지 못함 ({why})"
    opt = {**content.options, "stage2": True, **({"emphasis": emphasis} if emphasis else {})}
    content = content.model_copy(update={"options": opt, "record_ids": real_ids or content.record_ids})
    return content, f"{plan.chart_id} {content.chart_type} ({title})"
