"""
가벼운 단일 Agent  (구 kosis_rag_qa.py 의 답변·조건 적용·CLI 부분)

[CHANGED] kosis_rag_qa.py (820행) 를 역할별로 나눔 — 함수 본문은 그대로, import 만 바뀜
  HCX chat / 임베딩            → backend/core/llm.py
  tokenize (Kiwi BM25 토큰)    → backend/rag/retrieval/lexical.py
  load_records / stage_index   → backend/rag/ingestion/indexer.py
  Index (BM25+Dense→RRF)       → backend/rag/retrieval/fusion.py
  REWRITE_* / ANSWER_* 프롬프트 → backend/agent/prompts.py
  나머지(rewrite, answer, apply_conditions, CLI) → 이 파일
[NEW] 맨 아래 '통합 파이프라인' : 질의 재작성(query_analyzer) → View 검색·생성(ingestion.views) → Record 기반 답변
      = POST /api/v1/chat  (기존 answer() 는 legacy 경로 POST /api/v1/chat/legacy 로 그대로 사용)
[CHANGED] 실행: python -m backend.agent.light_agent <stage> ...   (이전: python kosis_rag_qa.py <stage> ...)

── 이하 원래 설명 (경로 kosis_data/... 는 config 의 동적 경로로 바뀜) ──
KOSIS 통계 RAG 질의응답: BM25(Kiwi) + Dense(HCX 임베딩) 하이브리드 검색 → HCX 답변

데이터셋 두 가지(variant)를 각각 인덱싱해 비교할 수 있습니다.
  base     : kosis_views.py views 결과 (LLM 보강 없음)      kosis_data/rag_views/records.jsonl
  enriched : LLM(GPT 등)으로 보강한 결과                   kosis_data/rag_views_enriched/records.jsonl  (경로는 --records 로 변경)

단계
  python kosis_rag_qa.py index   --variant base                 # BM25 + Dense 인덱스 생성 (임베딩은 캐시되어 이어서 진행)
  python kosis_rag_qa.py index   --variant enriched --records <보강된 records.jsonl>
  python kosis_rag_qa.py search  "서울 인구 추이" --variant base   # 검색 결과만 확인 (LLM 호출 없음, 임베딩 1회)
  python kosis_rag_qa.py ask     "최근 10년 서울 인구 어떻게 변했어?" --variant base
  python kosis_rag_qa.py compare "1인 가구 많은 지역은?"           # base vs enriched 검색·답변 나란히 비교
  python kosis_rag_qa.py eval    --variant base --n 200          # 검색 성능(Recall@k, MRR) 자동 측정

.env
  HCX_API_KEY=nv-...                                   # CLOVA Studio API 키 (Bearer 인증, HMAC 서명 불필요)
  HCX_BASE_URL=https://clovastudio.stream.ntruss.com   # 호스트까지만 (경로는 코드가 붙임)
  HCX_MODEL=HCX-007                                    # 답변·질의 재작성 모델 (v3 Chat Completions)
  # 선택: HCX_EMBED_PATH=/v1/api-tools/embedding/v2     # 임베딩 v2 (1024차원, 입력 약 8k 토큰)

호출 API (CLOVA Studio 기본 REST, openai SDK 사용 안 함)
  대화   POST {HCX_BASE_URL}/v3/chat-completions/{HCX_MODEL}
         HCX-007 은 구조화 출력(JSON 스키마) 사용 시 thinking.effort=none 이어야 함
  임베딩 POST {HCX_BASE_URL}/v1/api-tools/embedding/v2   body {"text": ...}

필요 패키지: pip install requests rank-bm25 kiwipiepy numpy pandas duckdb pyarrow python-dotenv  (차트: plotly)
같은 폴더의 kosis_views.py 에서 load_view(좌표 → 데이터)와 render(차트)를 가져다 씁니다.
"""
import argparse
import json
import math
import random
import re
import time
from datetime import datetime
from pathlib import Path

from backend.agent.prompts import ANSWER_SCHEMA, ANSWER_SYS, REWRITE_SCHEMA, REWRITE_SYS
from backend.core.config import ANSWERS_DIR, KOSIS_DATA_DIR, RAG_INDEX_DIR, RAG_VIEWS_DIR
from backend.core.llm import chat
from backend.rag.ingestion.indexer import stage_index
from backend.rag.retrieval.fusion import RRF_K, Index
# [CHANGED] 이전: 위 함수·상수가 모두 같은 파일(kosis_rag_qa.py)에 있었음

DATA = KOSIS_DATA_DIR                                # [CHANGED] 이전: DATA = Path(os.getenv("KOSIS_DATA", "kosis_data"))
VIEWS_DIR = RAG_VIEWS_DIR                            # [CHANGED] 이전: VIEWS_DIR = DATA / "rag_views"  (processed/ 가 있는 곳)
INDEX_DIR = RAG_INDEX_DIR                            # [CHANGED] 이전: INDEX_DIR = DATA / "index"
DEFAULT_RECORDS = {"base": VIEWS_DIR / "records.jsonl",
                   "enriched": DATA / "rag_views_enriched" / "records.jsonl"}


# 질의 재정의 (프롬프트는 agent/prompts.py)
def rewrite(question):
    out = chat([{"role": "system", "content": REWRITE_SYS},
                {"role": "user", "content": f"질문: {question}\n예) '애 낳는 사람 줄었어?' → '출생아수 추이'"}],
               schema=REWRITE_SCHEMA, max_tokens=300)
    rw = (out.get("rewritten") or question).strip()
    subs = [s for s in (out.get("sub_questions") or []) if isinstance(s, str) and s.strip()][:3]
    return rw, subs




def fmt_v(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "자료없음"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def context_block(rec, max_rows, cond=None):
    """cond = (적용된 조건, 적용 못 한 조건, 조회 행) — 있으면 미리보기 대신 질문 조건에 맞춘 데이터를 넣음"""
    pv = rec.get("preview") or {}
    rows = pv.get("rows") or []
    cols = pv.get("columns") or []
    lines = [f"[자료 id={rec['id']}]",
             f"제목: {rec['title']}",
             f"출처: {rec.get('source_text') or rec.get('survey_nm', '')}",
             f"설명: {rec['description']}"]
    if cond:
        applied, missing, crow = cond
        if missing:
            lines.append("⚠ 질문 조건 중 이 자료에 없는 것: " + "; ".join(missing)
                         + " → 이 자료의 값을 질문 대상의 값으로 답하지 말 것")
        if applied and crow:
            lines.append("질문 조건 적용: " + ", ".join(f"{k}={v}" for k, v in applied.items()))
            lines += [r[0] for r in crow]
            if rec.get("caveats"):
                lines.append("주의: " + " / ".join(c[:150] for c in rec["caveats"][:3]))
            return "\n".join(lines)
    if rec.get("facts"):
        lines.append("핵심 수치(기본 단면): " + "; ".join(f["text"] for f in rec["facts"]))
    if rows:
        unit = (rec.get("filters") or {}).get("unit") or ""
        lines.append(f"데이터({' | '.join(cols)}, 단위 {unit}):")
        for r in rows[:max_rows]:
            lines.append("  " + " | ".join(fmt_v(x) if isinstance(x, (int, float)) else str(x) for x in r))
        if len(rows) > max_rows:
            lines.append(f"  … 외 {len(rows) - max_rows}행")
    if rec.get("caveats"):
        lines.append("주의: " + " / ".join(c[:150] for c in rec["caveats"][:3]))
    return "\n".join(lines)


NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def nums(text):
    out = set()
    for n in NUM_RE.findall(str(text)):
        n = n.replace(",", "")
        try:
            v = float(n)
        except ValueError:
            continue
        out.add(f"{v:.2f}")
        out.add(f"{round(v):.2f}")
    return out


def verify_numbers(answer_text, context_text):
    ctx = nums(context_text)
    bad = []
    for n in NUM_RE.findall(answer_text):
        v = n.replace(",", "")
        if len(v.replace(".", "")) <= 2:              # 1~2자리(순위·개수)는 제외
            continue
        if not (nums(n) & ctx):
            bad.append(n)
    return sorted(set(bad))



# 질문 조건 적용 (지역·연도·성별) 
SIDO = ["서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시",
        "경기도", "강원특별자치도", "강원도", "충청북도", "충청남도", "전북특별자치도", "전라북도", "전라남도", "경상북도",
        "경상남도", "제주특별자치도"]
_SHORT = re.compile(r"(특별자치시|특별자치도|특별시|광역시|도)$")
_PROFILES = {}


def short_name(nm):
    s = _SHORT.sub("", nm)
    return {"충청북": "충북", "충청남": "충남", "전라북": "전북", "전라남": "전남", "경상북": "경북", "경상남": "경남"}.get(s, s)


def mentioned_regions(q):
    """질문에 나온 시도 (정식명 기준). '서울', '경북' 같은 줄임말도 인식"""
    out = []
    for nm in SIDO:
        if nm in q or (len(short_name(nm)) >= 2 and short_name(nm) in q):
            out.append(nm)
    return list(dict.fromkeys(out))


def _profile(table_key):
    if table_key not in _PROFILES:
        p = VIEWS_DIR / "profiles" / f"{table_key}.json"
        _PROFILES[table_key] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    return _PROFILES[table_key]


def apply_conditions(rec, question):
    """검색된 뷰의 좌표(source)에 질문의 지역·연도·성별을 적용
    → (새 좌표, 적용된 조건, 적용 못 한 조건)  예) 전국 추이 뷰 + '2023년 서울' → 서울·2023 좌표"""
    import copy
    src = copy.deepcopy(rec["source"])
    prof = _profile(src.get("table_key", ""))
    applied, missing = {}, []
    if not prof:
        return src, applied, ["표 구조 정보(profiles) 없음"]
    q = question
    # 지역
    want = mentioned_regions(q)
    geo = [lv for lv in prof["levels"] if lv["kind"] == "geo"]
    if geo:                                            # 이 표의 하위 지역(시군구 등) 이름도 인식
        local = sorted({c["name"] for c in geo[0]["codes"] if len(c["name"]) >= 2 and not c.get("is_total")
                        and c["name"] in q and c["name"] not in want}, key=len, reverse=True)
        want += [n for n in local if not any(n in w for w in want)]
    if want:
        if not geo:
            missing.append(f"지역({', '.join(want)}): 이 표에는 지역 분류가 없음")
        else:
            lv = geo[0]
            codes = [c["code"] for c in lv["codes"]
                     if c["name"] in want or any(short_name(w) == short_name(c["name"]) for w in want)]
            if codes:
                src["dims"][f"c{lv['level']}"] = {"codes": codes}
                applied["지역"] = want
            else:
                missing.append(f"지역({', '.join(want)}): 이 표의 지역 목록에 없음")
    # 성별
    sex = [w for w in ("남자", "여자") if w in q or w[0] + "성" in q]
    sexlv = [lv for lv in prof["levels"] if lv["kind"] == "sex"]
    if sex and sexlv:
        codes = [c["code"] for c in sexlv[0]["codes"] if c["name"] in sex]
        if codes:
            src["dims"][f"c{sexlv[0]['level']}"] = {"codes": codes}
            applied["성별"] = sex
    # 연도 (월·분기 표면 그해 전체)
    years = re.findall(r"(19\d{2}|20\d{2})\s*년?", q)
    plist = [p["prd_de"] for p in prof["periods"].get(src["prd_se"], [])]
    if years and plist:
        hit = [p for p in plist if p[:4] in years]
        if hit:
            src["period"] = {"in": hit}
            applied["시점"] = years
        else:
            missing.append(f"시점({', '.join(years)}): 수록기간 {plist[0]}~{plist[-1]} 밖")
    return src, applied, missing


def condition_rows(src, max_rows):
    """조건을 적용한 좌표로 실제 값을 다시 조회 → 문맥용 행"""
    from backend.rag.ingestion.view_builder import load_view   # [CHANGED] 이전: from kosis_views import load_view
    df = load_view(src, VIEWS_DIR)
    name_cols = [c for c in df.columns if re.fullmatch(r"c\d_name", c)]
    cols = ["period_label"] + name_cols + ["itm_nm", "value", "unit"]
    df = df[[c for c in cols if c in df.columns]]
    return df, [["조건 적용 데이터: " + " | ".join(df.columns)]] + [
        [" | ".join(fmt_v(v) if isinstance(v, (int, float)) else str(v) for v in r)] for r in df.head(max_rows).values]


def load_chart_data(rec, src=None):
    """좌표(source)로 실제 데이터를 다시 조회 → 차트·근거표용. kosis_views.py 가 없으면 preview 사용"""
    try:
        from backend.rag.ingestion.view_builder import load_view   # [CHANGED] 이전: from kosis_views import load_view
        df = load_view(src or rec["source"], VIEWS_DIR)
        cols = [c for c in ["period_label", rec["chart"]["x"], rec["chart"].get("series"), "itm_nm", "unit", "value"]
                if c and c in df.columns and c != "period_date"]
        return df[list(dict.fromkeys(cols))], "source"
    except Exception as e:  # noqa: BLE001
        import pandas as pd
        pv = rec.get("preview") or {}
        return pd.DataFrame(pv.get("rows") or [], columns=pv.get("columns") or None), f"preview ({e.__class__.__name__})"


def answer(question, variant="base", k=5, use_rewrite=True, max_rows=40, save=True, idx=None):
    idx = idx or Index(variant)
    t0 = time.time()
    rw, subs = rewrite(question) if use_rewrite else (question, [])
    queries = [rw] + subs
    # 원 질문 + 재작성 + 하위 질문 각각 검색 후 RRF 로 합침 (Decomposition)
    agg = {}
    weights = {q: 1.0 for q in queries}               # 재작성·하위 질문 = 1.0
    if question not in weights:
        weights[question] = 0.5                         # 원 질문(구어체)은 보조 신호로 절반만 반영
    for q, w in weights.items():
        for r, h in enumerate(idx.search(q, k=k * 2)):
            agg.setdefault(h["id"], {"h": h, "s": 0.0})["s"] += w / (RRF_K + r + 1)
    hits = [v["h"] | {"fused": round(v["s"], 5)} for v in sorted(agg.values(), key=lambda x: -x["s"])][:k]

    # 맥락: 뷰 우선, 표 레코드는 같은 표의 뷰가 없을 때만
    ctx_recs = []
    for h in hits:
        rec = idx.by_id[h["id"]]
        if rec.get("doc_type") == "table":
            vids = [v for v in rec.get("view_ids", []) if v in idx.by_id][:1]
            if vids and vids[0] not in [c["id"] for c in ctx_recs]:
                rec = idx.by_id[vids[0]]
        if rec["id"] not in [c["id"] for c in ctx_recs] and rec.get("doc_type") == "view":
            ctx_recs.append(rec)
    # 질문의 지역·연도·성별을 각 뷰의 좌표에 적용해 실제 값을 다시 조회
    conds, srcs = {}, {}
    for r in ctx_recs:
        try:
            src, applied, missing = apply_conditions(r, question)
            crow = condition_rows(src, max_rows)[1] if applied else None
        except Exception as e:  # noqa: BLE001  (kosis_views 없음 등 → 기존 미리보기 사용)
            src, applied, missing, crow = r["source"], {}, [f"조건 적용 실패: {e.__class__.__name__}"], None
        conds[r["id"]], srcs[r["id"]] = (applied, missing, crow), src
    # 조건을 모두 적용한 자료 → 일부 적용 → 미적용 순서로 정렬 (같은 순위면 검색 순서 유지)
    ctx_recs.sort(key=lambda r: (len(conds[r["id"]][1]) > 0, -len(conds[r["id"]][0])))
    ctx_recs = ctx_recs[:4]
    context = "\n\n".join(context_block(r, max_rows, conds[r["id"]]) for r in ctx_recs)
    asked = mentioned_regions(question) + re.findall(r"(19\d{2}|20\d{2})\s*년?", question)
    cond_ok = (not asked) or any(not conds[r["id"]][1] and conds[r["id"]][0] for r in ctx_recs)

    out = chat([{"role": "system", "content": ANSWER_SYS},
                {"role": "user", "content": f"[질문]\n{question}\n\n[검색어]\n{' / '.join(queries)}\n\n[자료]\n{context}"}],
               schema=ANSWER_SCHEMA, max_tokens=1200)
    ans = out.get("answer") or out.get("_raw", "")
    used = [u for u in (out.get("used_ids") or []) if u in idx.by_id] or [r["id"] for r in ctx_recs[:1]]
    chart_id = out.get("chart_id") if out.get("chart_id") in idx.by_id else (used[0] if used else None)
    unverified = verify_numbers(" ".join([ans, out.get("summary", "")] + list(out.get("key_points") or [])), context)

    result = {
        "question": question, "variant": variant, "rewritten": rw, "sub_questions": subs,
        "answer": ans, "summary": out.get("summary", ""), "key_points": out.get("key_points") or [],
        "insufficient": bool(out.get("insufficient")) or not cond_ok, "unverified_numbers": unverified,
        "conditions": {r["id"]: {"applied": conds[r["id"]][0], "missing": conds[r["id"]][1]} for r in ctx_recs},
        "condition_matched": cond_ok,
        "used_ids": used, "chart_id": chart_id,
        "sources": list(dict.fromkeys(
            f"{idx.by_id[u].get('source_text', '')} {idx.by_id[u]['source'].get('kosis_url', '')}".strip()
            for u in used)),
        "caveats": [c[:200] + ("…" if len(c) > 200 else "") for c in
                    dict.fromkeys(c for u in used for c in (idx.by_id[u].get("caveats") or []))][:4],
        "retrieved": hits, "elapsed_s": round(time.time() - t0, 2),
    }
    if chart_id:
        rec = idx.by_id[chart_id]
        df, how = load_chart_data(rec, srcs.get(chart_id))
        result["chart"] = {"view_id": chart_id, "spec": rec["chart"], "data_from": how,
                           "columns": list(df.columns), "rows": df.head(500).astype(object)
                           .where(df.head(500).notna(), None).values.tolist()}
    if save:
        save_result(result, idx)
    return result


def save_result(result, idx):
    d = ANSWERS_DIR   # [CHANGED] 이전: d = DATA / "answers"
    d.mkdir(parents=True, exist_ok=True)
    stem = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{result['variant']}"
    (d / f"{stem}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if result.get("chart_id"):
        try:
            from backend.rag.ingestion.view_builder import render   # [CHANGED] 이전: from kosis_views import render
            render(idx.by_id[result["chart_id"]], VIEWS_DIR, d / f"{stem}.html")
            result["chart_html"] = str(d / f"{stem}.html")
        except Exception:  # noqa: BLE001  (plotly 미설치 등)
            pass
    result["saved"] = str(d / f"{stem}.json")


def print_result(r):
    print(f"\n질문: {r['question']}   [{r['variant']}]  ({r['elapsed_s']}s)")
    print(f"검색어: {r['rewritten']}" + (f"  | 하위 질문: {r['sub_questions']}" if r["sub_questions"] else ""))
    print("\n■ 답변\n" + r["answer"])
    if r["key_points"]:
        print("\n■ 핵심 수치\n" + "\n".join(f"- {p}" for p in r["key_points"]))
    for rid, c in (r.get("conditions") or {}).items():
        if c["applied"] or c["missing"]:
            print(f"  · 조건 {rid.split('::')[1]}: 적용 {c['applied']}" + (f" / 없음 {c['missing']}" if c["missing"] else ""))
    if r["insufficient"]:
        print("\n⚠ 질문 조건과 정확히 맞는 자료가 없어 가장 가까운 자료로 답했습니다.")
    if r["unverified_numbers"]:
        print(f"\n⚠ 자료에서 확인되지 않은 숫자(계산값일 수 있음): {r['unverified_numbers']}")
    if r["caveats"]:
        print("\n■ 주의\n" + "\n".join(f"- {c}" for c in r["caveats"]))
    print("\n■ 출처\n" + "\n".join(f"- {s}" for s in r["sources"]))
    if r.get("chart"):
        print(f"\n■ 그래프: {r['chart']['spec']['type']} ({len(r['chart']['rows'])}행, {r['chart']['data_from']})"
              + (f" → {r['chart_html']}" if r.get("chart_html") else ""))
    print("\n■ 검색 결과")
    for h in r["retrieved"]:
        print(f"  {h['fused']:.4f}  bm25#{h['bm25_rank']}  dense#{h['dense_rank']}  {h['title']}")
    if r.get("saved"):
        print(f"\n저장: {r['saved']}")

# test 단계
def stage_search(args):
    idx = Index(args.variant)
    for h in idx.search(args.query, k=args.k):
        print(f"{h['score']:.4f}  bm25#{h['bm25_rank']}  dense#{h['dense_rank']}({h['dense_sim']})  "
              f"[{h['doc_type']}] {h['title']}  {h['id']}")


def stage_ask(args):
    print_result(answer(args.query, args.variant, k=args.k, use_rewrite=not args.no_rewrite))


def stage_compare(args):
    """같은 질문을 base / enriched 인덱스로 각각 처리해 비교"""
    res = {}
    for v in ("base", "enriched"):
        if not (INDEX_DIR / v / "meta.json").exists():
            print(f"({v} 인덱스 없음 → 건너뜀)")
            continue
        res[v] = answer(args.query, v, k=args.k, use_rewrite=not args.no_rewrite)
        print_result(res[v])
        print("=" * 80)
    if len(res) == 2:
        a, b = ([h["id"] for h in res[v]["retrieved"]] for v in ("base", "enriched"))
        print(f"검색 결과 겹침: {len(set(a) & set(b))}/{len(a)}  |  "
              f"사용 자료 동일: {set(res['base']['used_ids']) == set(res['enriched']['used_ids'])}")


def stage_eval(args):
    """검색 성능 측정. --qa 파일(jsonl: {"question": ..., "gold": [view_id, ...]})이 없으면
    뷰의 템플릿 질문을 무작위로 뽑아 사용 (자체 질문이라 실제보다 높게 나옴 → 직접 만든 질문 추가 권장)"""
    idx = Index(args.variant)
    if args.qa:
        qa = [json.loads(l) for l in Path(args.qa).open(encoding="utf-8") if l.strip()]
    else:
        random.seed(0)
        views = [r for r in idx.by_id.values() if r.get("doc_type") == "view" and r.get("questions")]
        qa = [{"question": random.choice(r["questions"]), "gold": [r["id"], r.get("parent_id")]}
              for r in random.sample(views, min(args.n, len(views)))]
    ks = (1, 3, 5, 10)
    hit = {k: 0 for k in ks}
    mrr = 0.0
    for q in qa:
        ids = [h["id"] for h in idx.search(q["question"], k=max(ks))]
        rank = next((i for i, x in enumerate(ids) if x in set(q["gold"])), None)
        for k in ks:
            hit[k] += rank is not None and rank < k
        mrr += 1 / (rank + 1) if rank is not None else 0
    n = max(1, len(qa))
    print(f"[{args.variant}] 질문 {len(qa)}개  " + "  ".join(f"Recall@{k}={hit[k] / n:.3f}" for k in ks)
          + f"  MRR={mrr / n:.3f}")


def main():
    global VIEWS_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["index", "search", "ask", "compare", "eval"])
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--variant", default="base", help="base | enriched (임의 이름도 가능)")
    ap.add_argument("--records", default=None, help="index: 인덱싱할 records.jsonl (기본: variant 별 경로)")
    ap.add_argument("--views-dir", default=None, help="processed/ 가 있는 폴더 (기본 kosis_data/rag_views)")
    ap.add_argument("--dense-mode", choices=["single", "multi"], default="single",
                    help="multi: embed_text + 질문마다 벡터 (재현율↑, 임베딩 호출 수↑)")
    ap.add_argument("--doc-type", choices=["table", "view"], default=None, help="index: 특정 문서 종류만")
    ap.add_argument("--limit", type=int, default=None, help="index: 테스트용 레코드 수 제한")
    ap.add_argument("--workers", type=int, default=4, help="임베딩 동시 호출 수")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--no-rewrite", action="store_true", help="질의 재작성(HCX) 생략")
    ap.add_argument("--qa", default=None, help="eval: 평가 질문 jsonl")
    ap.add_argument("--n", type=int, default=200, help="eval: 자동 생성 질문 수")
    args = ap.parse_args()
    if args.views_dir:
        VIEWS_DIR = Path(args.views_dir)
    if args.stage == "index":
        args.records = Path(args.records or DEFAULT_RECORDS.get(args.variant, ""))
        if not args.records.exists():
            raise SystemExit(f"records 파일 없음: {args.records}  (--records 로 지정)")
        stage_index(args)
    elif args.stage == "search":
        stage_search(args)
    elif args.stage == "ask":
        stage_ask(args)
    elif args.stage == "compare":
        stage_compare(args)
    elif args.stage == "eval":
        stage_eval(args)



# ═════════════════════════════ [NEW] 통합 파이프라인 ═════════════════════════════
# 질문 ─▶ ① 재작성(query_analyzer) ─▶ ② View 검색·생성(ingestion.views) ─▶ ③ Record 기반 답변 (아래)
# 기존 answer() 는 records.jsonl 레코드(title·description·preview·chart …)를 받는데, View 모듈 Record 는
# {id, lexical_text, table{columns, rows}, metadata, source} 라 모양이 다르다 → record_context() 로 맞춰서
# 같은 프롬프트(ANSWER_SYS / ANSWER_SCHEMA)·숫자 검증(verify_numbers)을 그대로 쓴다.
def record_title(rec, titles=None):
    return (titles or {}).get(rec["id"]) or " ".join(str(rec.get("lexical_text", "")).split()[:8])


def record_context(rec, max_rows, notes=None, title=None):
    """View 모듈 Record → [자료] 블록 (context_block 과 같은 형식)"""
    md, src, t = rec.get("metadata") or {}, rec.get("source") or {}, rec.get("table") or {}
    cols, rows = t.get("columns") or [], t.get("rows") or []
    lines = [f"[자료 id={rec['id']}]",
             f"제목: {title or record_title(rec)}",
             f"출처: {md.get('survey_nm', '')} {src.get('kosis_url', '')}".strip(),
             f"조건: {rec.get('lexical_text', '')}",
             f"기간: {md.get('prd_from')}~{md.get('prd_to')} ({md.get('prd_se')})"
             + (" · 최신" if md.get("is_latest") else "") + f" / 단위: {md.get('unit') or '-'}"]
    if notes:
        lines.append("⚠ 질문 조건 중 이 자료에 맞추지 못한 것: " + "; ".join(notes)
                     + " → 이 자료의 값을 질문 대상의 값으로 답하지 말 것")
    if rows:
        lines.append(f"데이터({' | '.join(cols)}):")
        for r in rows[:max_rows]:
            lines.append("  " + " | ".join(fmt_v(x) if isinstance(x, (int, float)) else str(x) for x in r))
        if len(rows) > max_rows:
            lines.append(f"  … 외 {len(rows) - max_rows}행")
    else:
        lines.append("데이터: 조건에 맞는 값이 없음")
    return "\n".join(lines)


def answer_from_records(question, records, notes=None, titles=None, max_rows=40, queries=None):
    """③ 답변 노드: Record 목록 → AnswerResult(dict). HCX 1회"""
    from backend.data_engine.chart_generator import chart_from_record
    notes, titles = notes or {}, titles or {}
    by_id = {r["id"]: r for r in records}
    # 조건을 모두 맞춘 View → 일부 → 빈 View 순 (같으면 검색 순서 유지) — answer() 의 정렬 기준과 같음
    ctx = sorted(records, key=lambda r: (not (r.get("table") or {}).get("rows"), len(notes.get(r["id"], []))))[:4]
    if not ctx:
        return {"answer": "질문에 맞는 통계표를 찾지 못했습니다.", "summary": "", "key_points": [], "insufficient": True,
                "unverified_numbers": [], "used_ids": [], "chart_id": None, "chart": None, "sources": [], "caveats": []}
    context = "\n\n".join(record_context(r, max_rows, notes.get(r["id"]), titles.get(r["id"])) for r in ctx)
    out = chat([{"role": "system", "content": ANSWER_SYS},
                {"role": "user", "content": f"[질문]\n{question}\n\n[검색어]\n{' / '.join(queries or [question])}"
                                            f"\n\n[자료]\n{context}"}],
               schema=ANSWER_SCHEMA, max_tokens=1200)
    ans = out.get("answer") or out.get("_raw", "")
    used = [u for u in (out.get("used_ids") or []) if u in by_id] or [ctx[0]["id"]]
    chart_id = out.get("chart_id") if out.get("chart_id") in by_id else used[0]
    cond_ok = any(not notes.get(r["id"]) and (r.get("table") or {}).get("rows") for r in ctx)
    return {"answer": ans, "summary": out.get("summary", ""), "key_points": out.get("key_points") or [],
            "insufficient": bool(out.get("insufficient")) or not cond_ok,
            "unverified_numbers": verify_numbers(" ".join([ans, out.get("summary", "")] + list(out.get("key_points") or [])),
                                                 context),
            "used_ids": used, "chart_id": chart_id,
            "chart": chart_from_record(by_id[chart_id], record_title(by_id[chart_id], titles)),
            "sources": list(dict.fromkeys(
                f"{(by_id[u].get('metadata') or {}).get('survey_nm', '')} {record_title(by_id[u], titles)} "
                f"{(by_id[u].get('source') or {}).get('kosis_url', '')}".strip() for u in used)),
            "caveats": list(dict.fromkeys(n for u in used for n in notes.get(u, [])))[:6]}


def run_chat(question, today=None, top_k=10, n_views=3, search_with="rewritten", use_rewrite=True,
             max_rows=40, save=False):
    """POST /api/v1/chat — 단일 상태 그래프(현재는 순차 3노드). 각 노드 결과를 모두 돌려줘 Swagger 에서 단계별 확인 가능"""
    from backend.agent.tools import tool_rewrite, tool_views
    timings, t0 = {}, time.time()
    rw, vb, notes, _ = tool_rewrite(question, today, None, search_with, use_rewrite)
    timings["1_rewrite"] = round(time.time() - t0, 2)
    t1 = time.time()
    views, records = tool_views(vb, top_k, n_views)
    timings["2_views"] = round(time.time() - t1, 2)
    vnotes = {v["record"]["id"]: v["notes"] for u in views["units"] for v in u["views"]}
    titles = {v["record"]["id"]: c["tbl_nm"] for u in views["units"] for v in u["views"]
              for c in u["candidates"] if c["tbl_id"] == v["tbl_id"]}
    for u in views["units"]:
        notes += [f"[{u['unit_id']}] {n}" for n in u["notes"]]
    t2 = time.time()
    queries = [vb.get("search_text") or question] + list(vb.get("sub_questions") or [])
    result = answer_from_records(question, records, vnotes, titles, max_rows, queries)
    timings["3_answer"] = round(time.time() - t2, 2)
    timings["total"] = round(time.time() - t0, 2)
    out = {"question": question, "rewrite": rw, "view_bundle": vb, "views": views, "records": records,
           "result": result, "notes": notes, "timings": timings, "saved": None}
    if save:
        ANSWERS_DIR.mkdir(parents=True, exist_ok=True)
        p = ANSWERS_DIR / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_chat.json")
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        out["saved"] = str(p)
    return out

if __name__ == "__main__":
    main()
