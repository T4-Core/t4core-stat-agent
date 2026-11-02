"""4. 최종 출력: QueryBundle + rewrite_query()
노트북 user_question_rewrite_v2.ipynb '4' 셀의 코드를 그대로 옮김 (실행 부분은 뺌). 저장 경로만 Rewritten_fastapi/outputs 로 바꿈
run_pipeline() 은 노트북에서 셀마다 나눠 하던 2-3 → 2-4 → 3 → 4 를 한 번에 하고 중간 결과까지 돌려줌 (API·대시보드용)"""
import json

from .config import OUTPUT_DIR
from .sentence import build_sentences, slots_to_sentence              # 3
from .slots import call_slots                                          # 2-3
from .validate import validate_slots                                   # 2-4

# ============= 4. 최종 출력: QueryBundle ================
# 재작성 모듈 → 검색 모듈로 넘기는 결과 묶음
# - 아래쪽 '1) 지금까지 결과로 묶기'는 2-3 ~ 3단계에서 이미 만든 결과를 묶기만 함 (HCX 추가 호출 없음)
# - rewrite_query(질문)은 2-3 ~ 4단계를 한 번에 실행 (HCX 1회). 검색 모듈에서는 이 함수만 부르면 됨
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd


@dataclass
class QueryBundle:
    """재작성 모듈 -> 검색 모듈. 질문 하나를 재작성한 결과 묶음."""
    original: str                                              # 사용자 원 질문
    rewritten: str                                             # 재작성된 질문 (3단계 문장)
    sub_questions: list[str] = field(default_factory=list)     # 복합 질문을 나눈 하위 질문 (없으면 [])
    intent: str | None = None                                  # 질문 분류 (의도 6개 중 하나)
    filters: dict[str, list[str]] | None = None                # 슬롯 (값 있는 슬롯만, 의도 제외)
    sub_filters: list[dict] | None = None                      # 하위 질문 슬롯 (sub_questions 와 순서 같음)


def to_filters(slots):
    """검증된 슬롯 → filters (값 있는 슬롯만, 의도 제외). 모두 비면 None"""
    f = {k: list(v) for k, v in (slots or {}).items() if k != "의도" and v}
    return f or None


def make_bundle(question, valid, sentences):
    """2-4 결과(valid) + 3단계 결과(sentences) → QueryBundle
    rewritten이 비면(슬롯이 모두 빔) 원 질문을 그대로 씀
    하위 질문 문장과 하위 슬롯은 같은 순서로 넣음 (문장이 빈 하위 슬롯은 함께 뺌)"""
    pairs = [(slots_to_sentence(s), s) for s in valid.get("sub_slots", [])]
    pairs = [(txt, s) for txt, s in pairs if txt]
    return QueryBundle(
        original=question,
        rewritten=sentences["rewritten"] or question,
        sub_questions=[txt for txt, _ in pairs],
        intent=valid["slots"].get("의도"),
        filters=to_filters(valid["slots"]),
        sub_filters=[to_filters(s) or {} for _, s in pairs] or None,
    )


def rewrite_query(question, today=None, debug=False):
    """질문 하나 → QueryBundle (2-3 HCX 슬롯 추출 → 2-4 검증 → 3 문장 → 4 묶기). HCX 1회
    debug=True면 프롬프트, HCX 원 응답, 검증 내역을 출력"""
    r = call_slots(question, today)
    v = validate_slots(r)
    b = make_bundle(question, v, build_sentences(v))
    if debug:
        print("----- user 프롬프트 -----\n" + r["messages"][1]["content"])
        print(f"\n----- HCX 원 응답 ({r['elapsed_s']}초) -----\n", r["hcx_out"] if r["parsed"] else f"실패: {r['error']}")
        print("\n----- 검증 내역 -----", *(v["log"] or ["없음"]), sep="\n  - ")
        print()
    return b


def bundles_table(bundles):
    """QueryBundle 목록 → 확인용 표"""
    return pd.DataFrame([asdict(b) for b in bundles])


SAVE_PATH = OUTPUT_DIR / "query_bundles.json"   # Rewritten_fastapi/outputs 에 저장 (노트북: 노트북과 같은 폴더)


def save_bundles(bundles, path=SAVE_PATH):
    """QueryBundle 목록 → JSON 파일 (QueryBundle 필드만, 목록 하나). 같은 이름이 있으면 덮어씀"""
    path = Path(path)
    path.write_text(json.dumps([asdict(b) for b in bundles], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {path.resolve()} ({len(bundles)}개)")
    return path


def load_bundles(path=SAVE_PATH):
    """저장한 JSON 파일 → QueryBundle 목록"""
    return [QueryBundle(**x) for x in json.loads(Path(path).read_text(encoding="utf-8"))]


def run_pipeline(question, today=None):
    """질문 하나 → 단계별 중간 결과 + QueryBundle. HCX 1회 (rewrite_query 와 같은 순서)
    반환: {"slot": 2-3 결과, "valid": 2-4 결과, "sentences": 3 결과, "bundle": QueryBundle}"""
    r = call_slots(question, today)
    v = validate_slots(r)
    sres = build_sentences(v)
    return {"slot": r, "valid": v, "sentences": sres, "bundle": make_bundle(question, v, sres)}
