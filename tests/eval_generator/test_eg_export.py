"""결과 정리본 내보내기 (HCX · Chrome 없음)"""
import gzip
import json
from pathlib import Path

import pytest

from eval.generator import export as E


def _run(rid, answer="답변", drawn=None, render_status=None, caveats=None):
    return {"id": rid, "run": 1, "question": f"{rid} 질문 <b>&</b>", "result": {"answer": answer, "caveats": caveats or []},
            "modules": {"drawn": drawn or [], "render_status": render_status or {}}}


def _write(tmp_path, runs, verdicts):
    d = tmp_path / "r"
    (d / "runs_report").mkdir(parents=True)
    with gzip.open(d / "runs.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in runs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (d / "runs_report" / "verdicts.jsonl").write_text(
        "\n".join(json.dumps(v, ensure_ascii=False) for v in verdicts) + "\n", encoding="utf-8")
    ds = tmp_path / "ds"
    ds.mkdir()
    (ds / "cases.json").write_text(json.dumps({"name": "demo", "version": "1", "cases": []}), encoding="utf-8")
    return d / "runs.jsonl.gz", ds


FIG = {"data": [{"type": "bar", "x": ["a", "b"], "y": [1, 2]}], "layout": {}}


def test_charts_of_orders_merged_last_and_adds_unrendered():
    r = _run("X-A", drawn=[
        {"chart_id": "c1+c2", "chart_type": "line", "status": "drawn", "merged_from": ["c1", "c2"], "figure": FIG},
        {"chart_id": "c2", "chart_type": "line", "status": "drawn", "merged_from": [], "figure": FIG},
        {"chart_id": "c1", "chart_type": "line", "status": "drawn", "merged_from": [], "figure": FIG}],
        render_status={"c3": {"state": "skipped", "reason": "no_chart_content"}, "c1": {"state": "drawn"}})
    cs = E.charts_of(r)
    assert [c.chart_id for c in cs] == ["c1", "c2", "c3", "c1+c2"]
    assert cs[2].status == "skipped" and cs[2].reason == "no_chart_content" and cs[2].figure is None


def test_load_items_sorted_with_verdicts_and_first_run_only(tmp_path):
    runs, ds = _write(tmp_path,
                      [_run("B-V", caveats=[{"text": "주의1"}, "주의2"]), _run("A-H"), {**_run("B-V", answer="2회차"), "run": 2}],
                      [{"id": "A-H", "verdict": "보류", "group": "boundary", "first_failure": ["M3"], "tags": ["no_viewset", "x"]},
                       {"id": "B-V", "verdict": "통과", "group": "chart", "first_failure": [], "tags": []}])
    items = E.load_items(runs, ds)
    assert [i.id for i in items] == ["A-H", "B-V"]
    assert items[0].verdict == "보류" and items[0].tags == ["x"] and items[0].first_failure == ["M3"]
    assert items[1].answer == "답변" and items[1].caveats == ["주의1", "주의2"]
    assert E.load_items(runs, ds, limit=1)[0].id == "A-H"


def test_missing_verdict_is_marked(tmp_path):
    runs, ds = _write(tmp_path, [_run("A-V")], [])
    assert E.load_items(runs, ds)[0].verdict == "판정 없음"


def _item(**kw):
    base = dict(dataset="demo", version="1", id="A-V", group="chart", verdict="통과", first_failure=[], tags=[],
                question="질문 <script>x</script> & 끝", answer="줄1\n\n\n줄2 <i>", caveats=[], charts=[])
    return E.Item(**{**base, **kw})


def test_html_escapes_and_compacts_blank_lines():
    h = E.build_html([("demo", "1", [_item()])], "제목")
    assert "<script>" not in h and "&lt;script&gt;x&lt;/script&gt; &amp; 끝" in h
    assert "줄1\n줄2 &lt;i&gt;" in h                                   # 연속 빈 줄은 한 줄로
    assert "class='badge ok'" in h


def test_md_has_blocks_links_and_quotes():
    c = E.Chart("c1", "bar", "drawn", "제목", figure=FIG, png="assets/demo/A-V_c1.png", small="assets/demo/A-V_c1_s.png",
                caption="답변 차트 · c1 · 하위 질문 1")
    miss = E.Chart("c2", None, "skipped", reason="no_chart_content", caption="답변 차트 · c2")
    md = E.build_md([("demo", "1", [_item(charts=[c, miss], verdict="보류", first_failure=["M3"], tags=["t1"])])], "T")
    assert "### A-V · chart · 보류" in md and "First Failure: M3" in md and "태그: t1" in md
    assert "**답변 차트 · c1 · 하위 질문 1**" in md and "![답변 차트 · c1 · 하위 질문 1](assets/demo/A-V_c1.png)" in md
    assert "- 답변 차트 · c2: 없음 (skipped, no_chart_content)" in md
    assert "> 줄1\n>\n>\n> 줄2" in md or "> 줄1" in md


def test_html_uses_small_images_and_notes_missing_chart():
    c = E.Chart("c1", "bar", "drawn", figure=FIG, png="a/x.png", small="a/x_s.png", caption="답변 차트 · c1")
    g = E.Chart("golden", "bar", "drawn", figure=FIG, png="a/g.png", small="a/g_s.png", source="golden", caption="골든 차트 (정답 기준 · bar)")
    miss = E.Chart("c2", None, "skipped", reason="no_chart_content", caption="답변 차트 · c2")
    h = E.build_html([("demo", "1", [_item(charts=[g, c, miss])])], "T")
    assert "src='a/x_s.png'" in h and "x.png'" not in h.replace("x_s.png", "")
    assert "<div class='cap gold'>골든 차트 (정답 기준 · bar)</div>" in h and "<div class='cap gen'>답변 차트 · c1</div>" in h
    assert "답변 차트 · c2</span> 없음: no_chart_content" in h


def test_summary_counts():
    s = E._summary([_item(), _item(verdict="보류"), _item(verdict="미달", charts=[E.Chart("c1", "bar", "drawn", figure=FIG)])])
    assert "문항 3" in s and "통과 1" in s and "보류 1" in s and "미달 1" in s and "답변 차트 1" in s and "골든 차트 0" in s


def test_safe_file_names():
    assert E._safe("c1+c2") == "c1_c2" and E._safe("G0007-A") == "G0007-A"


def test_render_png_small_figure(tmp_path):
    pytest.importorskip("kaleido")
    it = _item(charts=[E.Chart("c1", "bar", "drawn", figure=FIG), E.Chart("c2", None, "skipped")])
    try:
        stat = E.render_pngs([it], tmp_path, workers=1)
    except Exception as e:  # noqa: BLE001  (kaleido 는 Chrome 이 있어야 돈다. 없는 환경에서는 건너뛴다)
        pytest.skip(f"kaleido 렌더 불가: {type(e).__name__}")
    assert stat["rendered"] == 1 and stat["failed"] == 0
    c = it.charts[0]
    assert (tmp_path / c.png).exists() and (tmp_path / c.small).exists() and it.charts[1].png is None
    assert Path(tmp_path / c.small).stat().st_size < Path(tmp_path / c.png).stat().st_size


# ── 골든 차트 ─────────────────────────────────────────────────────
GOLD = {"should_render": True, "chart_type": "line", "x_axis": "시점", "y_axis": "상륙허가자", "unit": "명",
        "points": [{"label": "2021", "value": "860859"}, {"label": "2022", "value": "1003085"}]}


@pytest.mark.parametrize("kind,cls", [("line", "scatter"), ("bar", "bar"), ("donut", "pie")])
def test_golden_figure_types(kind, cls):
    fig = E.golden_figure({**GOLD, "chart_type": kind})
    assert fig["data"][0]["type"] == cls and fig["data"][0].get("y", fig["data"][0].get("values")) == [860859.0, 1003085.0]
    assert fig["layout"]["title"]["text"].startswith("골든 차트: 상륙허가자")


def test_golden_figure_unrenderable():
    assert E.golden_figure({**GOLD, "chart_type": "radar"}) is None and E.golden_figure({**GOLD, "points": []}) is None


def _charts_dir(tmp_path, name, spec):
    d = tmp_path / "charts"
    d.mkdir(exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")


def test_golden_chart_from_dataset(tmp_path):
    _charts_dir(tmp_path, "X-V", GOLD)
    _charts_dir(tmp_path, "X-H", {"should_render": False, "reason": "2025 원본 셀이 입력에서 누락", "allowed_partial": True,
                                  "partial_rules": "확인된 점만 사용"})
    g = E.golden_chart(tmp_path, "X-V")
    assert (g.source, g.status, g.caption) == ("golden", "drawn", "골든 차트 (정답 기준 · line)") and g.figure
    h = E.golden_chart(tmp_path, "X-H")
    assert h.status == "none" and h.figure is None and "누락" in h.reason and "부분 차트 허용: 확인된 점만 사용" in h.reason
    assert E.golden_chart(tmp_path, "NOPE").status == "none"


def test_load_items_puts_golden_first_and_captions_generator_charts(tmp_path):
    drawn = [{"chart_id": "c2", "chart_type": "line", "status": "drawn", "merged_from": [], "figure": FIG},
             {"chart_id": "c1+c2", "chart_type": "line", "status": "drawn", "merged_from": ["c1", "c2"], "figure": FIG},
             {"chart_id": "c1", "chart_type": "line", "status": "drawn", "merged_from": [], "figure": FIG}]
    r = _run("X-A", drawn=drawn)
    r["modules"]["charts"] = [{"chart_id": "c1", "sub_question_ids": ["X-A-1"]}, {"chart_id": "c2", "sub_question_ids": ["X-A-2"]}]
    runs, ds = _write(tmp_path, [r], [{"id": "X-A", "verdict": "통과", "group": "calculation_chart"}])
    _charts_dir(ds, "X-A", GOLD)
    it = E.load_items(runs, ds)[0]
    assert [c.chart_id for c in it.charts] == ["golden", "c1", "c2", "c1+c2"]
    assert [c.caption for c in it.charts[1:]] == ["답변 차트 · c1 · 하위 질문 1", "답변 차트 · c2 · 하위 질문 2", "답변 차트 · c1+c2 (두 차트 겹침)"]
