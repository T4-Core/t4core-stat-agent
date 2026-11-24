"""표 이름에만 있는 조건 · 형제 표 힌트 (reverse_qa_agent.table_qualifiers · sibling_hints)

  실데이터 결함: 정답 표가 '…(남)' · '…(15세이상)' 인데 질문에는 성별 · 모집단이 없음 → 검색이 (계) · 전체 인구 표를
  골라도 오답으로 셈 (backend/rag/search/tuning/gold_audit.py 가 기존 셋에서 찾는 것과 같은 결함을 생성 때 막음)
"""
from types import SimpleNamespace as NS

from synthetic_gold_pipeline.agents.reverse_qa_agent import (
    ReverseQAGeneratorAgent,
    ReverseQAOutput,
    condition_labels,
    sibling_hints,
    table_qualifiers,
)


def test_table_qualifiers():
    assert table_qualifiers("한국국적을 취득한 자-기타(남)(2007~2015)") == ["남자"]
    assert table_qualifiers("행정구역/성/연령/혼인상태별 인구(15세 이상)") == ["15세이상"]
    assert table_qualifiers("시도별 출생") == []


def _view(title, dims=(), sel=None):
    """condition_labels 가 보는 것만 가진 가짜 View — dims: [(level, obj_nm, {code: (name, is_total)})]"""
    dmap = {lv: NS(obj_nm=nm, dim_type=None) for lv, nm, _ in dims}
    cmap = {lv: {c: NS(name=n, is_total=t) for c, (n, t) in codes.items()} for lv, _, codes in dims}
    return NS(table_title=title, source_coordinates=NS(dim_filters={}), dim=lambda lv: dmap.get(lv),
              code_map=lambda lv: cmap.get(lv, {})), NS(coordinates=sel or {})


def test_condition_labels_add_title_qualifiers():
    v, o = _view("행정구역/성/연령/혼인상태별 인구(15세이상)")
    assert condition_labels(v, o) == ["15세이상"]
    # 성별 분류로 이미 '남자' 가 들어 있으면 표 이름의 (남) 을 또 넣지 않음
    v, o = _view("시도별 이혼(남)", [("C2", "성별", {"1": ("남자", False)})], {"C2": "1"})
    assert condition_labels(v, o) == ["남자"]


def test_validator_requires_qualifier_in_both_questions(demo_env):
    from synthetic_gold_pipeline.agents.llm_client import MockLLMClient
    qa = ReverseQAGeneratorAgent(MockLLMClient(), demo_env["index"])
    bundle = {"llm_input": {"operands": [{"period": "1985년", "condition_labels": ["15세이상"]}], "scalar_facts": [],
                            "thresholds": [], "entities": [], "k": None}, "values": {"FINAL": "1호"}}
    errs = qa.validate(ReverseQAOutput(question_original="1985년 안동군 15세 이상 인구 천 명당 주택은?",
                                       question_paraphrased="1985년 안동군 사람 천 명당 집은 몇 채?",
                                       answer_template="{FINAL}입니다.", limitations=[]), bundle)
    assert any("question_paraphrased" in e and "15세이상" in e for e in errs)
    assert not any("question_original" in e and "15세이상" in e for e in errs)


def test_sibling_hints():
    def tm(title, survey="인구동태패널통계", dims=("성별", "년생별")):
        return NS(table_title=title, survey_name=survey, dimension_definitions=[NS(obj_nm=d) for d in dims])
    index = NS(tables={"101_A004": tm("당해연도 혼인 비율"), "101_A001": tm("누적 혼인 비율"),
                       "101_A002": tm("누적 출산 비율"), "101_X": tm("당해연도 혼인 비율", survey="다른 조사")})
    hints = sibling_hints(index, ["101_A004"])
    assert hints == [{"this_table": "당해연도 혼인 비율", "sibling_table": "누적 혼인 비율", "only_in_this": ["당해연도"]}]
    assert sibling_hints(NS(tables={}), ["101_A004"]) == []
