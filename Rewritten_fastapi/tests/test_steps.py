"""단계별 동작 확인 (HCX 호출 없음). 노트북에서 주석 처리한 '확인/동작 확인' 출력을 테스트로 옮긴 것"""
from datetime import date

from rewriter.bundle import make_bundle
from rewriter.extract import rule_extract
from rewriter.sentence import build_sentences, slots_to_sentence
from rewriter.terms import lookup_terms, to_canonical
from rewriter.validate import validate_slots

TODAY = date(2026, 11, 2)


# ---- 2-1 용어 사전 ----
def test_terms():
    assert lookup_terms("2025년 전국에서 혼자 사는 가구는 몇 가구로 집계됐지?") == [("혼자 사는", ["1인가구"])]
    assert lookup_terms("2024년 서울에 사는 베트남 여자 결혼이민자 몇 명이야?") == []      # '결혼이민자' 안의 '결혼' 안 잡음
    assert lookup_terms("합계출산율 꼴찌 지역") == []                                        # 대표 용어 그대로
    assert lookup_terms("혼자사는 노인 비율") == [("혼자 사는", ["1인가구"]), ("노인 비율", ["고령인구비율"])]
    assert to_canonical("가구 수") == ("가구수", True)
    assert to_canonical("인구수") == ("인구수", False)


# ---- 2-2 코드 추출 ----
def test_extract():
    cases = {
        "2025년 전국에서 혼자 사는 가구는 몇 가구로 집계됐지?": {"시점": ["2025년"], "지역": ["전국"]},
        "지난해 전국 평균 가구원수는 몇 가구야?": {"시점": ["2025년"], "지역": ["전국"]},
        "인구동태패널통계에서 1983~1995년생 코호트": {"조건": ["출생연도=1983~1995년생"]},
        "2024년 7월부터 9월까지 외국인 순이동을 월별로 보여 줘.": {"시점": ["2024년 7월", "2024년 8월", "2024년 9월"]},
        "작년 전국 주택수와 올해 9월 전국 주민등록인구": {"시점": ["2025년", "2026년 9월"], "지역": ["전국"]},
        "2023년 남녀 평균초혼연령 차이": {"시점": ["2023년"], "성별": ["남자", "여자"]},
        "삼십대 여성 일인가구 2024 어딧어?": {"시점": ["2024년"], "성별": ["여자"], "연령": ["30~39세"]},
        "1인 가구를 가구주 연령대별로 보면 30대와 70대 이상": {"연령": ["30~39세", "70세 이상"]},
        "2024년 제주특별자치도 제주시 구좌읍의 총인구": {"시점": ["2024년"], "지역": ["제주특별자치도"]},
        "인도네시아 국적 등록외국인": {"국적": ["인도네시아"]},
    }
    for q, expected in cases.items():
        assert rule_extract(q, TODAY)[1] == expected, q
    q2, found, _ = rule_extract("2000 년 부터 2025 년까지의 1인 가구의 수의 추이", TODAY)
    assert found["시점"] == [f"{y}년" for y in range(2000, 2026)]


# ---- 2-4 검증: 실수가 섞인 HCX 응답 (노트북 2단계 마크다운 예시) ----
def _fake_result():
    q = "작년 서울 노인 인구랑 경기도 가구 수 알려줘"
    q2, found, _ = rule_extract(q, TODAY)
    return {"question": q, "input_question": q2, "rule_found": found, "term_hits": lookup_terms(q2),
            "hcx_slots": {"시점": ["2025년"], "지역": ["서울특별시", "경기도"], "대상": ["인구", "가구"],
                          "연령": ["65세 이상"], "지표": ["인구수", "가구 수"], "의도": "값 조회"},
            "hcx_subs": [{"시점": ["2025년"], "지역": ["서울"], "대상": ["인구"], "연령": ["65세 이상"], "지표": ["인구수"], "의도": "값 조회"},
                         {"시점": ["2024년"], "지역": ["경기도"], "대상": ["가구"], "지표": ["가구 수"], "의도": "조회"}]}


def test_validate():
    v = validate_slots(_fake_result())
    assert v["slots"]["지표"] == ["인구수", "가구수"]
    assert v["sub_slots"][0]["지역"] == ["서울특별시"]
    assert v["sub_slots"][1]["시점"] == ["2025년"]          # 질문에 없는 2024년 삭제 → 질문 전체 시점으로 채움
    assert v["sub_slots"][1]["의도"] == "값 조회"
    assert validate_slots({"question": "q", "input_question": "q", "rule_found": {"시점": ["2025년"]},
                           "hcx_slots": None, "error": "HTTP 500"})["slots"]["시점"] == ["2025년"]   # HCX 실패 → 코드 값만


def test_noin_moves_to_age():
    v = validate_slots({"question": "x", "input_question": "2025년 서울 노인 몇 명", "rule_found": {"시점": ["2025년"], "지역": ["서울특별시"]},
                        "term_hits": [("노인", ["65세 이상"])], "hcx_subs": [],
                        "hcx_slots": {"시점": ["2025"], "지역": ["서울"], "대상": ["노인"], "지표": ["인구수"], "의도": "값 조회"}})
    assert v["slots"]["대상"] == ["인구"] and v["slots"]["연령"] == ["65세 이상"]


# ---- 3 문장 ----
def test_sentence():
    assert slots_to_sentence({"시점": ["2024년"], "지역": ["서울특별시"], "국적": ["베트남"], "성별": ["여자"],
                              "대상": ["결혼이민자"], "지표": ["인구수"], "의도": "값 조회"}) == "2024년 서울특별시 베트남 여자 결혼이민자 인구수"
    assert slots_to_sentence({"전출지": ["부산광역시"], "전입지": ["울산광역시"], "이동": ["전출"], "지표": ["이동자수"],
                              "의도": "추이"}) == "부산광역시→울산광역시 전출 이동자수 추이"
    assert slots_to_sentence({"시점": [f"{y}년" for y in range(2000, 2026)], "대상": ["1인가구"], "지표": ["가구수"],
                              "의도": "추이"}) == "2000~2025년 1인가구 가구수 추이"
    assert slots_to_sentence({"시점": ["2019년", "2023년"], "대상": ["출생아"], "지표": ["출생아수"], "의도": "증감"}) == "2019년, 2023년 출생아수 증감"
    assert slots_to_sentence({"대상": ["인구"], "비교축": ["성별", "시도"], "의도": "비교"}) == "인구 성별 시도별 비교"


# ---- 4 QueryBundle ----
def test_bundle():
    v = validate_slots(_fake_result())
    b = make_bundle("작년 서울 노인 인구랑 경기도 가구 수 알려줘", v, build_sentences(v))
    assert b.sub_questions == ["2025년 서울특별시 65세 이상 인구수", "2025년 경기도 가구수"]
    assert b.intent == "값 조회"
    assert "의도" not in b.filters
    assert len(b.sub_filters) == 2
