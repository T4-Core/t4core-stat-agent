"""[NEW 11-12] 1-5 서브쿼리 분리 정책 · 문장 · 지역 칸 바로잡기 (CSV 색인·HCX 없음: 접지 결과를 직접 만듦)"""
from types import SimpleNamespace

from backend.core.settings_v4 import QueryV4Settings
from backend.rag.query_analyzer.v4.decompose import _numeric, concepts, decompose, time_text
from backend.rag.query_analyzer.v4.pipeline import fix_region_slots

YEARS = [f"{y}년" for y in range(2021, 2026)]
COMMON = ["DT_1B8000F", "DT_1B8000G"]


def _sv(raw, tables, grounded=True):
    return {"raw": raw, "value": raw, "source": "csv" if grounded else "llm", "match": "exact", "grounded": grounded,
            "n_tables": len(tables), "tables": tables, "csv": [], "candidates": [], "note": ""}


def _grounded(extra_indicators=(), region=("전국",)):
    g = {"지표": [_sv("혼인건수(건)", COMMON + ["DT_1BB0001"]), _sv("출생아수(명)", COMMON + ["DT_1BB0005"]),
                  _sv("사망자수(명)", COMMON + ["DT_1BB0007"])],
         "지역": [_sv(r, ["DT_X"]) for r in region]}
    g["지표"] = [_sv(v, ["DT_1JA1607"]) for v in extra_indicators] + g["지표"]
    return g


RAW = {"시점": YEARS, "지역": ["전국"], "지표": ["혼인건수(건)", "출생아수(명)", "사망자수(명)"]}


def test_time_text_and_numeric():
    assert time_text(YEARS) == "2021~2025년"
    assert time_text(["2020년", "2023년"]) == "2020년 2023년"
    assert time_text(["2025년"]) == "2025년"
    assert _numeric("2021") and _numeric("2021년") and not _numeric("출생아수(명)")


def test_policy_no_common_table_keeps_one():
    s = QueryV4Settings(split_policy="no_common_table")
    subs, reason = decompose(_grounded(), RAW, [], ["추이"], [], None, s)
    assert subs == [] and "함께 가진 표 2개" in reason


def test_policy_always_splits_per_indicator():
    s = QueryV4Settings(split_policy="always")
    subs, reason = decompose(_grounded(), RAW, [], ["추이"], [], None, s)
    assert [x["slots"]["지표"] for x in subs] == [["혼인건수(건)"], ["출생아수(명)"], ["사망자수(명)"]]
    assert [x["text"] for x in subs] == ["2021~2025년 전국 혼인건수(건)", "2021~2025년 전국 출생아수(명)",
                                         "2021~2025년 전국 사망자수(명)"]
    assert all(x["slots"]["시점"] == YEARS and x["intent"] == "추이" for x in subs)
    assert subs[0]["candidate_tables"][:2] == COMMON                       # 함께 가진 표가 앞
    assert "분리 정책 always" in reason and "3개로 나눔" in reason


def test_numbers_are_not_concepts_and_cut_is_reported():
    g = _grounded(extra_indicators=["2021", "2025"])
    assert [c["name"] for c in concepts(g)] == ["혼인건수(건)", "출생아수(명)", "사망자수(명)"]
    s = QueryV4Settings(split_policy="always", max_sub_queries=2)
    subs, reason = decompose(g, RAW, [], ["추이"], [], None, s)
    assert len(subs) == 2 and "빠짐: ['사망자수(명)']" in reason


def test_ungrounded_region_value_left_out_of_text():
    g = _grounded()
    g["지역"] = [_sv("혼인건수", [], grounded=False)]
    raw = {**RAW, "지역": ["혼인건수"]}
    subs, _ = decompose(g, raw, [], ["추이"], [], None, QueryV4Settings(split_policy="always"))
    assert subs[0]["text"] == "2021~2025년 혼인건수(건)"


class _Lex:
    """lex.best(text, slot) 만 흉내: 지역 이름은 지역으로, 지표 이름은 지표로 접지"""
    REGIONS, INDICATORS = {"전국", "서울특별시", "강남구"}, {"혼인건수", "출생아수", "사망자수"}

    def best(self, text, slot=None):
        ok = text in (self.REGIONS if slot in ("지역", "전출지", "전입지") else self.INDICATORS)
        return SimpleNamespace(grounded=ok, source="csv") if ok else None


def test_fix_region_slots_moves_indicators():
    raw = {"시점": YEARS, "지역": ["혼인건수", "출생아수", "사망자수", "강남구"], "전출지": ["추이"]}
    out, moved = fix_region_slots(raw, _Lex())
    assert out["지역"] == ["강남구"] and out["지표"] == ["혼인건수", "출생아수", "사망자수"]
    assert out["전출지"] == ["추이"]                                        # 지표로도 근거가 없으면 그대로 (문장에서는 빠짐)
    assert [v for _, v in moved] == ["혼인건수", "출생아수", "사망자수"]
