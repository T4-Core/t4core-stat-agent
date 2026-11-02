"""[파트 1] 사용자 질문 재작성 모듈 (구 Rewritten_fastapi/rewriter — 노트북 user_question_rewrite_v2.ipynb 를 나눈 것)

[CHANGED] import 경로: from rewriter import … → from backend.rag.query_analyzer import …
구조안의 파일 이름(rewriter.py / decomposer.py / filter_extractor.py)은 아래 실제 모듈을 묶어 보여 주는 진입점으로 추가함 [NEW]
View 모듈과의 입출력 연결: adapter.py (재작성 QueryBundle → View 모듈 QueryBundle) [NEW]

질문 → [2-1 용어 사전] → [2-2 코드 추출] → [2-3 HCX 슬롯 추출] → [2-4 슬롯 검증] → [3 슬롯 → 문장] → [4 QueryBundle]

    from backend.rag.query_analyzer import rewrite_query
    bundle = rewrite_query("2025년 전국에서 혼자 사는 가구는 몇 가구로 집계됐지?")

| 모듈        | 노트북 단계 |
|-------------|-------------|
| config.py   | 0-1 환경설정, 0-3 HCX 호출 확인 (베이스 코드는 kosis_rag_qa.py 복사본에서 불러옴) |
| terms.py    | 2-1 용어 사전 |
| extract.py  | 2-2 코드 추출 |
| slots.py    | 2-3 HCX 슬롯 추출 |
| validate.py | 2-4 슬롯 검증 |
| sentence.py | 3 슬롯 → 문장 |
| bundle.py   | 4 QueryBundle, rewrite_query, run_pipeline |
| trace.py    | 5 대시보드용 중간 결과 |
"""
from .bundle import QueryBundle, load_bundles, make_bundle, rewrite_query, run_pipeline, save_bundles
from .config import check_hcx, settings
from .trace import build_trace, save_trace

__all__ = ["QueryBundle", "rewrite_query", "run_pipeline", "make_bundle", "save_bundles", "load_bundles",
           "build_trace", "save_trace", "check_hcx", "settings"]
