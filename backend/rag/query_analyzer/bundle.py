"""4. 최종 출력: QueryBundle + rewrite_query()
노트북 user_question_rewrite_v3.ipynb '4' 셀의 코드를 그대로 옮김 (실행 부분은 뺌). 저장 위치는 config.OUTPUT_DIR (eval/query_rewrite/outputs)
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
from datetime import datetime
from pathlib import Path

import pandas as pd


@dataclass
class QueryBundle:
    """재작성 모듈 -> 검색 모듈. 질문 하나를 재작성한 결과 묶음."""
    original: str                                              # 사용자 원 질문
    rewritten: str                                             # 재작성된 질문 (3단계 문장)
    sub_questions: list[str] = field(default_factory=list)     # 복합 질문을 나눈 하위 질문 (없으면 [])
    intent: str | None = None                                  # 원 질문의 의도 하나 (9개 중). v2 모듈·API 스키마와 같은 형식
    filters: dict[str, list[str]] | None = None                # 슬롯 (값 있는 슬롯만, 의도 제외)
    sub_filters: list[dict] | None = None                      # 하위 질문 슬롯 (sub_questions 와 순서 같음)


def _intent_one(v):
    """의도 → 문자열 하나. 검증 슬롯은 의도가 목록(여러 개 가능)이므로 첫 번째 값을 씀 (목록이 저장된 예전 결과 파일도 받음)"""
    if isinstance(v, str):
        return v or None
    return next(iter(v or []), None)


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
        intent=_intent_one(valid["slots"].get("의도")),           # ['값 조회', '순위'] → '값 조회'
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


# 파일 이름에 실행 날짜·시간을 붙여 덮어쓰지 않음 → query_bundles_20261103_143015.json
SAVE_PREFIX = "query_bundles"


def bundle_runs():
    """저장된 실행 결과 파일 목록 (오래된 것 → 최근 것)"""
    return sorted(OUTPUT_DIR.glob(f"{SAVE_PREFIX}_*.json"))


def save_bundles(bundles, path=None):
    """QueryBundle 목록 → JSON 파일 (QueryBundle 필드만, 목록 하나)
    path=None 이면 OUTPUT_DIR/query_bundles_YYYYMMDD_HHMMSS.json (실행할 때마다 새 파일)"""
    path = Path(path) if path else OUTPUT_DIR / f"{SAVE_PREFIX}_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)   # [NEW] config.py 의 import 시점 생성을 옮겨옴
    path.write_text(json.dumps([asdict(b) for b in bundles], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {path.resolve()} ({len(bundles)}개)")
    return path


def load_bundles(path=None):
    """저장한 JSON 파일 → QueryBundle 목록. path=None 이면 가장 최근 실행 결과
    v3 실행 결과(query_bundles_*.json)가 없으면 v2 모듈이 저장한 query_bundles.json 을 읽음"""
    if path is None:
        runs = bundle_runs() or [p for p in [OUTPUT_DIR / f"{SAVE_PREFIX}.json"] if p.exists()]
        if not runs:
            raise FileNotFoundError(f"{OUTPUT_DIR} 에 {SAVE_PREFIX}_*.json 이 없음")
        path = runs[-1]
    return [QueryBundle(**{**x, "intent": _intent_one(x.get("intent"))})         # 목록으로 저장된 파일도 문자열 하나로
            for x in json.loads(Path(path).read_text(encoding="utf-8"))]


def compare_bundles(old=None, new=None, fields=("rewritten", "sub_questions", "intent", "filters", "sub_filters")):
    """두 실행 결과 비교 → 달라진 질문만 표로 (원 질문 기준으로 짝지음)
    old·new: 파일 경로 또는 QueryBundle 목록. 생략하면 가장 최근 두 실행 결과 (old=직전, new=최근)"""
    runs = bundle_runs()
    if old is None or new is None:
        if len(runs) < 2:
            raise FileNotFoundError("비교할 실행 결과가 2개 이상 있어야 함")
        old, new = old or runs[-2], new or runs[-1]
    name = lambda x: Path(x).stem.removeprefix(SAVE_PREFIX + "_") if isinstance(x, (str, Path)) else "목록"
    names = name(old), name(new)
    a = {b.original: asdict(b) for b in (load_bundles(old) if isinstance(old, (str, Path)) else old)}
    b = {x.original: asdict(x) for x in (load_bundles(new) if isinstance(new, (str, Path)) else new)}
    rows = []
    for q in dict.fromkeys([*a, *b]):                      # 질문 순서: old 먼저, new 에만 있는 질문은 뒤에
        x, y = a.get(q), b.get(q)
        if x is None or y is None:
            rows.append({"original": q, "field": "(질문)", names[0]: "없음" if x is None else "있음",
                         names[1]: "없음" if y is None else "있음"})
            continue
        rows += [{"original": q, "field": f, names[0]: x[f], names[1]: y[f]} for f in fields if x[f] != y[f]]
    print(f"비교: {names[0]} → {names[1]} | 질문 {len(set(a) | set(b))}개 중 달라진 질문 {len({r['original'] for r in rows})}개")
    return pd.DataFrame(rows, columns=["original", "field", *names])


def run_pipeline(question, today=None):
    """질문 하나 → 단계별 중간 결과 + QueryBundle. HCX 1회 (rewrite_query 와 같은 순서)
    반환: {"slot": 2-3 결과, "valid": 2-4 결과, "sentences": 3 결과, "bundle": QueryBundle}"""
    r = call_slots(question, today)
    v = validate_slots(r)
    sres = build_sentences(v)
    return {"slot": r, "valid": v, "sentences": sres, "bundle": make_bundle(question, v, sres)}
