"""[NEW] template.py — HCX 없이 만드는 규칙 문장"""
from backend.agent.answer_compose.caveats import build_caveats
from backend.agent.answer_compose.facts import Facts
from backend.agent.answer_compose.template import compose, sentence
from backend.schemas.chart import CalcResult
from tests.answer_compose._data import growth, inp, request
from tests.chart_calculate._views import VID


def res(**kw) -> CalcResult:
    return CalcResult.model_validate({"step_id": "a1", "record_ids": [VID], **kw})


def one(r):
    f = Facts(request(results=[r]))
    return sentence(f, f.results[r.step_id])


def test_growth_rate_up_and_down():
    assert one(growth()) == "전국 혼인건수는 2021년 192,507건에서 2025년 240,326건으로 24.8% 증가했습니다."
    down = res(op="growth_rate", value=-2.3875, unit="%", display_ref="d1",
               inputs=[inp("2021", 260562, "출생아수(명)", unit="명"), inp("2025", 254341, "출생아수(명)", unit="명")])
    assert one(down) == "전국 출생아수는 2021년 260,562명에서 2025년 254,341명으로 2.4% 감소했습니다."


def test_change_diff_share():
    ch = res(op="change", value=47819, unit="건", display_ref="d2", inputs=[inp("2021", 192507), inp("2025", 240326)])
    assert one(ch) == "전국 혼인건수는 2021년 192,507건에서 2025년 240,326건으로 47,819건 증가했습니다."
    df = res(op="diff", value=-1000, unit="건", display_ref="d2", inputs=[inp("2025", 100), inp("2025", 1100, "출생아수(명)")])
    assert one(df) == "2025년 혼인건수(100건)가 출생아수(1,100건)보다 1,000건 작습니다."          # 같은 시점은 앞에 한 번만
    sh = res(op="share", value=12.34, unit="%", display_ref="d1", scope_label="선택 항목 내 비중", inputs=[inp("2025", 1)])
    assert one(sh) == "혼인건수의 비중은 12.3%입니다. (분모: 선택 항목 내 비중)"


def test_negative_base_direction_is_end_minus_start():
    neg = res(op="change", value=50, unit="명", display_ref="d2", inputs=[inp("2021", -100, "순이동자수(명)", unit="명"), inp("2025", -50, "순이동자수(명)", unit="명")])
    assert one(neg) == "순이동자수는 2021년 -100명에서 2025년 -50명으로 50건 증가했습니다."
    odd = res(op="growth_rate", value=-50.0, unit="%", display_ref="d1", inputs=[inp("2021", -100, "순이동자수(명)", unit="명"), inp("2025", -50, "순이동자수(명)", unit="명")])
    assert "증가했습니다" in one(odd) and "감소" not in one(odd)       # 값은 -50% 라도 -100 → -50 은 늘었다 (모듈 3 은 이 경우 계산하지 않지만 방어)


def test_zero_change():
    z = res(op="growth_rate", value=0, unit="%", display_ref="d1", inputs=[inp("2021", 5), inp("2025", 5)])
    assert one(z).endswith("변화가 없습니다.")


def test_rank_and_extreme():
    rk = res(op="rank", unit="건", display_ref="d2", inputs=[inp("2025", 240326)],
             value=[{"key": {"시점": str(y)}, "value": v, "rank": n} for n, (y, v) in enumerate([(2025, 240326), (2024, 222412)], 1)])
    assert one(rk) == "전국 혼인건수 순위는 1위 2025년 240,326건, 2위 2024년 222,412건입니다."
    ex = res(op="extreme", unit="건", display_ref="d2", value=[{"key": {"시점": "2021"}, "value": 192507}], inputs=[inp("2021", 192507)])
    assert one(ex) == "전국 혼인건수의 극값(최대 또는 최소)은 2021년 192,507건입니다."      # answer_steps 를 못 받으면 방향을 단정하지 않는다


def test_failed_calc_and_caveats_appended():
    f = Facts(request(results=[growth(), growth("a2", None).model_copy(update={"note": "기준값 0"})]))
    lines = compose(f, build_caveats(f)).splitlines()
    assert lines[0].endswith("혼인건수 증감률을 계산하지 못했습니다(기준 값이 0이라 비율을 계산할 수 없습니다).")
    assert lines[1].startswith("※ 혼인건수 증감률을 계산하지 못했습니다: 기준 값이 0이라 비율을 계산할 수 없습니다")
