"""[NEW] judge 테스트들이 함께 쓰는 가짜 Record 생성기

파일 이름이 test_ 로 시작하지 않으므로 pytest 는 이 파일을 테스트로 실행하지 않는다 (도우미 전용).
"""


def make_record(columns, rows, rid="view::101_DT_TEST::Y::1-1::value", title="테스트 표", **meta):
    """테스트용 Record dict. build_view 가 만드는 모양과 같게 (필요한 필드만 채움)
    title  = lexical_text (표 이름 등). 지표·대상이 '표 이름에만' 있는 경우를 시험할 때 바꾼다
    **meta = 이름 붙인 인자를 모두 dict 로 받는다 (예: make_record(..., prd_se="M") → meta = {"prd_se": "M"})"""
    return {
        "id": rid,
        "lexical_text": title,
        "table": {"columns": columns, "rows": rows},
        "doc_type": "view",
        "parent_id": "table::101_DT_TEST",
        "metadata": {"prd_se": "Y", "view_type": "value", **meta},   # **meta 로 기본값을 덮어씀
        "source": {"tbl_id": "DT_TEST", "prd_se": meta.get("prd_se", "Y")},
    }
