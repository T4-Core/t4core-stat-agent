"""
[NEW] 근거 표 만들기 — CalcResult · Record → AnswerTable[]   (HCX 를 부르지 않는다)

  순서: 계산 요약표 1개 → 값이 여러 개인 계산마다 목록표 → 계산에 쓴 원본 View 표
  표시 문자열(rows)은 모듈 3 의 format_value, 원래 값(raw_rows)은 그대로 둔다 (QA 가 다시 계산해 볼 수 있게).
"""
from typing import Any

from backend.agent.answer_compose.caveats import used_record_ids
from backend.agent.answer_compose.reasons import humanize
from backend.agent.answer_compose.facts import BETWEEN_OPS, Facts, has_value, is_list, key_label, matching_rows, points
from backend.agent.chart_calculate.display import data_digits, format_value, make_display, strip_unit, unit_of
from backend.agent.chart_calculate.select import ITEM_COL, MISSING_TEXT, VALUE_COL, to_number
from backend.schemas.answer import AnswerTable
from backend.schemas.chart import CalcInput, CalcResult
from backend.schemas.record import Record

SUMMARY_ID = "t_calc"
SHOW_INPUTS = 5          # 요약표 '입력값' 칸에 보여 줄 입력 수 (합계처럼 입력이 많은 계산)
TITLE_LEN = 60
HIGHLIGHT_FACTOR = 2     # 계산에 쓴 행(강조 행)은 max_rows 의 몇 배까지 보여 줄지 (결정 D-5)


# ── 계산 요약표 ──────────────────────────────────────────────────
def _unique(seq: list[str]) -> list[str]:
    return list(dict.fromkeys(s for s in seq if s))


def _basis(f: Facts, r: CalcResult) -> str:
    labels = _unique([key_label(i.key) for i in r.inputs])
    return (" → " if r.op in BETWEEN_OPS else ", ").join(labels)


def _inputs_cell(f: Facts, r: CalcResult) -> tuple[str, list[Any]]:
    shown = r.inputs[:SHOW_INPUTS]
    texts = [f.fmt_input(i) for i in shown]
    if len({strip_unit(i.item or "") for i in r.inputs}) > 1:           # 항목이 다르면 이름을 붙인다 (diff · ratio …)
        texts = [f"{strip_unit(i.item or '')} {t}".strip() for i, t in zip(shown, texts)]
        text = " / ".join(texts)
    else:
        text = (" → " if r.op in BETWEEN_OPS else ", ").join(texts)
    if len(r.inputs) > SHOW_INPUTS:
        text += f" … 외 {len(r.inputs) - SHOW_INPUTS}개"
    return text, [i.value for i in r.inputs]


def build_summary(f: Facts) -> AnswerTable | None:
    scalars = [r for r in f.req.calc_results if not is_list(r)]
    if not scalars:
        return None
    rows, raw = [], []
    for r in scalars:
        pts = points(r)
        value = pts[0]["value"] if pts else None
        shown = f.fmt_result(r, value) if pts else "계산 불가"
        inputs_text, inputs_raw = _inputs_cell(f, r)
        den = f.denominator(r)
        note = "; ".join(x for x in ((f"분모: {den}" if den else None), humanize(r.note, r.inputs)) if x)
        name = " ".join(x for x in (f.fixed_text(r), f.label(r)) if x)
        rows.append([name, _basis(f, r), inputs_text, shown, note])
        raw.append([name, _basis(f, r), inputs_raw, value, note])
    return AnswerTable(table_id=SUMMARY_ID, kind="calc_summary", title="계산 요약",
                       columns=["계산", "기준", "입력값", "결과", "비고"], rows=rows, raw_rows=raw,
                       record_ids=_unique([rid for r in scalars for rid in r.record_ids]),
                       step_ids=[r.step_id for r in scalars], total_rows=len(rows))


# ── 목록형 계산표 (순위 · 시점별 값 …) ────────────────────────────
def build_list(f: Facts, r: CalcResult, max_rows: int) -> AnswerTable | None:
    pts = points(r)
    if not has_value(r):
        return None            # 값이 전부 없는 목록은 표로 만들지 않는다 (caveats 가 알린다)
    key_cols = _unique([c for p in pts for c in (p.get("key") or {})])
    has_rank = any("rank" in p for p in pts)
    columns = (["순위"] if has_rank else []) + key_cols + ["값"]
    rows, raw = [], []
    for p in pts[:max_rows]:
        key = p.get("key") or {}
        head = [p.get("rank")] if has_rank else []
        cells = [key.get(c) for c in key_cols]
        raw.append([*head, *cells, p.get("value")])
        rows.append([*(None if h is None else str(h) for h in head), *(None if c is None else str(c) for c in cells),
                     f.fmt_result(r, p.get("value")) if p.get("value") is not None else "계산 불가"])
    return AnswerTable(table_id=f"t_{r.step_id}", kind="calc_list", title=" ".join(x for x in (f.fixed_text(r), f.label(r)) if x) + " 결과" + (f" (분모: {f.denominator(r)})" if f.denominator(r) else ""), columns=columns,
                       rows=rows, raw_rows=raw, record_ids=list(r.record_ids), step_ids=[r.step_id],
                       truncated=len(pts) > max_rows, total_rows=len(pts))


# ── 원본 View 표 ─────────────────────────────────────────────────
def highlighted_rows(f: Facts, rec: Record, inputs: list[CalcInput]) -> set[int]:
    """계산 입력(CalcInput)이 가리키는 View 행 번호 (facts.matching_rows). 피연산자의 select 로 좁혀 다른 지역의 같은 값 행은 뺀다"""
    return {k for inp in inputs if inp.record_id == rec.id for k in matching_rows(rec, inp, f.selects_of(inp))}


def _cell(v: Any) -> str | None:
    return None if v is None else str(v)


def _row_value(rec: Record, row: list, item_i: int | None, value_i: int, digits: dict[Any, int | None]) -> str | None:
    v = row[value_i]
    n = to_number(v)
    if n is None:
        return "-" if v is None or str(v).strip() in MISSING_TEXT else str(v)
    unit = unit_of(str(row[item_i]) if item_i is not None else None, rec.metadata.get("unit"))
    return format_value(n, make_display(unit, auto_digits=digits.get(row[item_i] if item_i is not None else None))) or "-"


def _item_digits(rec: Record, rows: list[list], item_i: int | None, value_i: int) -> dict[Any, int | None]:
    """[NEW 11-17] 항목마다 한 가지 자릿수: 그 항목의 값들 중 가장 긴 소수 자릿수 (최대 3).
    이전에는 값마다 따로 정해 한 열에 0.778명 · 0.72명 · 0.7명 · 1명이 섞였다 (자체 검토 A-7)"""
    values: dict[Any, list] = {}
    for row in rows:
        values.setdefault(row[item_i] if item_i is not None else None, []).append(to_number(row[value_i]))
    out = {}
    for item, vals in values.items():
        unit = unit_of(str(item) if item is not None else None, rec.metadata.get("unit"))
        out[item] = data_digits([v for v in vals if v is not None], unit)
    return out


def _title(rec: Record) -> str:
    lines = rec.lexical_text.strip().splitlines()
    return str(rec.metadata.get("survey_nm") or (lines[0] if lines else rec.id))[:TITLE_LEN]


def direct_rows(f: Facts, rec: Record) -> list[int]:
    """[NEW 11-16] 순위 · 극값 결과가 **직접 가리키는** 원본 행 (결과 점과 key · 값이 같은 입력의 행), 결과 점 순서대로.
    행 제한에 걸려도 1위의 근거 행은 빠지면 안 된다 (검수 4)"""
    out: list[int] = []
    for r in f.req.calc_results:
        if r.op not in ("rank", "extreme"):
            continue
        for p in points(r):
            inp = next((i for i in r.inputs if i.record_id == rec.id and i.key == p.get("key") and i.value == p.get("value")), None)
            for k in matching_rows(rec, inp, f.selects_of(inp)) if inp else []:
                if k not in out:
                    out.append(k)
    return out


def build_view(f: Facts, rec: Record, no: int, max_rows: int) -> AnswerTable:
    cols, rows = rec.table.columns, rec.table.rows
    all_inputs = [i for r in f.req.calc_results for i in r.inputs]
    hit = highlighted_rows(f, rec, all_inputs)
    if len(rows) <= max_rows:
        keep = list(range(len(rows)))
    else:
        # [CHANGED 11-16] 이전: 계산에 쓴 행은 제한과 관계없이 모두 — 시군구 순위(250행)면 표가 250행이 됐다. 이제 제한의 2배까지 (결정 D-5)
        direct = [k for k in direct_rows(f, rec) if k in hit]        # 순위 · 극값이 직접 가리키는 행을 먼저 (그 다음 계산에 쓴 행을 앞에서부터)
        shown = (direct + [k for k in sorted(hit) if k not in direct])[:max_rows * HIGHLIGHT_FACTOR]
        room = max(max_rows - len(shown), 0)
        extra = [k for k in range(len(rows)) if k not in hit][:room]
        keep = sorted(set(shown) | set(extra))
    item_i = cols.index(ITEM_COL) if ITEM_COL in cols else None
    value_i = cols.index(VALUE_COL) if VALUE_COL in cols else len(cols) - 1
    digits = _item_digits(rec, [rows[k] for k in keep], item_i, value_i)
    shown = [[_row_value(rec, rows[k], item_i, value_i, digits) if j == value_i else _cell(c) for j, c in enumerate(rows[k])]
             for k in keep]
    return AnswerTable(table_id=f"t_view_{no}", kind="view", title=_title(rec), columns=list(cols), rows=shown,
                       raw_rows=[list(rows[k]) for k in keep], record_ids=[rec.id],
                       highlight_rows=[j for j, k in enumerate(keep) if k in hit],
                       truncated=len(keep) < len(rows), total_rows=len(rows))


# ── 전체 ─────────────────────────────────────────────────────────
def build_tables(f: Facts) -> list[AnswerTable]:
    max_rows = f.req.max_rows
    tables: list[AnswerTable] = []
    if summary := build_summary(f):
        tables.append(summary)
    tables += [t for r in f.req.calc_results if is_list(r) and (t := build_list(f, r, max_rows))]

    by_id = {rec.id: rec for rec in f.req.records}
    ids = [rid for rid in used_record_ids(f) if rid in by_id] or list(by_id)      # 쓴 View 를 모르면 받은 View 전부
    tables += [build_view(f, by_id[rid], no, max_rows) for no, rid in enumerate(ids, 1)]
    return tables
