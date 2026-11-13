"""
[NEW] 모듈 6 공통 재료 — 계산 결과를 사람이 읽는 말로 바꾸는 작은 함수들 (표 · 자리표시자 · 템플릿이 같이 쓴다)

  표시 모양은 모듈 3 의 format_value 를 그대로 쓴다. 차트 · 표 · 답변이 같은 숫자 모양을 내려면 함수가 하나여야 해서다.
  입력값(CalcInput)에는 display_ref 가 없다 → 같은 단위의 displays 설정이 있으면 그것을, 없으면 단위별 기본 자릿수를 쓴다.
"""
import re
from typing import Any

from backend.agent.chart_calculate.display import format_value, make_display, strip_unit
from backend.agent.chart_calculate.select import ITEM_COL, VALUE_COL, find_item_column, to_number
from backend.agent.chart_calculate.validate import TOTAL_LABELS
from backend.schemas.answer import Module6Request
from backend.schemas.chart import CalcInput, CalcResult, Display, Step
from backend.schemas.record import Record

OP_LABEL = {"raw": "조회값", "change": "증감", "growth_rate": "증감률", "cagr": "연평균 증감률", "index": "지수",
            "share": "비중", "diff": "차이", "ratio": "비율", "rank": "순위", "extreme": "극값", "aggregate": "집계",
            "combine": "합산"}
BETWEEN_OPS = {"change", "growth_rate", "cagr", "index"}      # 두 시점(처음 → 끝)을 잇는 연산

# 받침 판단: 한글은 유니코드로, 숫자는 읽는 소리(영·일·삼·육·칠·팔 = 받침 있음)로 본다
_DIGIT_FINAL = {"0": True, "1": True, "2": False, "3": True, "4": False, "5": False, "6": True, "7": True, "8": True, "9": False}
_JOSA = {"은": ("은", "는"), "이": ("이", "가"), "을": ("을", "를"), "과": ("과", "와"), "으로": ("으로", "로")}


def josa(word: str, kind: str) -> str:
    """josa('혼인건수', '은') → '혼인건수는'. kind = 은 · 이 · 을 · 과 · 으로"""
    with_final, without = _JOSA[kind]
    last = word.rstrip()[-1:] if word.strip() else ""
    final = False
    if "가" <= last <= "힣":
        n = (ord(last) - 0xAC00) % 28
        final = n != 0 and not (kind == "으로" and n == 8)     # '으로' 는 ㄹ 받침도 '로'
    elif last in _DIGIT_FINAL:
        final = _DIGIT_FINAL[last]
        if kind == "으로" and last in "178":                    # 일 · 칠 · 팔 = ㄹ 받침
            final = False
    return word + (with_final if final else without)


def key_label(key: dict[str, Any] | None) -> str:
    """{'시점': '2021'} → '2021', {'행정구역별': '서울', '시점': '2021'} → '서울 2021'"""
    return " ".join(str(v) for v in (key or {}).values())


_YEAR = re.compile(r"\d{4}")


def key_text(key: dict[str, Any] | None) -> str:
    """문장용 key_label: 시점이 4자리 연도면 '2021년'. (표는 key_label 그대로 '2021')"""
    return " ".join(f"{v}년" if c == "시점" and _YEAR.fullmatch(str(v)) else str(v) for c, v in (key or {}).items())


def matching_rows(rec: Record, inp: CalcInput, selects: list[dict] | None = None) -> list[int]:
    """계산 입력이 가리키는 View 행 번호: 항목 · key 가 맞고 **값까지 같은** 행.
    입력 key 에는 고정 좌표(전국 · 서울)가 없을 수 있어 값을 함께 봐야 다른 지역의 행을 가려낸다.
    selects = 이 입력을 고른 피연산자의 select 후보. 있으면 그 조건에 드는 행만 (서울만 골랐는데 같은 값의 부산 행까지 잡히지 않게)"""
    cols, rows = rec.table.columns, rec.table.rows
    conds: dict[int, str] = {cols.index(c): str(v) for c, v in (inp.key or {}).items() if c in cols}
    if inp.item is not None:
        found = find_item_column(cols, rows, inp.item)
        if found is None:
            return []
        conds[cols.index(found[0])] = str(found[1])
    if not conds:
        return []              # 조건이 없으면 모든 행이 맞는다
    vi = cols.index(VALUE_COL) if VALUE_COL in cols else None

    def selected(row: list) -> bool:
        if not selects:
            return True
        return any(all(str(row[cols.index(c)]) in {str(v) for v in vals} for c, vals in sel.items() if c in cols) for sel in selects)

    return [k for k, row in enumerate(rows) if all(str(row[c]) == v for c, v in conds.items()) and selected(row)
            and (inp.value is None or vi is None or to_number(row[vi]) == inp.value)]


def points(r: CalcResult) -> list[dict]:
    """CalcResult.value 를 [{'key', 'value', ('rank')}] 로 통일. 값이 없으면 빈 목록"""
    if r.value is None:
        return []
    if isinstance(r.value, list):
        return [p for p in r.value if isinstance(p, dict)]
    return [{"key": {}, "value": r.value}]


def has_value(r: CalcResult) -> bool:
    """계산에 성공한 값이 하나라도 있는가. 목록이 있어도 값이 전부 None 이면(기준값 0인 지수 등) 실패한 계산이다"""
    return any(isinstance(p.get("value"), (int, float)) and not isinstance(p.get("value"), bool) for p in points(r))


def is_list(r: CalcResult) -> bool:
    return isinstance(r.value, list)


class Facts:
    """요청 하나의 계산 결과와 표시 설정을 묶어 문장·표가 같은 방식으로 값을 꺼내게 한다"""

    def __init__(self, req: Module6Request):
        self.req = req
        self.results: dict[str, CalcResult] = {r.step_id: r for r in req.calc_results}
        self.steps: dict[str, Step] = {s.step_id: s for s in req.answer_steps}
        self.displays = req.displays
        self.records: dict[str, Record] = {rec.id: rec for rec in req.records}
        self._coords: dict[int, dict[str, Any]] = {}
        self._owner: dict[int, CalcResult] = {id(i): r for r in req.calc_results for i in r.inputs}

    # ── 계산이 있는가 ──
    @property
    def ok_results(self) -> list[CalcResult]:
        return [r for r in self.req.calc_results if has_value(r)]

    def direction(self, r: CalcResult) -> float | None:
        """증가(+) · 감소(-) 방향. 증감 계산은 값의 부호가 아니라 **끝 − 처음** 으로 판단한다 (-100 → -50 은 증가).
        스칼라 결과만. 입력이 둘 미만이면 값의 부호"""
        pts = points(r)
        if is_list(r) or len(pts) != 1 or not isinstance(pts[0].get("value"), (int, float)):
            return None
        if len(r.inputs) >= 2:
            first, last = r.inputs[0], r.inputs[-1]
            if isinstance(first.value, (int, float)) and isinstance(last.value, (int, float)):
                return last.value - first.value
        return pts[0]["value"]

    def selects_of(self, inp: CalcInput) -> list[dict] | None:
        """이 입력을 고른 피연산자들의 select (answer_steps 가 있을 때). 같은 View · 항목의 피연산자가 여럿이면 모두"""
        r = self._owner.get(id(inp))
        st = self.steps.get(r.step_id) if r else None
        if not st or not st.operands:
            return None
        found = [o.select for o in st.operands if o.record_id == inp.record_id
                 and (o.item is None or inp.item is None or strip_unit(o.item) == strip_unit(inp.item))]
        return [s for s in found if s] or None

    # ── 표시 ──
    def result_display(self, r: CalcResult) -> Display:
        return self.displays.get(r.display_ref or "") or make_display(r.unit)

    def input_display(self, unit: str | None) -> Display:
        for d in self.displays.values():          # 같은 단위의 설정(예: 만 명 환산)이 있으면 그 모양을 따른다
            if unit and d.source_unit == unit:
                return d
        return make_display(unit)

    def fmt_result(self, r: CalcResult, value: Any, absolute: bool = False) -> str:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return "-"
        return format_value(abs(value) if absolute else value, self.result_display(r)) or "-"

    def fmt_input(self, i: CalcInput, absolute: bool = False) -> str:
        if i.value is None:
            return "-"
        return format_value(abs(i.value) if absolute else i.value, self.input_display(i.unit)) or "-"

    # ── 고정 좌표 (지역 · 성별 · 연령 …) ──
    def coords(self, inp: CalcInput) -> dict[str, Any]:
        """입력 값이 있는 View 행에서 key 에 없는 분류 열(지역 · 성별 …)의 값. 행을 못 찾거나 행마다 다르면 그 열은 뺀다"""
        got = self._coords.get(id(inp))
        if got is None:
            got, rec = {}, self.records.get(inp.record_id)
            hits = matching_rows(rec, inp, self.selects_of(inp)) if rec else []
            if hits:
                for n, col in enumerate(rec.table.columns):
                    if col in (VALUE_COL, ITEM_COL):
                        continue
                    vals = {str(rec.table.rows[k][n]) for k in hits}
                    if len(vals) == 1:
                        got[col] = vals.pop()
            self._coords[id(inp)] = got
        return got

    def fixed_text(self, r: CalcResult) -> str:
        """계산 전체에서 하나로 고정된 대상: '전국', '서울특별시 남자 20~29세'. 입력 key 에 없는 열만 (key 에 있는 것은 문장이 이미 쓴다).
        총계 행('계' · '전체')은 의미가 없어 뺀다"""
        if not r.inputs:
            return ""
        in_key = {c for i in r.inputs for c in (i.key or {})}
        per = [self.coords(i) for i in r.inputs]
        fixed = {c: v for c, v in per[0].items()
                 if c not in in_key and c != "시점" and v not in TOTAL_LABELS and all(p.get(c) == v for p in per)}
        return key_text(fixed)

    # ── 이름 ──
    def item(self, r: CalcResult) -> str:
        """계산 대상 항목 이름 (단위 괄호 없이). 입력에서 못 찾으면 연산 이름"""
        for i in r.inputs:
            if i.item:
                return strip_unit(i.item)
        return OP_LABEL.get(r.op, r.op)

    def label(self, r: CalcResult) -> str:
        """표의 '계산' 칸: '혼인건수 증감률'"""
        name = OP_LABEL.get(r.op, r.op)
        return f"{self.item(r)} {name}" if r.inputs and any(i.item for i in r.inputs) else name

    def denominator(self, r: CalcResult) -> str | None:
        """share 의 분모 설명: '전국 대비 — 인구수 2025년 51,325,329명'. 계산할 때 쓴 분모(scope_label + role=total 입력)를 그대로 쓴다"""
        if r.op != "share":
            return None
        totals = [i for i in r.inputs if i.role == "total"]
        if not totals:
            return r.scope_label
        t = totals[0]
        desc = " ".join(x for x in (strip_unit(t.item or ""), key_text(t.key), self.fmt_input(t)) if x)
        desc += f" 외 {len(totals) - 1}개" if len(totals) > 1 else ""
        return f"{r.scope_label} — {desc}" if r.scope_label else desc

    def extreme_kind(self, r: CalcResult) -> str | None:
        """'max' | 'min'. answer_steps 를 못 받았으면 None — 방향을 추측하면 '가장 적은 해'를 '가장 큰 값'으로 답한다.
        단계는 있는데 kind 가 없으면 모듈 3 기본값(max)"""
        st = self.steps.get(r.step_id)
        return None if st is None else str((st.model_extra or {}).get("kind", "max"))

    def agg_name(self, r: CalcResult) -> str:
        st = self.steps.get(r.step_id)
        return {"sum": "합계", "mean": "평균"}.get(st.agg if st and st.agg else "", "집계값")
