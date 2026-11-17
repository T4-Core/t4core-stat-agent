"""[NEW] tables.py · caveats.py — 계산 요약 · 목록 · 원본 View 표, 강조 행, 행 제한, 주의사항"""
from backend.agent.answer_compose.caveats import build_caveats
from backend.agent.answer_compose.facts import Facts
from backend.agent.answer_compose.tables import build_tables
from backend.schemas.chart import CalcResult
from tests.answer_compose._data import growth, request
from tests.chart_calculate._views import TRUNCATED, VID, view


def tables(**kw):
    return {t.table_id: t for t in build_tables(Facts(request(**kw)))}


def test_summary_view_order_and_texts():
    ts = build_tables(Facts(request()))
    assert [(t.table_id, t.kind) for t in ts] == [("t_calc", "calc_summary"), ("t_view_1", "view")]
    s = ts[0]
    assert s.columns == ["계산", "기준", "입력값", "결과", "비고"]
    assert s.rows == [["전국 혼인건수 증감률", "2021 → 2025", "192,507건 → 240,326건", "24.8%", ""]]
    assert s.raw_rows[0][2:4] == [[192507, 240326], 24.84013568337775] and s.step_ids == ["a1"]


def test_view_table_highlights_rows_used_by_calculation():
    v = tables()["t_view_1"]
    used = [v.raw_rows[i][:3] for i in v.highlight_rows]
    assert used == [["2021", "전국", "혼인건수(건)"], ["2025", "전국", "혼인건수(건)"]]    # 출생아수·조혼인율 행은 강조하지 않는다
    assert v.rows[0] == ["2021", "전국", "혼인건수(건)", "192,507건"] and v.record_ids == [VID]
    assert (v.truncated, v.total_rows) == (False, len(v.rows))
    assert v.raw_rows[-1][3] is None and v.rows[-1][3] == "-"                       # 결측 행


def test_view_table_keeps_highlighted_rows_when_truncated():
    rows = [[str(y), "전국", "혼인건수(건)", float(y)] for y in range(1990, 2030)]
    r = growth().model_copy(update={"inputs": [
        growth().inputs[0].model_copy(update={"key": {"시점": "2028"}, "value": 2028.0}),
        growth().inputs[1].model_copy(update={"key": {"시점": "2029"}, "value": 2029.0})]})
    v = tables(records=[view(rows=rows)], results=[r], max_rows=5)["t_view_1"]
    assert (v.truncated, v.total_rows, len(v.rows)) == (True, 40, 5)
    assert [v.raw_rows[i][0] for i in v.highlight_rows] == ["2028", "2029"]          # 5행 제한 밖이어도 포함
    assert [x[0] for x in v.raw_rows[:3]] == ["1990", "1991", "1992"]               # 남는 자리는 앞쪽 행


def test_list_result_gets_own_table_with_rank():
    r = CalcResult.model_validate({
        "step_id": "a3", "op": "rank", "unit": "건", "display_ref": "d2", "record_ids": [VID],
        "value": [{"key": {"시점": "2025"}, "value": 240326, "rank": 1}, {"key": {"시점": "2024"}, "value": 222412, "rank": 2}]})
    t = tables(results=[r])
    assert "t_calc" not in t                                   # 스칼라 계산이 없으면 요약표도 없다
    assert t["t_a3"].columns == ["순위", "시점", "값"]
    assert t["t_a3"].rows == [["1", "2025", "240,326건"], ["2", "2024", "222,412건"]]
    assert t["t_a3"].raw_rows[0] == [1, "2025", 240326]


def test_failed_calculation_in_summary_and_caveats():
    bad = growth(step_id="a2", value=None).model_copy(update={"note": "기준값 0"})
    f = Facts(request(results=[growth(), bad]))
    s = {t.table_id: t for t in build_tables(f)}["t_calc"]
    assert [r[3] for r in s.rows] == ["24.8%", "계산 불가"] and s.rows[1][4] == "기준 값이 0이라 비율을 계산할 수 없습니다"
    assert [(c.source, c.ref) for c in build_caveats(f)] == [("calc_note", "a2")]
    assert "계산하지 못했습니다: 기준 값이 0이라 비율을 계산할 수 없습니다" in build_caveats(f)[0].text


def test_caveats_from_view_notes_deduplicated_and_missing_view():
    note = {"slot": "시점", "type": "latest_shift", "requested": [2026], "applied": [2025], "text": "2026년 자료가 없어 2025년으로 대체"}
    f = Facts(request(records=[view(notes=[note, note])]))
    assert [c.text for c in build_caveats(f)] == ["2026년 자료가 없어 2025년으로 대체"]
    gone = Facts(request(records=[]))
    assert [c.source for c in build_caveats(gone)] == ["view_missing"]
    assert [t.kind for t in build_tables(gone)] == ["calc_summary"]                 # View 가 없으면 원본 표만 빠진다


def test_truncated_view_note_is_a_caveat():
    f = Facts(request(records=[view(notes=[TRUNCATED])]))
    assert "행이 2000개를 넘어" in build_caveats(f)[0].text
