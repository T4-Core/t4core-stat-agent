"""Chart-Data Fidelity: 차트 유형별 extractor"""
import copy
import json

import pytest

from backend.agent.draw_chart import run_module5
from backend.agent.draw_chart.draw_chart_module.draw_chart_samples import SAMPLE_CONTENTS, SAMPLE_DISPLAYS, sample_plan
from eval.generator.chart_extract import SUPPORTED, compare


@pytest.fixture(scope="module")
def drawn():
    contents = [c.model_dump(mode="json") if hasattr(c, "model_dump") else copy.deepcopy(c) for c in SAMPLE_CONTENTS]
    displays = {k: v.model_dump(mode="json") for k, v in SAMPLE_DISPLAYS.items()}
    m3 = {"query_id": "samples", "chart_plan": {"plans": []}, "chart_contents": contents, "calc_results": [], "displays": displays,
          "validation": {}}
    out = run_module5(chart_plan=sample_plan(), module3_output=m3, save=False)
    figs = {r.chart_id: {"chart_id": r.chart_id, "figure": json.loads(r.figure.to_json()), "merged_from": []}
            for r in out["results"] if r.figure is not None}
    return {c["chart_id"]: c for c in contents}, displays, figs


def test_all_sample_types_match(drawn):
    contents, displays, figs = drawn
    types = set()
    for cid, c in contents.items():
        f = compare(c, displays, figs[cid])
        assert f.status == "ok", (c["chart_type"], f.missing[:3], f.extra[:3], f.diff[:3])
        types.add(c["chart_type"])
    assert types == SUPPORTED                                          # 15종 모두


def _by_type(drawn, t):
    contents, displays, figs = drawn
    cid = next(k for k, c in contents.items() if c["chart_type"] == t)
    return copy.deepcopy(contents[cid]), displays, figs[cid]


def test_heatmap_single_cell_change_detected(drawn):
    c, d, fig = _by_type(drawn, "heatmap")
    vi = c["columns"].index(c["encoding"]["value"])
    c["rows"][0][vi] = (c["rows"][0][vi] or 0) + 1
    f = compare(c, d, fig)
    assert f.status == "mismatch" and len(f.diff) == 1


def test_unit_scale_is_reversed_not_rounded(drawn):
    """figure 값은 v / unit_scale (반올림 없음). 표시 자릿수 허용오차를 쓰지 않으므로 1 원단위 차이도 잡힌다"""
    for t in ("line", "bar", "pie"):
        c, d, fig = _by_type(drawn, t)
        enc = c["encoding"]
        vi = c["columns"].index(enc.get("y") or enc.get("value"))
        c["rows"][0][vi] = c["rows"][0][vi] + 1
        assert compare(c, d, fig).status == "mismatch", t


def test_pyramid_sign_removed(drawn):
    c, d, fig = _by_type(drawn, "pyramid")
    assert compare(c, d, fig).status == "ok"
    xs = fig["figure"]["data"][0]["x"]
    assert any(v is not None and v < 0 for v in (xs if isinstance(xs, list) else []))  # 첫 group 은 음수로 그려진다


def test_scatter_label_swap_detected(drawn):
    """서울 · 부산의 좌표는 그대로 두고 레이블만 맞바꾸면 불일치"""
    for t in ("scatter", "bubble"):
        c, d, fig = _by_type(drawn, t)
        li = c["columns"].index(c["encoding"]["label"])
        c["rows"][0][li], c["rows"][1][li] = c["rows"][1][li], c["rows"][0][li]
        assert compare(c, d, fig).status == "mismatch", t


def test_bubble_size_swap_detected(drawn):
    c, d, fig = _by_type(drawn, "bubble")
    si = c["columns"].index(c["encoding"]["size"])
    c["rows"][0][si], c["rows"][1][si] = c["rows"][1][si], c["rows"][0][si]
    assert compare(c, d, fig).status == "mismatch"


def test_radar_closing_point_removed(drawn):
    c, d, fig = _by_type(drawn, "radar")
    tr = fig["figure"]["data"][0]
    assert tr["theta"][0] == tr["theta"][-1]
    assert compare(c, d, fig).status == "ok"


def test_overlay_is_unsupported(drawn):
    c, d, fig = _by_type(drawn, "line")
    assert compare(c, d, {**fig, "merged_from": ["c1", "c2"]}).status == "unsupported"
