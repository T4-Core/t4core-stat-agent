"""일상어 사전 캐내기 · 개념 카탈로그 · dev/heldout 나누기 (저장소 없이)"""
import json

from backend.rag.search.tuning import colloq_mine as M
from backend.rag.search.concepts import build
from backend.rag.search.tuning.splits import split_of


def _rec(i, o, p, gold, groups=None, alts=None):
    return {"dataset_id": f"SG-{i:04d}", "answerability_type": "ANSWERABLE", "question_original": o,
            "question_paraphrased": p, "retrieval_eval": {"golden_table_ids": [f"101_{g}" for g in gold],
                                                          "required_evidence_groups": groups or {}}}


def test_split_is_stable_and_about_20_percent():
    ids = [f"SG-{i:05d}" for i in range(2000)]
    s = [split_of(x) for x in ids]
    assert s == [split_of(x) for x in ids]
    assert 0.15 < s.count("heldout") / len(s) < 0.25


def test_mine_pairs_from_dev_only(tmp_path):
    dev = [i for i in range(400) if split_of(f"SG-{i:04d}") == "dev"][:3]
    held = next(i for i in range(400) if split_of(f"SG-{i:04d}") == "heldout")
    recs = [_rec(i, "2020년 시도별 초혼 건수", "2020년에 한 번 결혼했던 사람 수", ["DT_A"]) for i in dev]
    recs.append(_rec(held, "2021년 시도별 재혼 건수", "2021년에 다시 결혼한 사람 수", ["DT_B"]))
    g = tmp_path / "g.jsonl"
    g.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs), encoding="utf-8")
    rows = M.load_records(g)
    titles = {"DT_A": "시도/초혼연령별 혼인", "DT_B": "시도/재혼연령별 혼인"}
    cands, n_dev = M.mine(rows, titles)
    assert n_dev == 3
    pairs = {(c["colloquial"], c["term"]) for c in cands}
    assert ("결혼했던", "초혼") in pairs, cands
    assert not any(c["term"] == "재혼" for c in cands)                  # heldout 레코드는 캐내지 않음
    assert "결혼했던" in M.to_yaml(cands)
    cov = M.coverage(rows, titles, None, "heldout")
    assert cov["n"] == 1


def test_concepts_from_alt_dev_only(tmp_path):
    dev = [i for i in range(400) if split_of(f"SG-{i:04d}") == "dev"][:2]
    held = next(i for i in range(400) if split_of(f"SG-{i:04d}") == "heldout")
    alt = tmp_path / "alt.jsonl"
    lines = [{"dataset_id": f"SG-{dev[0]:04d}", "gold_tables": ["DT_A"],
              "groups": {"R1": {"alternatives": [{"tbl_id": "DT_A2", "match": "exact"}, {"tbl_id": "DT_X", "match": "rounded"}]}}},
             {"dataset_id": f"SG-{dev[1]:04d}", "gold_tables": ["DT_A2"],
              "groups": {"R1": {"alternatives": [{"tbl_id": "DT_A3", "match": "exact"}]}}},
             {"dataset_id": f"SG-{held:04d}", "gold_tables": ["DT_B"],
              "groups": {"R1": {"alternatives": [{"tbl_id": "DT_B2", "match": "exact"}]}}}]
    alt.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    d = build([alt])
    assert [c["tables"] for c in d["concepts"]] == [["DT_A", "DT_A2", "DT_A3"]], d   # 이어진 묶음 · rounded 빼고 · heldout 빼고
    d2 = build([alt], include_rounded=True, splits=None)
    assert sorted(len(c["tables"]) for c in d2["concepts"]) == [2, 4]


def test_compare_split_filter(tmp_path):
    from backend.rag.search.tuning.compare import load_golden
    recs = [_rec(i, f"질문 {i}", f"일상 {i}", ["DT_A"]) for i in range(60)]
    g = tmp_path / "g.jsonl"
    g.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs), encoding="utf-8")
    held = load_golden(g, split=["heldout"])
    assert held and all(r["split"] == "heldout" for r in held)
    assert len(held) + len(load_golden(g, split=["dev"])) == len(load_golden(g))
