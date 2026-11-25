import csv
import json

from backend.rag.search.tuning import value_eval as v


def fact(period="2024년", region="서울특별시", value="1,000", unit="명", item="인구"):
    return {"period": period, "item": item, "labels": {"행정구역별": region}, "value": value, "unit": unit}


def cell(entry):
    return v.make_cell(**entry)


def test_direct_requires_same_coordinate_value_and_unit():
    target = v.parse_gold({"expected_values": [fact()]}, {"raw": 1000, "unit": "명"}, "SIMPLE_LOOKUP")
    wrong = [
        cell(fact(period="2023년")), cell(fact(region="부산광역시")), cell(fact(item="출생")),
        cell(fact(unit="가구")), cell(fact(value="999")),
    ]
    assert v.evaluate_cells(target, [v.ViewValues(wrong)]) == ("mismatch", 0)
    assert v.evaluate_cells(target, [v.ViewValues([cell(fact(value="1", unit="천명"))])]) == ("match", 1)
    assert v.evaluate_cells(target, [v.ViewValues([cell(fact(region="서울특별시 읍부"))])]) == ("mismatch", 0)


def test_derived_needs_all_input_coordinates_across_views():
    first, second = fact(), fact(period="2023년", value="900")
    target = v.parse_gold({"expected_values": [first, second]}, {"raw": 100, "unit": "명"}, "TIME_SERIES_COMPARISON")
    assert v.evaluate_cells(target, [v.ViewValues([cell(fact(value="100")), cell(first)])]) == ("mismatch", 1)
    assert v.evaluate_cells(target, [v.ViewValues([cell(first)]), v.ViewValues([cell(second)])]) == ("match", 2)


def test_missing_and_mismatched_values_are_separate():
    target = v.parse_gold({"expected_values": [fact()]}, {"raw": 1000, "unit": "명"}, "SIMPLE_LOOKUP")
    assert v.evaluate_cells(target, [v.ViewValues([])]) == ("no_value", 0)
    assert v.evaluate_cells(target, [v.ViewValues([], "view_error")]) == ("view_error", 0)
    assert v.evaluate_cells(target, [v.ViewValues([], "incomplete_view")]) == ("incomplete_view", 0)
    assert v.evaluate_cells(target, []) == ("no_candidates", 0)
    assert v.make_cell("2024", "인구", {}, "NaN", "명") is None
    assert v.parse_gold({"expected_values": [fact()]}, {"raw": 1001, "unit": "명"}, "SIMPLE_LOOKUP").kind == "gold_value_conflict"


def test_csv_and_jsonl_gold_share_lookup_values(tmp_path):
    m2 = {"expected_values": [fact()]}
    numeric = {"exact_decimal": "1000", "unit": "명"}
    csv_path, json_path = tmp_path / "refs.csv", tmp_path / "gold.jsonl"
    columns = ["id", "answerability", "module_eval", "numeric_ground_truth", "executed_formula"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerow(["q-O", "ANSWERABLE", json.dumps({"M2": m2}), json.dumps(numeric), "s1: A = 1000명 = 1000명"])
    row = {"dataset_id": "q", "answerability_type": "ANSWERABLE", "reasoning_type": "SIMPLE_LOOKUP",
           "question_ids": {"original": "q-O"}, "generation_eval": {"exact_numeric_ground_truth": numeric},
           "module_eval": {"M2": m2}}
    json_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert v.load_gold(csv_path) == v.load_gold(json_path)


def test_view_csv_preserves_unit_per_cell(tmp_path):
    p = tmp_path / "view.csv"
    p.write_text("시점,항목,값,단위,부호\n2024,인구,1,천명,\n2024,가구,2,가구,\n2024,주택,-,호,\n", encoding="utf-8")
    assert [(c.value, c.unit) for c in v.read_view(p)] == [(1, "천명"), (2, "가구")]


def test_replays_only_selected_units_and_uses_filters():
    class Pipe:
        def search(self, query, filters, top_k, *, question, unit):
            by_unit = {"main": ["M", "M2"], "sub": ["A", "B", "C", "D"]}
            return {"hits": [{"tbl_id": t} for t in by_unit[unit][:top_k]]}
    base = {"question": "인구", "top1": "M", "top5": "M A M2 B C"}
    units = [
        {"unit": "main", "text": "본", "search_query": "본", "filters": {"시점": [2024]}, "status": "ok"},
        {"unit": "sub", "text": "하위", "search_query": "하위", "filters": {"시점": [2023]}, "status": "ok"},
    ]
    seen = []

    def fetch(tid, filters):
        seen.append((tid, filters["시점"][0]))
        return v.ViewValues([])

    _, app_views = v.candidate_views(base, units, Pipe(), {"n_rec": 3, "main_with_subs": False}, 10, fetch)
    assert len(app_views) == 3 and seen == [("M", 2024), ("A", 2023), ("B", 2023), ("C", 2023)]
    seen.clear()
    _, app_views = v.candidate_views({**base, "top5": "M X"}, units, Pipe(), {"n_rec": 3, "main_with_subs": False}, 10, fetch)
    assert len(app_views) == 1 and app_views[0].reason == "ranking_changed"
