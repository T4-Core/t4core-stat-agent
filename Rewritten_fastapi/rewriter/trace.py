"""5. 대시보드용 중간 결과 저장 (HCX 호출 없음)
노트북 '5' 셀의 build_trace() 와 같은 내용. 노트북은 전역 변수(SLOT_RESULTS 등)를 썼고, 여기서는 run_pipeline() 결과 목록을 인자로 받음
  rewrite_trace.json : 중간 결과
  rewrite_trace.js   : 같은 내용 (dashboard/rewrite_pipeline_dashboard.html 이 서버 없이 바로 읽음)"""
import json
from dataclasses import asdict
from datetime import date, datetime

from .config import DASHBOARD_DIR, chat_model
from .slots import SLOT_KEYS


def build_trace(results, today=None, source=""):
    """results: run_pipeline() 결과 목록. 반환: {"meta": ..., "items": [...]}"""
    items = []
    for i, res in enumerate(results, 1):
        r, v, sres, b = res["slot"], res["valid"], res["sentences"], res["bundle"]
        items.append({
            "no": i,
            "question": r["question"],                                         # 1. 사용자 질문
            "term_hits": [[a, list(t)] for a, t in r.get("term_hits", [])],     # 2-1. 용어 사전
            "input_question": r["input_question"],                             # 2-2. 코드 추출
            "time_notes": r.get("time_notes", []),
            "rule_found": r.get("rule_found", {}),
            "user_prompt": r["messages"][1]["content"],                        # 2-3. HCX 슬롯 추출
            "hcx_out": r.get("hcx_out"),
            "hcx_slots": r.get("hcx_slots"),
            "hcx_subs": r.get("hcx_subs", []),
            "parsed": r.get("parsed"),
            "error": r.get("error", ""),
            "elapsed_s": r.get("elapsed_s"),
            "valid_slots": v["slots"],                                         # 2-4. 슬롯 검증
            "valid_subs": v["sub_slots"],
            "valid_log": v["log"],
            "rewritten": sres["rewritten"],                                    # 3. 슬롯 → 문장
            "sub_questions": sres["sub_questions"],
            "bundle": asdict(b),                                               # 4. QueryBundle
        })
    meta = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "model": chat_model(),
        "today": str(today or date.today()),
        "source": str(source),
        "n": len(items),
        "slot_keys": SLOT_KEYS,
        "system_prompt": results[0]["slot"]["messages"][0]["content"] if results else "",
    }
    return {"meta": meta, "items": items}


def save_trace(trace, out_dir=DASHBOARD_DIR):
    """rewrite_trace.json + rewrite_trace.js 저장. 반환: (json 경로, js 경로)"""
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(trace, ensure_ascii=False, indent=1)
    pj, pjs = out_dir / "rewrite_trace.json", out_dir / "rewrite_trace.js"
    pj.write_text(text, encoding="utf-8")
    pjs.write_text("window.REWRITE_TRACE = " + text + ";\n", encoding="utf-8")
    return pj, pjs
