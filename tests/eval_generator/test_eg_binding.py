"""numeric_match 와 semantic_ok 분리 (계획 2.2, D-5 · D-25)"""
from eval.generator import binding
from synthetic_gold_pipeline.schemas.dataset import ExpectedClaim
from synthetic_gold_pipeline.tools.evaluation_tool import NumericAnswerEvaluator
from tests.eval_generator._fx import REC_BIRTH, births, share_calc

WANT = {"region": "서울", "period": "2024"}


def test_existing_evaluator_false_pass_reproduced():
    """기존 평가기는 FINAL 값의 지역 · 기간을 보지 않는다 (0.6장 #5)"""
    claims = [ExpectedClaim(claim_id="f", role="FINAL", value=100, value_text="100", unit="명", period="2024", region="서울특별시")]
    chk = NumericAnswerEvaluator().evaluate("2023년 부산광역시 100명입니다.", claims, {"unit_required": True})
    assert chk.final_value_ok and chk.passed


def test_text_binding_rejects_other_region_and_year():
    b = binding.check("2023년 부산광역시 100명입니다.", 100, "명", WANT)
    assert b.numeric_match and b.semantic_ok is False
    b = binding.check("2024년 서울특별시 100명입니다.", 100, "명", WANT)
    assert b.numeric_match and b.semantic_ok is True


def test_two_regions_two_values_nearest_label():
    text = "2024년 부산광역시는 50명, 서울특별시는 100명입니다."
    assert binding.check(text, 100, "명", WANT).semantic_ok is True
    assert binding.check(text, 50, "명", WANT).semantic_ok is False


def test_structural_binding_restores_fixed_region_via_select():
    """서울 단일 계열 계산(key={'시점': '2024'})에서 원본 행으로 지역 복원. 분모 '전국 대비' 는 입력 지역이라 불일치가 아니다"""
    calc = share_calc()
    steps = [{"step_id": "a1", "operands": [{"record_id": REC_BIRTH, "select": {"시군구별": ["서울특별시"]}}]}]
    b = binding.check("2024년 서울의 출생아 비중은 전국 대비 17.5%입니다.", 0.17458, "ratio", WANT, tol=0.0005,
                      calc=calc, records=[births()], steps=steps)
    assert b.semantic_ok is True and "서울" in b.detail["structural"]["regions"]


def test_ambiguous_restore_is_unresolved_not_judged():
    """같은 record_id + key 에 행이 둘이고 값으로도 좁혀지지 않으면 binding_unresolved, semantic_ok=None"""
    rec = births()
    rec["table"]["rows"].append(["2024", "부산광역시", "출생아수", 41605.0])        # 서울과 값이 같은 행
    calc = share_calc()
    b = binding.check("2024년 서울의 출생아 비중은 전국 대비 17.5%입니다.", 0.17458, "ratio", WANT, tol=0.0005,
                      calc=calc, records=[rec], steps=[])
    assert b.numeric_match and b.semantic_ok is None and b.detail["why"] == "binding_unresolved"
