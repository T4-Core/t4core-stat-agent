"""정답 라벨 초안 만들기 (HCX 호출 없음)

모수: 평가 질문 80개 전체 (data/kosis_rag_eval_80_queries.csv). 기준일 2026-11-02 고정
초안 = 지금 실행 결과(dashboard/rewrite_trace.json) + 정답 참고 파일(data/kosis_rag_eval_80_answers_references.csv)
  - answerability 가 OUT_OF_SCOPE·UNANSWERABLE 인 질문 → 정답 = "슬롯이 비어야 함"
  - 나머지 → 지금 결과를 정답 초안으로 복사 (틀린 결과도 그대로 들어가므로 사람이 검토해 고쳐야 함)
  - 확인이 필요해 보이는 질문에는 flags 를 달아 둠
  - 모든 항목 status = "검토 전"
survey·test_type·answerability 등은 집계·참고용(meta)으로만 넣음. 재작성 입력에는 쓰지 않음

실행 (Rewritten_fastapi 폴더에서)
    python scripts/make_gold_draft.py
저장
    data/rewrite_gold_80.draft.json      정답 라벨 초안
    labeling/gold_draft.js               같은 내용 (labeling/label_editor.html 이 서버 없이 바로 읽음)
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rewriter.slots import SLOT_KEYS     # noqa: E402

TODAY = "2026-11-02"
QUERIES = ROOT / "data" / "kosis_rag_eval_80_queries.csv"
REFS = ROOT / "data" / "kosis_rag_eval_80_answers_references.csv"
TRACE = ROOT / "dashboard" / "rewrite_trace.json"
OUT_JSON = ROOT / "data" / "rewrite_gold_80.draft.json"
OUT_JS = ROOT / "labeling" / "gold_draft.js"
EMPTY_ANSWERABILITY = {"OUT_OF_SCOPE", "UNANSWERABLE"}       # 정답 = 슬롯이 비어야 함

# 이전 80개 실행 결과를 보며 찾은 문제 (같은 질문이라도 다시 실행하면 결과가 다를 수 있으므로 '이전 실행에서' 로 표시)
KNOWN_ISSUES = {
    "Q005": "이전 실행: 지역에 '제주특별자치도'가 두 번 들어감 (계층 지역 값 처리 문제)",
    "Q007": "이전 실행: 지역 슬롯에 '합계출산율'이 들어감 (지명 아님)",
    "Q009": "이전 실행: HCX 슬롯이 밀려 씀 (전출지: 남자·여자, 성별: 추이 등)",
    "Q012": "이전 실행: 대상·지표가 비어 문장이 연령만 남음",
    "Q016": "이전 실행: 시군구 '신안군' 누락",
    "Q027": "이전 실행: 비교축에 '시도 내' (정해진 축 아님)",
    "Q031": "이전 실행: 문장에 지역만 남음",
    "Q044": "이전 실행: 비교축에 고위·중위·저위 (시나리오는 조건으로 보는 게 맞는지 확인)",
    "Q051": "이전 실행: '솔로 가구'가 사전에 없어 1인가구로 안 바뀜",
    "Q058": "이전 실행: 질문에 없는 '장래인구추계'가 붙음",
    "Q064": "이전 실행: '중구' 누락 (서울 중구, 대전 중구)",
    "Q069": "이전 실행: 시군구 '사하구' 누락",
    "Q077": "이전 실행: '일인가구'가 사전에 없어 1인가구로 안 바뀜",
}


def _list(v):
    return [str(x) for x in v] if isinstance(v, list) else ([] if v in (None, "") else [str(v)])


def ref_filters_to_slots(f):
    """정답 참고 파일 expected_filters → 슬롯 (참고용 비교에 씀)"""
    s = {}
    if "year" in f:
        s["시점"] = [f"{f['year']}년"]
    if "years" in f:
        s["시점"] = [f"{y}년" for y in f["years"]]
    if "month" in f:
        y, m = str(f["month"]).split("-")
        s["시점"] = [f"{int(y)}년 {int(m)}월"]
    if "region" in f:
        s["지역"] = [f["region"]]
    if "indicator" in f:
        s["지표·대상"] = [f["indicator"]]
    return s


def must_include_from(slots):
    """문장에 꼭 들어가야 할 단어 초안: 시점의 처음·끝 연도, 지역, 지표"""
    words = []
    years = sorted({v[:4] for v in slots.get("시점", [])})
    words += [years[0], years[-1]] if years else []
    words += slots.get("지역", []) + slots.get("전출지", []) + slots.get("전입지", [])
    words += slots.get("지표", [])
    return list(dict.fromkeys(words))


def main():
    q = pd.read_csv(QUERIES, encoding="utf-8-sig")
    ref = pd.read_csv(REFS, encoding="utf-8-sig").set_index("id")
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    if trace["meta"].get("today") != TODAY:
        print(f"주의: rewrite_trace.json 의 기준일({trace['meta'].get('today')})이 {TODAY} 와 다름")
    by_q = {it["question"]: it for it in trace["items"]}

    items = []
    for _, row in q.iterrows():
        qid, question = row["id"], str(row["question"]).strip()
        rf = ref.loc[qid] if qid in ref.index else None
        get = (lambda c: (None if rf is None or pd.isna(rf[c]) else rf[c]))
        cur = by_q.get(question)
        flags = []

        answerability = get("answerability")
        empty = answerability in EMPTY_ANSWERABILITY
        ref_filters = json.loads(get("expected_filters")) if get("expected_filters") else None
        ref_subs = json.loads(get("expected_sub_questions")) if get("expected_sub_questions") else None

        if cur is None:
            flags.append("지금 실행 결과 없음 (rewrite_trace.json 에 이 질문이 없음)")
            cur = {"term_hits": [], "rule_found": {}, "valid_slots": {}, "valid_subs": [], "rewritten": "", "valid_log": [],
                   "parsed": False}

        # 슬롯·하위 슬롯: 범위 밖·답 불가면 비움, 아니면 지금 결과 복사 (값 있는 것만)
        def pick(s):
            return {k: _list(s.get(k)) for k in SLOT_KEYS if _list(s.get(k))}

        slots = {} if empty else pick(cur["valid_slots"])
        intent = None if empty else (cur["valid_slots"].get("의도") or None)
        subs = [] if empty else [{**pick(s), "의도": s.get("의도") or None} for s in cur["valid_subs"]]

        # 확인 필요 표시
        if qid in KNOWN_ISSUES:
            flags.append(KNOWN_ISSUES[qid])
        if empty:
            flags.append(f"answerability={answerability} → 정답을 '슬롯이 비어야 함'으로 둠 (지금 결과: {cur.get('rewritten') or '빈 문장'})")
        elif answerability == "AMBIGUOUS":
            flags.append("answerability=AMBIGUOUS (모호한 질문) → 어떤 슬롯을 정답으로 볼지 확인")
        if not cur.get("parsed", True):
            flags.append("지금 결과: HCX 응답을 읽지 못함")
        if cur.get("valid_log"):
            flags.append(f"지금 결과: 2-4 검증에서 고친 내역 {len(cur['valid_log'])}건")
        if not empty and not cur.get("rewritten"):
            flags.append("지금 결과: 빈 문장")
        if ref_subs is not None and len(ref_subs) != len(subs):
            flags.append(f"정답 참고의 하위 질문 {len(ref_subs)}개 ↔ 초안 {len(subs)}개")
        if ref_filters:
            rs = ref_filters_to_slots(ref_filters)
            for k in ("시점", "지역"):
                if k in rs and set(rs[k]) != set(slots.get(k, [])):
                    flags.append(f"정답 참고 {k} {rs[k]} ↔ 초안 {slots.get(k, [])}")
            for ind in rs.get("지표·대상", []):
                if not any(ind.replace(" ", "") in v.replace(" ", "") for v in slots.get("지표", []) + slots.get("대상", [])):
                    flags.append(f"정답 참고 지표 '{ind}' 가 초안 대상·지표에 없음")

        items.append({
            "id": qid,
            "question": question,
            "meta": {                                           # 집계·참고용 (재작성 입력 아님)
                "survey": row.get("survey"), "test_type": row.get("test_type"),
                "answerability": answerability, "view_complexity": get("view_complexity"),
                "ref_pass_criteria": get("pass_criteria"), "ref_expected_intent": get("expected_intent"),
                "ref_expected_filters": ref_filters, "ref_expected_sub_questions": ref_subs,
            },
            "expect_empty": empty,                              # True면 정답 = 슬롯이 비어야 함
            "terms": [[a, ", ".join(t)] for a, t in cur["term_hits"]],     # 2-1 정답: [일상어, 대표 용어]
            "extract": {k: list(v) for k, v in cur["rule_found"].items()},  # 2-2 정답 (코드 추출 값)
            "slots": slots,                                     # 2-3·2-4 정답 (값마다 'A|B' 로 허용 값 여러 개)
            "intent": intent,
            "sub_questions": subs,
            "rewritten": {"must_include": [] if empty else must_include_from(slots), "must_not_include": []},
            "flags": flags,
            "status": "검토 전",
            "note": "",
        })

    gold = {"meta": {"name": "질문 재작성 정답 라벨 (평가 질문 80개)", "today": TODAY,
                     "created": datetime.now().isoformat(timespec="seconds"), "status": "draft",
                     "source_queries": QUERIES.name, "source_refs": REFS.name, "source_trace": TRACE.name,
                     "slot_keys": SLOT_KEYS,
                     "rules": {"exact": ["시점", "지역", "전출지", "전입지", "국적", "성별", "연령", "조건", "이동", "비교축"],
                               "any_of": ["대상", "지표"],
                               "alt_sep": "|",
                               "note": "정확 슬롯은 값 집합이 같아야 맞음. 대상·지표는 정답 값마다 허용 값 중 하나가 있으면 맞음. 'A|B' = A 또는 B"}},
            "items": items}
    text = json.dumps(gold, ensure_ascii=False, indent=1, default=str)
    OUT_JSON.write_text(text, encoding="utf-8")
    OUT_JS.parent.mkdir(exist_ok=True)
    OUT_JS.write_text("window.GOLD_DRAFT = " + text + ";\n", encoding="utf-8")

    n_flag = sum(1 for it in items if it["flags"])
    print(f"초안 {len(items)}개 | 슬롯이 비어야 함 {sum(it['expect_empty'] for it in items)}개 | 확인 필요 표시 {n_flag}개")
    print(f"저장: {OUT_JSON}\n저장: {OUT_JS}")


if __name__ == "__main__":
    main()
