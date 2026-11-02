"""[NEW] 평가 질문 세트 자동 탐색 (eval/pipeline_review/review_80.py) — HCX 없음

새 테스트 파일을 storage/test_data 에 넣기만 하면 코드 수정 없이 읽히는지 확인
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "pipeline_review"))
import review_80 as rv  # noqa: E402


@pytest.fixture
def test_dir(tmp_path):
    d = tmp_path / "test_data"
    d.mkdir()
    # 1) 기존 형식 + 짝이 되는 정답 참고 파일
    pd.DataFrame({"id": ["Q001", "Q002"], "survey": ["인구총조사", "인구동향조사"], "test_type": ["EXACT", "CHANGE"],
                  "target_module": ["M1", "M2"], "question": ["질문1", "질문2"]}) \
        .to_csv(d / "kosis_rag_eval_80_queries.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({"id": ["Q001"], "answerability": ["ANSWERABLE"], "gold_tbl_id": ["DT_1"], "pass_criteria": ["기준1"]}) \
        .to_csv(d / "kosis_rag_eval_80_answers_references.csv", index=False, encoding="utf-8-sig")
    # 2) 한글 열 이름 + id 없음 + 엑셀식 cp949 CSV + 정답 열이 같은 파일에
    pd.DataFrame({"질문": ["서울 인구", "부산 인구", ""], "조사명": ["주민등록인구현황"] * 3, "유형": ["EXACT"] * 3,
                  "통과기준": ["서울 값", "부산 값", ""]}) \
        .to_csv(d / "new_set_2026.csv", index=False, encoding="cp949")
    # 3) jsonl, query 열
    (d / "smoke.jsonl").write_text("\n".join(json.dumps({"qid": f"S{i}", "query": f"q{i}"}, ensure_ascii=False)
                                             for i in range(3)), encoding="utf-8")
    # 4) 질문 열이 없는 파일 → 오류로 표시만 (전체를 멈추지 않음)
    pd.DataFrame({"a": [1]}).to_csv(d / "broken.csv", index=False)
    return d


def test_find_sets(test_dir):
    sets = {s["name"]: s for s in rv.find_test_sets(test_dir)}
    assert "kosis_rag_eval_80_answers_references" not in sets          # 정답 참고 파일은 세트가 아님
    assert sets["kosis_rag_eval_80_queries"]["refs"].name == "kosis_rag_eval_80_answers_references.csv"
    assert sets["kosis_rag_eval_80_queries"]["columns"]["target_modules"] == "target_module"
    assert sets["new_set_2026"]["columns"] == {"question": "질문", "survey": "조사명", "test_type": "유형"}
    assert sets["smoke"]["columns"] == {"id": "qid", "question": "query"}
    assert "error" in sets["broken"]
    assert sets["new_set_2026"]["run"].dir.name == "new_set_2026"     # 세트마다 결과 폴더 따로


def test_load_questions(test_dir):
    q80 = rv.load_questions("80", test_dir)
    assert [q["id"] for q in q80] == ["Q001", "Q002"]
    assert q80[0]["reference"] == {"answerability": "ANSWERABLE", "gold_tbl_id": "DT_1", "pass_criteria": "기준1"}
    assert rv.expected_tables(q80[0]["reference"]) == {"DT_1"}
    assert rv.pass_criteria_of(q80[0]) == "기준1"
    new = rv.load_questions("new_set", test_dir)
    assert [(q["id"], q["question"], q["survey"]) for q in new] == [("Q001", "서울 인구", "주민등록인구현황"),
                                                                    ("Q002", "부산 인구", "주민등록인구현황")]   # 빈 질문 제외, id 자동
    assert rv.pass_criteria_of(new[0]) == "서울 값"                     # 같은 파일의 남는 열 = 정답 참고
    assert [q["id"] for q in rv.load_questions(str(test_dir / "smoke.jsonl"))] == ["S0", "S1", "S2"]


def test_resolve(test_dir):
    with pytest.raises(ValueError, match="여러 개"):
        rv.resolve_test_set(None, test_dir)
    with pytest.raises(ValueError):
        rv.resolve_test_set("없는세트", test_dir)
    assert rv.resolve_test_set("1", test_dir)["name"] == "kosis_rag_eval_80_queries"   # 번호 (이름순)
    one = test_dir.parent / "only"
    one.mkdir()
    (one / "a.jsonl").write_text(json.dumps({"question": "x"}), encoding="utf-8")
    assert rv.resolve_test_set(None, one)["name"] == "a"                                # 하나뿐이면 생략 가능
