"""
[NEW] 80문항 파이프라인 검수 — 자동 실행(JSON) → 검수 카드(HTML/PNG) → 사람 판정(JSON+CSV)

구 eval/golden_set/kosis_fast_human_review_accum.ipynb 와 같은 2단계 방식을 새 파이프라인(POST /api/v1/chat 과 같은
backend.agent.light_agent.run_chat)에 맞춘 것. 결과 JSON 형식은 그 노트북과 같아서 eval/review_app.py 로 그대로 열린다.

  [Phase 1] 자동 실행   질문마다 ① 재작성 → ② 검색·View → ③ 답변, 5대 지표 자동 채점(초안)
                       → <run>/auto_results.json (전체) + json/Q001.json (문항별)   ※ 중간에 멈춰도 이어서
  [Phase 2] 사람 검수   카드 보기 → 지표·최종 판정·코멘트 입력 → auto_results.json + human_final.csv 저장
                       방법 A: review_80.ipynb (QID 바꿔 가며 실행)   방법 B: streamlit run eval/review_app.py
  카드                  cards/Q001.html (항상) + cards/Q001.png (playwright 또는 html2image 가 있으면)

입력  config.TEST_DATA_DIR (기본 storage/test_data) 의 평가 질문 파일 — **코드 수정 없이 파일만 넣으면 됨**
      - 형식: .csv / .jsonl / .json / .xlsx
      - 질문 열만 있으면 됨. 열 이름은 별칭으로 찾음 (COLUMN_ALIASES: question|query|질문 …, id|qid|문항 …)
        id 가 없거나 겹치면 Q001… 자동 부여, 나머지 열(pass_criteria, gold_table_ids …)은 정답 참고로 사용
      - 이름에 ref / answer / 정답 이 들어간 파일 = 정답 참고 파일 → 이름이 같은 질문 파일에 id 로 결합
        (예: kosis_rag_eval_80_queries.csv ↔ kosis_rag_eval_80_answers_references.csv)
출력  config.EVAL_RUNS_DIR / <질문 파일 이름>/   (예: storage/eval_runs/kosis_rag_eval_80_queries/)
      테스트 세트마다 폴더가 따로 생기고, run_meta.json 에 어떤 파일·설정으로 돌렸는지 기록

CLI (저장소 루트에서)
  python eval/pipeline_review/review_80.py list                      # 찾은 테스트 세트·열 매핑·진행 현황
  python eval/pipeline_review/review_80.py run --queries 80 --n 5    # 이름 일부/번호/경로로 선택, 앞 5문항
  python eval/pipeline_review/review_80.py run --queries 80          # 전체, 이어서 실행
  python eval/pipeline_review/review_80.py run --all                 # 모든 테스트 세트
  python eval/pipeline_review/review_80.py run --queries 11 --ids Q001 --force
  python eval/pipeline_review/review_80.py cards --queries 80 --png  # 카드 다시 만들기
  python eval/pipeline_review/review_80.py summary --queries 80
"""
import argparse
import html
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.config import EVAL_RUNS_DIR, KOSIS_DATA_DIR, TEST_DATA_DIR  # noqa: E402
from backend.core.utils import safe  # noqa: E402

METRICS = ["검색_적합성", "원본_수치_추출", "Context_충분성", "변화율_응답_완성도", "자동_환각_검증"]   # review_app.py 와 같은 이름
GRADES = ("PASS", "PARTIAL", "FAIL")
DEFAULT_TODAY = "2026-11-02"            # 평가셋 기준일 (작년·최근 N년 해석 고정)

# 답이 '없다/할 수 없다' 여야 맞는 유형
NEGATIVE_TYPES = {"OUT_OF_SCOPE", "OUT_OF_DOMAIN", "PRIVACY", "PROMPT_INJECTION", "CONTRADICTORY", "NOT_YET", "LIMITS"}
NEGATIVE_ANSWERABILITY = {"OUT_OF_SCOPE", "UNANSWERABLE"}
# 변화량·비율 계산이 필요한 유형 (질문 문구로도 판단)
CHANGE_TYPES = {"CHANGE", "RATIO", "LONG_TREND", "CALC", "TIME_SHIFT", "NET", "COMPARISON", "AGE_SHARE", "NESTED"}
CHANGE_Q = re.compile(r"차이|늘었|줄었|늘어|줄어|변화|증감|올라|내려|비교|퍼센트|%|비중|추이")
CHANGE_A = re.compile(r"증가|감소|늘|줄|차이|%|퍼센트|포인트|변화|높|낮|많|적")
REFUSE_A = re.compile(r"없습니다|어렵습니다|확인할 수 없|제공하지 않|범위|개인|식별|추계|아직|불가")
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


# ═════════════════════════════ 경로 ═════════════════════════════
class RunPaths:
    def __init__(self, name, base=None):
        self.dir = Path(base or EVAL_RUNS_DIR) / name
        self.auto = self.dir / "auto_results.json"
        self.final_csv = self.dir / "human_final.csv"
        self.json_dir = self.dir / "json"
        self.card_dir = self.dir / "cards"

    def __repr__(self):
        return f"RunPaths({self.dir})"


# ═════════════════════════════ 입력 (테스트 세트 자동 탐색) ═════════════════════════════
DATA_EXT = (".csv", ".jsonl", ".json", ".xlsx")
REF_NAME = re.compile(r"ref|answer|정답", re.I)        # 이 단어가 이름에 있으면 정답 참고 파일
# 표준 열 이름 ← 별칭 (소문자·공백/_ 무시하고 비교). 새 파일의 열 이름이 다르면 여기에 별칭만 추가
COLUMN_ALIASES = {
    "id": ["id", "qid", "question_id", "문항", "문항id", "번호", "no"],
    "question": ["question", "query", "user_question", "질문", "질의", "q"],
    "survey": ["survey", "survey_nm", "조사", "조사명", "통계명"],
    "test_type": ["test_type", "type", "유형", "테스트유형", "category"],
    "target_modules": ["target_modules", "target_module", "modules", "모듈", "대상모듈"],
}


def _key(c):
    return re.sub(r"[\s_\-]+", "", str(c)).lower()


def read_table(path):
    """csv(utf-8 → cp949) / jsonl / json / xlsx → DataFrame(문자열)"""
    path = Path(path)
    suf = path.suffix.lower()
    if suf == ".csv":
        try:
            df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(path, dtype=str, encoding="cp949")      # 엑셀에서 저장한 CSV
    elif suf == ".jsonl":
        df = pd.DataFrame([json.loads(l) for l in path.read_text(encoding="utf-8-sig").splitlines() if l.strip()])
    elif suf == ".json":
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        df = pd.DataFrame(obj if isinstance(obj, list) else obj.get("items") or obj.get("questions") or [])
    elif suf == ".xlsx":
        df = pd.read_excel(path, dtype=str)
    else:
        raise ValueError(f"지원하지 않는 형식: {path.name}")
    return df.fillna("").astype(str)


def column_map(columns):
    """{표준 이름: 실제 열 이름}"""
    keys = {_key(c): c for c in columns}
    return {std: next(keys[_key(a)] for a in al if _key(a) in keys)
            for std, al in COLUMN_ALIASES.items() if any(_key(a) in keys for a in al)}


def _base(stem):
    return re.sub(r"[_\-]*(queries|query|questions|question|질문)$", "", stem, flags=re.I)


def find_test_sets(test_dir=None):
    """TEST_DATA_DIR 의 평가 질문 파일 목록 [{path, name, n, columns, refs, run}]  (정답 참고 파일은 짝지어 붙임)"""
    d = Path(test_dir or TEST_DATA_DIR)
    if not d.exists():
        return []
    files = sorted(f for f in d.iterdir() if f.suffix.lower() in DATA_EXT and not f.name.startswith(("~$", ".")))
    refs = [f for f in files if REF_NAME.search(f.stem)]
    out = []
    for f in files:
        if f in refs:
            continue
        try:
            df = read_table(f)
        except Exception as e:  # noqa: BLE001
            out.append({"path": f, "name": f.stem, "error": f"{e.__class__.__name__}: {e}"})
            continue
        cm = column_map(df.columns)
        if "question" not in cm:
            out.append({"path": f, "name": f.stem, "error": f"질문 열 없음 (열: {list(df.columns)[:8]} — COLUMN_ALIASES 에 추가)"})
            continue
        base = _base(f.stem)
        ref = next((r for r in refs if r.stem.startswith(base) or _base(r.stem).startswith(base)), None)
        out.append({"path": f, "name": f.stem, "n": len(df), "columns": cm, "refs": ref,
                    "extra": [c for c in df.columns if c not in cm.values()], "run": RunPaths(f.stem)})
    return out


def resolve_test_set(spec=None, test_dir=None):
    """spec = None(하나뿐이면 그것) | 번호(1부터) | 파일 이름 일부 | 경로 → test set dict"""
    if spec and Path(spec).is_file():
        f = Path(spec)
        sets = [s for s in find_test_sets(f.parent) if s["path"] == f]
        if sets:
            return sets[0]
    sets = [s for s in find_test_sets(test_dir) if "error" not in s]
    if not sets:
        raise FileNotFoundError(f"평가 질문 파일이 없습니다: {test_dir or TEST_DATA_DIR} (.csv/.jsonl/.json/.xlsx, 질문 열 필요)")
    if spec is None:
        if len(sets) == 1:
            return sets[0]
        raise ValueError("테스트 세트가 여러 개입니다. --queries 로 고르세요: "
                         + ", ".join(f"[{i}] {s['name']}" for i, s in enumerate(sets, 1)))
    if str(spec).isdigit() and 1 <= int(spec) <= len(sets) and not any(str(spec) in s["name"] for s in sets):
        return sets[int(spec) - 1]
    hit = [s for s in sets if str(spec) == s["name"]] or [s for s in sets if str(spec) in s["name"]]
    if len(hit) != 1:
        raise ValueError(f"'{spec}' 에 맞는 테스트 세트 {len(hit)}개: {[s['name'] for s in hit] or [s['name'] for s in sets]}")
    return hit[0]


def load_questions(queries=None, test_dir=None):
    """평가 질문 → [dict(id, survey, test_type, target_modules, question, reference)]
    queries = None | 번호 | 이름 일부 | 경로 (resolve_test_set 참고)"""
    ts = resolve_test_set(queries, test_dir)
    df = read_table(ts["path"])
    cm = ts["columns"]
    ref_by_id = {}
    if ts.get("refs"):
        rdf = read_table(ts["refs"])
        rid = column_map(rdf.columns).get("id", rdf.columns[0])
        ref_by_id = {r[rid]: {k: v for k, v in r.items() if k != rid and v != ""} for r in rdf.to_dict(orient="records")}
    items, seen = [], set()
    for i, r in enumerate(df.to_dict(orient="records"), 1):
        q = r[cm["question"]].strip()
        if not q:
            continue
        qid = r.get(cm.get("id", ""), "").strip()
        if not qid or qid in seen:
            qid = f"Q{i:03d}"
        seen.add(qid)
        extra = {k: v for k, v in r.items() if k not in cm.values() and v != ""}     # 남는 열 = 정답 참고
        items.append({"id": qid, "question": q,
                      "survey": r.get(cm.get("survey", ""), "") or "", "test_type": r.get(cm.get("test_type", ""), "") or "-",
                      "target_modules": r.get(cm.get("target_modules", ""), "") or "",
                      "reference": {**extra, **ref_by_id.get(qid, {})}})
    return items


def run_for(queries=None, test_dir=None):
    """테스트 세트 → 결과 폴더 (storage/eval_runs/<질문 파일 이름>)"""
    return resolve_test_set(queries, test_dir)["run"]


def expected_tables(ref):
    """정답 참고 CSV 에 표 ID 열(이름에 'tbl' 포함)이 있으면 그 값들"""
    out = set()
    for k, v in (ref or {}).items():
        if "tbl" in k.lower():
            out |= {x for x in re.split(r"[\s,;|]+", str(v)) if x}
    return out


def pass_criteria_of(item):
    ref = item.get("reference") or {}
    for k in ("pass_criteria", "통과기준", "통과_기준", "expected_answer", "gold_answer"):
        if ref.get(k):
            return ref[k]
    if ref:
        return " · ".join(f"{k}={v}" for k, v in list(ref.items())[:6])[:400]
    return f"[{item['test_type']}] 질문 조건(시점·지역·항목)에 맞는 수치·단위·출처 제시 (정답 참고 CSV 없음)"


def is_negative(item):
    ans = str((item.get("reference") or {}).get("answerability", "")).upper()
    return item["test_type"] in NEGATIVE_TYPES or ans in NEGATIVE_ANSWERABILITY


# ═════════════════════════════ Phase 1: 실행 + 자동 채점 ═════════════════════════════
def _nospace(s):
    return re.sub(r"\s+", "", str(s or ""))


def _titles(out):
    return {v["record"]["id"]: c["tbl_nm"] for u in out["views"]["units"] for v in u["views"]
            for c in u["candidates"] if c["tbl_id"] == v["tbl_id"]}


def _rec_notes(out):
    return {v["record"]["id"]: v["notes"] for u in out["views"]["units"] for v in u["views"]}


def _unit_filters(out):
    return {v["record"]["id"]: u.get("filters") for u in out["views"]["units"] for v in u["views"]}


def score(item, out):
    """새 파이프라인 결과 → (지표, 근거). 자동 채점은 초안이고 최종은 사람이 정한다"""
    res, recs = out["result"], out["records"]
    by_id = {r["id"]: r for r in recs}
    notes = _rec_notes(out)
    used = [by_id[u] for u in res.get("used_ids", []) if u in by_id]
    ans = " ".join([res.get("answer", ""), res.get("summary", "")] + list(res.get("key_points") or []))
    nums = [n for n in NUM_RE.findall(ans) if len(n.replace(",", "").replace(".", "")) >= 1]
    unver = res.get("unverified_numbers") or []
    insufficient = bool(res.get("insufficient"))
    neg = is_negative(item)
    has_rows = lambda r: bool((r.get("table") or {}).get("rows"))  # noqa: E731
    m, why = {}, {}

    # 1) 검색_적합성 — 기대 조사(또는 정답 표)가 답변 근거/검색 후보에 있는가
    exp_tbl = expected_tables(item.get("reference"))
    exp_survey = _nospace(item.get("survey"))
    cands = [c for u in out["views"]["units"] for c in u["candidates"]]
    if neg:
        m["검색_적합성"], why["검색_적합성"] = ("PASS", "범위 밖 질문 — 검색 결과와 무관하게 답변 태도로 판단") if insufficient \
            else ("PARTIAL", "범위 밖 질문인데 검색 자료로 답함")
    elif exp_tbl:
        hit_used = [r["source"]["tbl_id"] for r in used if r["source"]["tbl_id"] in exp_tbl]
        hit_cand = [c["tbl_id"] for c in cands if c["tbl_id"] in exp_tbl]
        m["검색_적합성"], why["검색_적합성"] = ("PASS", f"정답 표 {hit_used} 를 근거로 사용") if hit_used else \
            ("PARTIAL", f"정답 표 {hit_cand} 가 후보에는 있으나 근거로 쓰이지 않음") if hit_cand else \
            ("FAIL", f"정답 표 {sorted(exp_tbl)} 가 후보 {len(cands)}개에 없음")
    elif exp_survey and "교차" not in exp_survey:
        su = [r for r in used if exp_survey in _nospace((r.get("metadata") or {}).get("survey_nm"))]
        sc = [c for c in cands if exp_survey in _nospace(c.get("survey_nm"))]
        m["검색_적합성"], why["검색_적합성"] = ("PASS", f"기대 조사 '{item['survey']}' 표를 근거로 사용") if su else \
            ("PARTIAL", f"기대 조사 표가 후보 {len(sc)}개 있으나 근거로 쓰이지 않음") if sc else \
            ("FAIL", f"기대 조사 '{item['survey']}' 표가 후보 {len(cands)}개에 없음")
    else:
        m["검색_적합성"], why["검색_적합성"] = ("PASS", "교차 문항 — 자료 확보") if any(has_rows(r) for r in recs) else \
            ("FAIL", "교차 문항 — 값이 있는 View 없음")

    # 2) 원본_수치_추출 — 근거 View 에 실제 값이 있는가
    if neg:
        m["원본_수치_추출"], why["원본_수치_추출"] = "PASS", "범위 밖 질문 — 수치 추출 대상 아님"
    elif used and all(has_rows(r) for r in used):
        n = sum((r.get("metadata") or {}).get("n_points", 0) for r in used)
        m["원본_수치_추출"], why["원본_수치_추출"] = "PASS", f"근거 View {len(used)}개, 값 {n}개"
    elif any(has_rows(r) for r in recs):
        m["원본_수치_추출"], why["원본_수치_추출"] = "PARTIAL", "값 있는 View 는 있으나 근거 View 가 비었음"
    else:
        m["원본_수치_추출"], why["원본_수치_추출"] = "FAIL", f"값 있는 View 없음 (View {len(recs)}개)"

    # 3) Context_충분성 — 질문 조건을 View 가 다 맞췄는가 (build_view notes)
    miss = [n for r in used for n in notes.get(r["id"], [])]
    if neg:
        m["Context_충분성"], why["Context_충분성"] = ("PASS", "범위 밖 — insufficient 정상") if insufficient \
            else ("PARTIAL", "범위 밖인데 insufficient=false")
    elif used and not miss and not insufficient:
        m["Context_충분성"], why["Context_충분성"] = "PASS", "조건을 모두 맞춘 View 로 답변"
    elif used and any(has_rows(r) for r in used):
        m["Context_충분성"], why["Context_충분성"] = "PARTIAL", ("못 맞춘 조건: " + "; ".join(miss[:3])) if miss \
            else "insufficient=true (가까운 자료로 답변)"
    else:
        m["Context_충분성"], why["Context_충분성"] = "FAIL", "근거로 쓸 View 없음"

    # 4) 변화율_응답_완성도 — 유형별 답변 완성도
    if ans.startswith("[API 호출 오류"):
        m["변화율_응답_완성도"], why["변화율_응답_완성도"] = "FAIL", "API 호출 실패"
    elif neg:
        ok = insufficient or bool(REFUSE_A.search(ans))
        m["변화율_응답_완성도"], why["변화율_응답_완성도"] = ("PASS", "범위 밖 질문에 한계 안내") if ok \
            else ("FAIL", "범위 밖 질문에 수치로 답함")
    elif item["test_type"] in CHANGE_TYPES or CHANGE_Q.search(item["question"]):
        if len(nums) >= 2 and CHANGE_A.search(ans) and not unver:
            m["변화율_응답_완성도"], why["변화율_응답_완성도"] = "PASS", "비교 수치와 변화 표현 모두 있음"
        elif len(nums) >= 1:
            m["변화율_응답_완성도"], why["변화율_응답_완성도"] = "PARTIAL", "수치는 있으나 비교·변화율 일부 누락 또는 검증 안 된 계산값"
        else:
            m["변화율_응답_완성도"], why["변화율_응답_완성도"] = "FAIL", "비교 수치 없음"
    else:
        if nums and not insufficient:
            m["변화율_응답_완성도"], why["변화율_응답_완성도"] = "PASS", "요구 수치 응답"
        elif nums or insufficient:
            m["변화율_응답_완성도"], why["변화율_응답_완성도"] = "PARTIAL", "부분 응답 또는 자료 부족 안내"
        else:
            m["변화율_응답_완성도"], why["변화율_응답_완성도"] = "FAIL", "수치 없음"

    # 5) 자동_환각_검증 — 답변 숫자가 컨텍스트에 있는가 (verify_numbers)
    if ans.startswith("[API 호출 오류"):
        m["자동_환각_검증"], why["자동_환각_검증"] = "FAIL", "API 오류"
    elif not unver:
        m["자동_환각_검증"], why["자동_환각_검증"] = "PASS", "미검증 숫자 없음"
    elif len(unver) <= 2:
        m["자동_환각_검증"], why["자동_환각_검증"] = "PARTIAL", f"계산값일 수 있는 미검증 숫자: {unver}"
    else:
        m["자동_환각_검증"], why["자동_환각_검증"] = "FAIL", f"컨텍스트에 없는 숫자 다수: {unver}"

    m["자동_종합_판정"] = overall(m)
    return m, why


def overall(m):
    """review_app.rule_overall 과 같은 규칙"""
    if all(m[k] == "PASS" for k in METRICS):
        return "PASS"
    return "FAIL" if "FAIL" in (m["검색_적합성"], m["변화율_응답_완성도"]) else "PARTIAL"


def _facts(rec, n=6):
    t = rec.get("table") or {}
    cols, rows = t.get("columns") or [], t.get("rows") or []
    unit = (rec.get("metadata") or {}).get("unit") or ""
    out = []
    for r in rows[:n]:
        d = dict(zip(cols, r))
        v = d.get("값")
        label = " | ".join(str(d[c]) for c in cols if c not in ("값",))
        out.append(f"{label}: {v:,.0f} {unit}" if isinstance(v, (int, float)) else f"{label}: {v}")
    return out


def evidence(out, max_rows=30):
    """근거 View → review_app.py 가 읽는 evidence_sources 형식"""
    res, by_id = out["result"], {r["id"]: r for r in out["records"]}
    titles, notes, filters = _titles(out), _rec_notes(out), _unit_filters(out)
    order = list(dict.fromkeys([u for u in res.get("used_ids", []) if u in by_id] + list(by_id)))[:3]
    ev = []
    for rid in order:
        r = by_id[rid]
        md, src, t = r.get("metadata") or {}, r.get("source") or {}, r.get("table") or {}
        raw = KOSIS_DATA_DIR / "raw" / safe(md.get("category") or "") / f"{src.get('table_key')}.csv"
        ev.append({
            "view_id": rid, "title": titles.get(rid, src.get("tbl_id", "")), "used": rid in res.get("used_ids", []),
            "survey_nm": md.get("survey_nm", ""), "tbl_nm": titles.get(rid, ""), "tbl_id": src.get("tbl_id"),
            "prd_range": f"{md.get('prd_from')}~{md.get('prd_to')} ({md.get('prd_se')})", "unit": md.get("unit", ""),
            "kosis_url": src.get("kosis_url", ""), "raw_csv": str(raw), "csv_exists": raw.exists(),
            "applied_conditions": {k: v for k, v in (filters.get(rid) or {}).items() if v},
            "missing_conditions": notes.get(rid, []),
            "facts_summary": _facts(r),
            "condition_filtered_rows": [dict(zip(t.get("columns") or [], row)) for row in (t.get("rows") or [])[:max_rows]],
            "n_rows_total": len(t.get("rows") or []),
            "preview_rows": [], "caveats": [], "source": src,
        })
    return ev


def run_one(item, today=DEFAULT_TODAY, top_k=10, n_views=3):
    """질문 하나 → 검수용 레코드 (구 노트북 run_single_query_and_pack_evidence 와 같은 모양)"""
    from backend.agent.light_agent import record_context, run_chat
    t0 = time.time()
    base = {"id": item["id"], "survey": item["survey"], "test_type": item["test_type"],
            "target_modules": item.get("target_modules", ""), "question": item["question"],
            "pass_criteria": pass_criteria_of(item), "reference": item.get("reference") or {}}
    try:
        out = run_chat(item["question"], today, top_k, n_views)
    except (Exception, SystemExit) as e:  # noqa: BLE001  (한 문항 실패로 전체를 멈추지 않음)
        err = f"[API 호출 오류] {e.__class__.__name__}: {str(e)[:300]}"
        m = {k: "FAIL" for k in METRICS} | {"자동_종합_판정": "FAIL"}
        return {**base, "rewritten_query": "", "ai_answer": err, "ai_summary": "", "ai_key_points": [],
                "insufficient": True, "unverified_numbers": [], "auto_metrics": m,
                "auto_reasons": {k: err for k in METRICS}, "evidence_sources": [], "prompt_context_raw": "",
                "pipeline": {}, "human_review": _init_human(m), "elapsed_s": round(time.time() - t0, 2)}
    res = out["result"]
    m, why = score(item, out)
    titles, notes = _titles(out), _rec_notes(out)
    ctx = "\n\n".join(record_context(r, 40, notes.get(r["id"]), titles.get(r["id"])) for r in out["records"][:4])
    vb = out["view_bundle"]
    return {
        **base,
        "rewritten_query": vb.get("search_text") or (out.get("rewrite") or {}).get("rewritten", ""),
        "ai_answer": res["answer"], "ai_summary": res.get("summary", ""), "ai_key_points": res.get("key_points") or [],
        "insufficient": bool(res.get("insufficient")), "unverified_numbers": res.get("unverified_numbers") or [],
        "auto_metrics": m, "auto_reasons": why,
        "evidence_sources": evidence(out),
        "prompt_context_raw": ctx,
        "pipeline": {    # 모듈별로 어디서 틀렸는지 보기 위한 단계 결과
            "rewrite": out.get("rewrite"), "view_filters": vb.get("filters"), "search_text": vb.get("search_text"),
            "sub_questions": vb.get("sub_questions"), "notes": out.get("notes"), "timings": out.get("timings"),
            "candidates": [{"unit": u["unit_id"], "rank": c["rank"], "tbl_id": c["tbl_id"], "tbl_nm": c["tbl_nm"],
                            "survey_nm": c["survey_nm"], "score": c["score"], "bm25_rank": c.get("bm25_rank"),
                            "has_view": c["has_view"]} for u in out["views"]["units"] for c in u["candidates"]],
            "chart": res.get("chart"), "sources": res.get("sources"),
        },
        "human_review": _init_human(m),
        "elapsed_s": round(time.time() - t0, 2),
    }


def _init_human(m):
    return {**{k: m[k] for k in METRICS}, "최종_HUMAN_평가": m["자동_종합_판정"], "human_comment": "", "reviewed": False}


def load_results(run):
    return {r["id"]: r for r in json.loads(run.auto.read_text(encoding="utf-8"))} if run.auto.exists() else {}


def save_results(run, data):
    """auto_results.json + json/<id>.json + human_final.csv 를 한 번에 저장"""
    run.dir.mkdir(parents=True, exist_ok=True)
    run.json_dir.mkdir(exist_ok=True)
    ordered = [data[k] for k in sorted(data)]
    run.auto.write_text(json.dumps(ordered, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for r in ordered:
        (run.json_dir / f"{r['id']}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2, default=str),
                                                      encoding="utf-8")
    rows = []
    for r in ordered:
        hm, ev0 = r["human_review"], (r.get("evidence_sources") or [{}])[0]
        rows.append({"id": r["id"], "survey": r["survey"], "test_type": r["test_type"],
                     "target_modules": r.get("target_modules", ""), "question": r["question"],
                     "rewritten_query": r.get("rewritten_query", ""), "ai_answer": r["ai_answer"],
                     "근거_표": ev0.get("tbl_nm", ""), "근거_Facts_요약": " | ".join(ev0.get("facts_summary", [])),
                     "KOSIS_링크": ev0.get("kosis_url", ""),
                     **{f"자동_{k}": r["auto_metrics"][k] for k in METRICS},
                     **{k: hm[k] for k in METRICS}, "자동_종합_판정": r["auto_metrics"]["자동_종합_판정"],
                     "최종_HUMAN_평가": hm["최종_HUMAN_평가"], "human_comment": hm.get("human_comment", ""),
                     "reviewed": hm.get("reviewed", False), "elapsed_s": r.get("elapsed_s")})
    pd.DataFrame(rows).to_csv(run.final_csv, index=False, encoding="utf-8-sig")


def run_batch(run=None, ids=None, n=None, force=False, today=DEFAULT_TODAY, top_k=10, n_views=3, png=True,
              test_dir=None, log=print, queries=None):
    """테스트 세트 자동 실행. 이미 성공한 문항은 건너뜀(force=True 면 다시). 사람 판정은 다시 실행해도 유지
    queries = 테스트 세트 (None | 번호 | 이름 일부 | 경로), run = 결과 폴더 (None 이면 질문 파일 이름)"""
    ts = resolve_test_set(queries, test_dir)
    run = run or ts["run"]
    items = load_questions(str(ts["path"]))
    run.dir.mkdir(parents=True, exist_ok=True)
    (run.dir / "run_meta.json").write_text(json.dumps({
        "queries_file": str(ts["path"]), "refs_file": str(ts["refs"]) if ts.get("refs") else None,
        "n_questions": len(items), "columns": ts["columns"], "today": today, "top_k": top_k, "n_views": n_views,
        "updated": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"테스트 세트: {ts['path'].name} ({len(items)}문항)" + (f" + 정답 참고 {ts['refs'].name}" if ts.get("refs") else "")
        + f" → {run.dir}")
    if ids:
        items = [it for it in items if it["id"] in set(ids)]
    if n:
        items = items[:n]
    data = load_results(run)
    t0 = time.time()
    for i, it in enumerate(items, 1):
        old = data.get(it["id"])
        if old and not force and not str(old.get("ai_answer", "")).startswith("[API 호출 오류"):
            continue
        rec = run_one(it, today, top_k, n_views)
        if old and old["human_review"].get("reviewed"):          # 사람이 이미 본 판정은 보존
            rec["human_review"] = old["human_review"]
        data[it["id"]] = rec
        save_results(run, data)
        write_card(run, rec, png=png)
        mm = rec["auto_metrics"]
        log(f"[{i:02d}/{len(items)}] {it['id']} {it['test_type']:<14} 검색:{mm['검색_적합성']:<7} 추출:{mm['원본_수치_추출']:<7} "
            f"Ctx:{mm['Context_충분성']:<7} 완성:{mm['변화율_응답_완성도']:<7} 환각:{mm['자동_환각_검증']:<7} "
            f"→ {mm['자동_종합_판정']} ({rec['elapsed_s']}s)")
    log(f"완료: {len(data)}문항 저장 ({time.time() - t0:.0f}s) → {run.auto}")
    return data


# ═════════════════════════════ Phase 2: 사람 판정 ═════════════════════════════
def set_verdict(run, qid, final=None, comment=None, png=True, **details):
    """사람 판정 저장 + 카드 다시 그림. details 키 = METRICS 이름 (예: 검색_적합성="PARTIAL")"""
    data = load_results(run)
    hm = data[qid]["human_review"]
    for k, v in details.items():
        if k not in METRICS:
            raise KeyError(f"지표 이름은 {METRICS} 중 하나: {k}")
        if v is not None:
            if v not in GRADES:
                raise ValueError(f"{k}: {v} → {GRADES} 중 하나")
            hm[k] = v
            hm["reviewed"] = True
    if final is not None:
        if final not in GRADES:
            raise ValueError(f"final: {final} → {GRADES} 중 하나")
        hm["최종_HUMAN_평가"] = final
        hm["reviewed"] = True
    if comment is not None:
        hm["human_comment"] = comment
        hm["reviewed"] = True
    save_results(run, data)
    write_card(run, data[qid], png=png)      # 카드에도 사람 판정·코멘트 반영
    return data[qid]


def summary_df(run):
    data = load_results(run)
    return pd.DataFrame([{"id": r["id"], "조사": r["survey"], "유형": r["test_type"], "질문": r["question"][:50],
                          **{k.split("_")[0]: r["human_review"][k] for k in METRICS},
                          "자동": r["auto_metrics"]["자동_종합_판정"], "최종": r["human_review"]["최종_HUMAN_평가"],
                          "검수": "✅" if r["human_review"].get("reviewed") else "⏳", "초": r.get("elapsed_s")}
                         for r in (data[k] for k in sorted(data))])


# ═════════════════════════════ 카드 (HTML / PNG) ═════════════════════════════
COLORS = {"PASS": ("#d4edda", "#155724"), "PARTIAL": ("#fff3cd", "#856404"), "FAIL": ("#f8d7da", "#721c24")}


def _badge(v):
    bg, fg = COLORS.get(v, ("#e2e8f0", "#000"))
    return f'<span style="background:{bg};color:{fg};font-weight:700;padding:2px 8px;border-radius:6px">{html.escape(str(v))}</span>'


def _esc(x):
    return html.escape("" if x is None else str(x))


def _table(rows, limit=15):
    if not rows:
        return "<div style='color:#666'>표 데이터 없음</div>"
    cols = list(rows[0])
    th = "".join(f"<th>{_esc(c)}</th>" for c in cols)
    tr = "".join("<tr>" + "".join(f"<td>{_esc(f'{v:,.0f}' if isinstance(v, float) and v.is_integer() else v)}</td>"
                                  for v in r.values()) + "</tr>" for r in rows[:limit])
    more = f"<div style='color:#666;font-size:12px'>… 외 {len(rows) - limit}행</div>" if len(rows) > limit else ""
    return f"<table class='t'><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>{more}"


def card_html(rec):
    """검수 카드 한 장 (독립 HTML, 흰 배경·검은 글씨, 폭 960px)"""
    hm, am, ar, p = rec["human_review"], rec["auto_metrics"], rec["auto_reasons"], rec.get("pipeline") or {}
    ans = _esc(rec["ai_answer"])
    for nn in sorted(set(rec.get("unverified_numbers") or []), key=len, reverse=True):
        ans = ans.replace(_esc(nn), f"<mark>{_esc(nn)}</mark>")
    metric_rows = "".join(f"<tr><td>{i}. {k.replace('_', ' ')}</td><td>{_badge(am[k])}</td><td>{_badge(hm[k])}</td>"
                          f"<td>{_esc(ar.get(k, ''))}</td></tr>" for i, k in enumerate(METRICS, 1))
    rw = p.get("rewrite") or {}
    pipe = (f"<div><b>① 재작성</b> {_esc(rw.get('rewritten'))} <span class='g'>intent={_esc(rw.get('intent'))}</span></div>"
            f"<div><b>② View 조건</b> <code>{_esc(json.dumps(p.get('view_filters'), ensure_ascii=False))}</code></div>"
            + (f"<div><b>하위 질문</b> {_esc(p.get('sub_questions'))}</div>" if p.get("sub_questions") else "")
            + f"<div class='g'>검색 문장: {_esc(p.get('search_text'))} · 소요 {_esc(p.get('timings'))}</div>")
    cand = "".join(f"<tr><td>{c['unit']}</td><td>{c['rank']}</td><td>{_esc(c['survey_nm'])}</td><td>{_esc(c['tbl_nm'])}</td>"
                   f"<td>{c['tbl_id']}</td><td>{c['score']}</td><td>{c.get('bm25_rank')}</td><td>{'●' if c['has_view'] else ''}</td></tr>"
                   for c in (p.get("candidates") or [])[:10])
    evs = ""
    for i, ev in enumerate(rec.get("evidence_sources") or [], 1):
        warn = (f"<div class='w'>⚠ 못 맞춘 조건: {_esc('; '.join(ev['missing_conditions']))}</div>"
                if ev.get("missing_conditions") else "")
        evs += (f"<div class='box'><div><b>#{i} {'[근거] ' if ev.get('used') else ''}{_esc(ev['title'])}</b> "
                f"<span class='g'>{_esc(ev['survey_nm'])} · {_esc(ev['tbl_id'])} · {_esc(ev['prd_range'])} · 단위 {_esc(ev['unit'] or '-')}"
                f" · 행 {ev.get('n_rows_total')}</span></div>"
                f"<div class='g'>{_esc(ev['kosis_url'])}</div>{warn}"
                f"<div class='g'>적용 조건: {_esc(json.dumps(ev.get('applied_conditions'), ensure_ascii=False))}</div>"
                f"{_table(ev.get('condition_filtered_rows'))}</div>")
    st = "✅ 검수완료" if hm.get("reviewed") else "⏳ 자동초안"
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
.card{{width:960px;padding:20px 24px;font-family:'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif;
color:#000;font-size:14px;line-height:1.5;background:#fff;text-align:left}} .card h2{{margin:0 0 8px;font-size:19px;color:#000}}
.card .box{{border:1px solid #cbd5e1;border-radius:8px;padding:10px 12px;margin:8px 0}} .card .g{{color:#444;font-size:12.5px}}
.card .w{{background:#fff7ed;border:1px solid #fdba74;padding:4px 8px;border-radius:6px;margin:4px 0}}
.card table.t,.card table.m{{border-collapse:collapse;width:100%;margin-top:6px;font-size:12.5px}}
.card .t th,.card .t td,.card .m th,.card .m td{{border:1px solid #cbd5e1;padding:3px 6px;text-align:left;color:#000;background:#fff}}
.card .t th,.card .m th{{background:#f1f5f9}} .card mark{{background:#fecaca}} .card code{{font-size:12px;color:#000}}
/* 노트북(다크 테마 포함)에 그대로 표시해도 다른 셀에 영향 없도록 모든 규칙을 .card 안으로 한정 */
</style></head><body><div class="card">
<h2>[{_esc(rec['id'])}] {_esc(rec['survey'])} <code>{_esc(rec['test_type'])}</code> {_badge(hm['최종_HUMAN_평가'])} <span class='g'>{st} · 자동 {_esc(am['자동_종합_판정'])}</span></h2>
<div class="box"><b>❓ 질문</b> {_esc(rec['question'])}<div class='g'>🎯 통과 기준: {_esc(rec.get('pass_criteria'))}</div></div>
<div class="box">{pipe}</div>
<div class="box"><b>🤖 답변</b> <span class='g'>insufficient={rec['insufficient']} · 미검증 숫자={_esc(rec.get('unverified_numbers'))}</span><div>{ans}</div>
<div class='g'>핵심 수치: {_esc(', '.join(rec.get('ai_key_points') or []))}</div></div>
<table class="m"><thead><tr><th>지표</th><th>자동</th><th>HUMAN</th><th>자동 진단 근거</th></tr></thead><tbody>{metric_rows}</tbody></table>
{('<div class="box"><b>💬 코멘트</b> ' + _esc(hm.get('human_comment')) + '</div>') if hm.get('human_comment') else ''}
<div class="box"><b>🔎 검색 후보</b><table class="t"><thead><tr><th>단위</th><th>순위</th><th>조사</th><th>표</th><th>ID</th><th>점수</th><th>BM25</th><th>View</th></tr></thead><tbody>{cand}</tbody></table></div>
<div><b>📂 근거 View</b>{evs or "<div class='g'>없음</div>"}</div>
</div></body></html>"""


def _png_playwright(html_text, out_png):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1010, "height": 600}, device_scale_factor=1.5)
        pg.set_content(html_text)
        pg.locator(".card").screenshot(path=str(out_png))   # 카드 전체 높이 그대로
        b.close()
    return out_png


def _png(html_text, out_png):
    """playwright → html2image 순으로 시도. 둘 다 없으면 None
    playwright 동기 API 는 Jupyter(이벤트 루프 실행 중)에서 바로 못 써서 별도 스레드에서 실행"""
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(1) as ex:
            return ex.submit(_png_playwright, html_text, out_png).result(timeout=60)
    except Exception:  # noqa: BLE001
        pass
    try:
        from html2image import Html2Image
        h = max(900, 26 * html_text.count("<tr>") + 120 * html_text.count("class='box'") + 600)
        hti = Html2Image(output_path=str(out_png.parent), size=(1010, h))
        hti.screenshot(html_str=html_text, save_as=out_png.name)
        return out_png
    except Exception:  # noqa: BLE001
        return None


def write_card(run, rec, png=True):
    run.card_dir.mkdir(parents=True, exist_ok=True)
    h = card_html(rec)
    hp = run.card_dir / f"{rec['id']}.html"
    hp.write_text(h, encoding="utf-8")
    return hp, (_png(h, run.card_dir / f"{rec['id']}.png") if png else None)


def write_cards(run, ids=None, png=True, log=print):
    data = load_results(run)
    made = 0
    for k in sorted(data):
        if ids and k not in ids:
            continue
        _, p = write_card(run, data[k], png)
        made += p is not None
    log(f"카드 {len(data) if not ids else len(ids)}장 HTML, PNG {made}장 → {run.card_dir}")


# ═════════════════════════════ CLI ═════════════════════════════
def list_sets(test_dir=None, log=print):
    sets = find_test_sets(test_dir)
    log(f"테스트 세트 폴더: {test_dir or TEST_DATA_DIR}")
    for i, t in enumerate(sets, 1):
        if "error" in t:
            log(f"  [-] {t['path'].name}: {t['error']}")
            continue
        done = load_results(t["run"])
        rv_ = sum(bool(r["human_review"].get("reviewed")) for r in done.values())
        log(f"  [{i}] {t['path'].name}  {t['n']}문항  열={t['columns']}"
            + (f"  정답참고={t['refs'].name}" if t.get("refs") else "")
            + (f"  정답 참고 열={t['extra']}" if t.get("extra") else "")
            + f"  | 실행 {len(done)}/{t['n']} · 검수 {rv_}")
    return sets


def main():
    ap = argparse.ArgumentParser(description="평가 질문 세트 파이프라인 검수 (storage/test_data 자동 탐색)")
    ap.add_argument("cmd", choices=["list", "run", "cards", "summary"])
    ap.add_argument("--queries", help="테스트 세트: 번호 | 파일 이름 일부 | 경로 (하나뿐이면 생략)")
    ap.add_argument("--all", action="store_true", help="run: 모든 테스트 세트")
    ap.add_argument("--test-dir", default=None, help="평가 질문 폴더 (기본 config.TEST_DATA_DIR)")
    ap.add_argument("--run", default=None, help="결과 폴더 이름 (기본: 질문 파일 이름). 설정을 바꿔 비교할 때 지정")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--n", type=int)
    ap.add_argument("--force", action="store_true", help="이미 실행한 문항도 다시 (사람 판정은 유지)")
    ap.add_argument("--today", default=DEFAULT_TODAY)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--n-views", type=int, default=3)
    ap.add_argument("--png", action="store_true", help="cards: PNG 도 만들기 (run 은 기본으로 만듦)")
    ap.add_argument("--no-png", action="store_true", help="run: PNG 만들지 않기 (빠름)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if a.cmd == "list":
        list_sets(a.test_dir)
        return
    if a.cmd == "run" and a.all:
        for t in [t for t in find_test_sets(a.test_dir) if "error" not in t]:
            run_batch(None, a.ids, a.n, a.force, a.today, a.top_k, a.n_views, png=not a.no_png,
                      test_dir=a.test_dir, queries=str(t["path"]))
        return
    try:
        ts = resolve_test_set(a.queries, a.test_dir)
    except (ValueError, FileNotFoundError) as e:     # 세트를 못 고르면 목록을 보여 주고 끝냄
        print(f"✗ {e}\n")
        list_sets(a.test_dir)
        sys.exit(2)
    run = RunPaths(a.run) if a.run else ts["run"]
    if a.cmd == "run":
        run_batch(run, a.ids, a.n, a.force, a.today, a.top_k, a.n_views, png=not a.no_png,
                  test_dir=a.test_dir, queries=str(ts["path"]))
    elif a.cmd == "cards":
        write_cards(run, a.ids, png=a.png)
    else:
        df = summary_df(run)
        print(df.to_string(index=False))
        print(df["최종"].value_counts().to_string())


if __name__ == "__main__":
    main()
