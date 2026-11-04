"""[NEW] 답변 문맥 고르기 (light_agent.pick_context): groups 없으면 예전과 같음 / 있으면 하위 질의마다 최소 1개"""
from backend.agent.light_agent import pick_context


def _r(i, tbl, rows=True):
    return {"id": i, "source": {"tbl_id": tbl}, "table": {"rows": [[1]] if rows else []}}


def test_default_is_unchanged():
    recs = [_r("a", "T1", False), _r("b", "T2"), _r("c", "T3"), _r("d", "T4"), _r("e", "T5")]
    notes = {"c": ["x"]}
    assert [r["id"] for r in pick_context(recs, notes)] == ["b", "d", "e", "c"]     # 값 있는 View → 메모 적은 순 → 빈 View


def test_each_group_gets_one():
    # main 의 비슷한 표 3개가 앞자리를 차지해도 S2 의 표가 들어감, 같은 예비 표(T9)는 한 번만
    recs = [_r("m1", "T1"), _r("m2", "T2"), _r("m3", "T3"), _r("s1", "T9"), _r("s2a", "T5"), _r("s2b", "T9")]
    groups = {"m1": "main", "m2": "main", "m3": "main", "s1": "S1", "s2a": "S2", "s2b": "S2"}
    got = [r["id"] for r in pick_context(recs, {}, groups)]
    assert got[:3] == ["m1", "s1", "s2a"] and len(got) == 4 and "s2b" not in got, got


def test_many_groups_extend_to_k_max():
    recs = [_r(f"s{i}", f"T{i}") for i in range(8)]
    groups = {r["id"]: r["id"] for r in recs}
    assert len(pick_context(recs, {}, groups)) == 6
