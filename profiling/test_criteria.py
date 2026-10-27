"""criteria.py 채점기 회귀 시험 (LLM 호출 없음). 합성 답변으로 오판 사례를 고정한다.

실행: .venv/Scripts/python.exe -m profiling.test_criteria   (t4core-stat-agent 폴더에서)
골든셋 정답은 golden/golden_set.built.jsonl 을 읽으므로 build_gold.py 를 먼저 실행해 둬야 한다.
"""
import json

from profiling import config
from profiling import criteria as cr
from profiling import e2e_eval as ev

BUILT = config.PROFILING_DIR / "golden" / "golden_set.built.jsonl"
G = {x["qid"]: x for x in map(json.loads, BUILT.open(encoding="utf-8"))}


def c4(qid, answer):
    return cr.c4(G[qid], {"answer": answer})["items"]


def passed(qid, answer, *keys):
    items = c4(qid, answer)
    return all(items[k] is True for k in keys or items)


# ── 숫자 해석 ───────────────────────────────────────────────
def test_man_unit_is_one_value():
    # GPT 지적 4: 988만 1,726 의 조각 1,726 을 따로 오답으로 세면 안 된다
    g = {"question": "가구 수?", "type": "lookup", "gold_value": 9881726, "tolerance": 0}
    out = cr.c5(g, {"answer": "988만 1,726가구입니다"}, {"x": "가구 | 9881726"})
    assert out["FN"] == 0 and out["TN"] == 1


def test_korean_units():
    assert cr.extract_numbers("약 2만 6천 명", merge=True) == [(26000.0, 500.0)]
    assert cr.extract_numbers("1만 2천 5백명", merge=True)[0][0] == 12500
    assert cr.extract_numbers("3억 4천만 명", merge=True)[0][0] == 340000000


def test_formula_constant_is_not_a_claim():
    for s in ("차이 ÷ 기준 * 100", "(b-a)/a × 100 = -24.33%", "100을 곱해 퍼센트로"):
        assert 100.0 not in [v for v, _ in cr.extract_numbers(s, merge=True)], s
    assert 100.0 in [v for v, _ in cr.extract_numbers("2025년 100명 증가", merge=True)]


# ── C4: 단위 (GPT 지적 2) ────────────────────────────────────
def test_pct_unit():
    assert passed("Q13", "변화율은 6.724%입니다")
    assert passed("Q13", "6.724 퍼센트 증가")
    assert not passed("Q13", "6.724명 증가했습니다")


def test_pp_unit():
    assert passed("Q17", "14.6%p 증가")
    assert passed("Q17", "14.6퍼센트포인트 증가")
    assert not passed("Q17", "14.6% 증가")


def test_diff_has_no_percent():
    assert passed("Q15", "110,487명 증가", "diff")
    assert not passed("Q15", "110,487% 증가", "diff")


# ── C4: 순위 역할 (GPT 지적 1) ───────────────────────────────
RANK = [
    ("Q14", "1위 서울특별시, 최하위 경기도", False),
    ("Q14", "1위 경기도, 최하위 서울특별시", True),
    ("Q14", "서울특별시가 가장 많고, 경기도가 가장 적습니다.", False),
    ("Q14", "순유입이 가장 많은 시도와 가장 적은 시도는 각각 경기도, 서울특별시입니다.", True),
    ("Q14", "순유입이 가장 많은 시도와 가장 적은 시도는 각각 서울특별시, 경기도입니다.", False),
    ("Q14", "경기도는 순유입 1위, 서울은 순유출 1위입니다.", True),
    ("Q14", "서울이 순유입 1위이고 경기는 순유출 1위입니다.", False),
    ("Q14", "경기도 | 32,970\n서울특별시 | -26,769", True),            # 역할어가 없으면 판단하지 않는다
    ("Q12", "경기도가 1위(76,309명)이고 세종특별자치시가 최하위(2,954명)입니다.", True),
    ("Q12", "세종특별자치시가 1위(76,309명)이고 경기도가 최하위입니다.", False),
    ("Q18", "가장 높은 년생은 1983년생(71.3%), 가장 낮은 년생은 1995년생(9.3%)", True),
    ("Q18", "가장 높은 년생은 1995년생(71.3%), 가장 낮은 년생은 1983년생(9.3%)", False),
    ("Q21", "가구 수가 가장 많은 연령대는 70~74세입니다.", True),
    ("Q21", "70~74세는 가구 수가 가장 적습니다.", False),
]


def test_rank_roles():
    for qid, ans, want in RANK:
        assert passed(qid, ans, "top1", *(["bottom1"] if "bottom1" in G[qid]["metrics"] else [])) is want, (qid, ans)


# ── C4: 누락과 계산 오류 구분 (점수는 같고 사유만 다르다) ───────
def test_missing_vs_wrong_value():
    miss = c4("Q16", "2020년 2,152,572명, 2025년 1,628,873명입니다")["pct"]
    wrong = c4("Q16", "변화율은 -24.7% 감소했습니다")["pct"]
    assert "계산 누락" in miss and "다른 값" in wrong and "-24.7" in wrong
    assert cr.c4(G["Q16"], {"answer": "-24.33% 감소"})["score"] == 1


# ── 지표형 관문 3: 검증 경고 (GPT 지적 3) ─────────────────────
def test_unverified_numbers_fail_gate3():
    g, pct = G["Q13"], G["Q13"]["gold_metrics"]["pct"]["value"]
    texts = {"x": f"핵심 수치: 변화율 {pct:.3f}%"}
    g1 = {"pass": True, "fused_top": []}
    ok = ev.judge(g, {"answer": f"변화율은 {pct:.3f}%입니다", "unverified_numbers": []}, g1, texts)
    bad = ev.judge(g, {"answer": f"변화율은 {pct:.3f}%이고 총 999,999명입니다", "unverified_numbers": ["999,999"]}, g1, texts)
    assert ok[0] == 4 and bad[0] == 3


def test_derived_gold_flag_is_false_alarm():
    # 72.9-58.1=14.8 은 문맥에 그대로 없어 verify 가 경고하지만 정답이다 → 실패 사유가 되면 안 된다
    assert cr.wrong_flags(G["Q19"], {"unverified_numbers": ["14.8"]}) == []
    assert cr.wrong_flags(G["Q13"], {"unverified_numbers": ["999,999"]}) == ["999,999"]
    assert cr.wrong_flags(G["Q13"], {"unverified_numbers": ["6.724", "999,999"]}) == ["999,999"]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("통과", name)
        except AssertionError as e:
            failed += 1
            print("실패", name, e)
    print(f"{len(tests) - failed}/{len(tests)} 통과")
    raise SystemExit(1 if failed else 0)
