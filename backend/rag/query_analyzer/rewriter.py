"""[NEW] 구조안의 rewriter.py — 구어체 정규화·표준 슬롯 변환·검색 문장 만들기 진입점

실제 코드는 노트북 단계별 파일에 그대로 있다 (팀원이 나중에 이 파일로 합칠 때 참고):
  terms.py     2-1 일상어 → KOSIS 용어          lookup_terms, to_canonical
  sentence.py  3   슬롯 → 검색용 문장            slots_to_sentence, build_sentences
  bundle.py    4   QueryBundle 생성 (HCX 1회)    rewrite_query, run_pipeline
"""
from .bundle import QueryBundle, make_bundle, rewrite_query, run_pipeline  # noqa: F401
from .sentence import build_sentences, slots_to_sentence  # noqa: F401
from .terms import TERM_DICT, lookup_terms, to_canonical  # noqa: F401
