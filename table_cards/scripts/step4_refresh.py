"""
[4] 카드 갱신 — LLM 을 다시 부르지 않고 카드 칸만 최신으로 맞추고, 검토 수정본을 반영

하는 일
  1) 제목·대상·지표·축·지역수준을 최신 pieces / conditions 와 맞춤 (설명은 그대로)
  2) 검토 페이지에서 내보낸 수정본(card_edits.json)이 있으면 설명을 바꾸고 '검토' 칸에 기록
  3) 검색 글(bm25_text · dense_text)과 금지 규칙 검사를 다시 만듦
  4) 재료_해시를 지금 재료로 바꿔 둠 → step3_cards.py 를 다시 돌려도 이 카드들은 LLM 이 덮어쓰지 않음
  5) 검토 페이지 review/review.html 을 만듦 (review_template.html 에 카드 데이터를 넣은 파일 하나 — 어디서 열어도 동작)

실행  저장소 루트에서:
  .venv/Scripts/python.exe table_cards/scripts/step4_refresh.py                       # 칸 맞추기 + 검토 데이터
  .venv/Scripts/python.exe table_cards/scripts/step4_refresh.py --edits <card_edits.json 경로>   # 수정본 반영
"""
import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from step3_cards import CARDS, OUT, PROMPT_VER, check, facts, load    # noqa: E402

REVIEW = HERE / "review"


def search_texts(card, p):
    axis_vals = [v for a in p["축"] if a.get("값_수", 0) <= 30 for v in (a.get("값") or [])]
    bm25 = " ".join([card["조사명"] or "", card["제목"], " ".join(card["대상"]), " ".join(card["지표"]),
                     " ".join(card["축"]), " ".join(p["항목"][:30]), " ".join(axis_vals)])
    dense = f"{card['조사명']} | {card['제목']}\n{card['설명']}"
    return bm25, dense


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--edits", help="검토 페이지에서 내보낸 card_edits.json")
    a = ap.parse_args()

    P, C, K = load(OUT / "pieces.jsonl"), load(OUT / "conditions.jsonl"), load(CARDS)
    edits = json.loads(Path(a.edits).read_text(encoding="utf-8"))["edits"] if a.edits else {}

    backup = OUT / f"cards_backup_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
    shutil.copy(CARDS, backup)

    changed_fields, applied = 0, 0
    for tid, k in K.items():
        if "오류" in k:
            continue
        p, c = P[tid], C[tid]
        new = {"제목": p["제목"], "대상": p["대상"], "지표": p["지표"], "축": [x["표준"] or x["원래"] for x in p["축"]],
               "조사구분": c["조사구분"], "지역수준": facts(p, c, P)["지역 수준"]}
        changed_fields += any(k.get(f) != v for f, v in new.items())
        k.update(new)
        e = edits.get(tid)
        if e:
            if e.get("설명") is not None:
                k["설명"] = e["설명"].strip()
            k["검토"] = {"확인": bool(e.get("확인")), "수정": bool(e.get("수정")), "메모": e.get("메모", ""),
                        "시각": e.get("시각")}
            applied += 1
        k["bm25_text"], k["dense_text"] = search_texts(k, p)
        k["검사"] = check(k)
        f = facts(p, c, P)
        k["재료_해시"] = hashlib.sha1((PROMPT_VER + json.dumps(f, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:16]

    with CARDS.open("w", encoding="utf-8") as fo:
        for k in K.values():
            fo.write(json.dumps(k, ensure_ascii=False) + "\n")

    # 검토 페이지 데이터 (보기 칸 + 고칠 칸)
    REVIEW.mkdir(exist_ok=True)
    rows = [{"id": t, "조사": k.get("조사명"), "제목": k.get("제목"), "제목_원래": P[t]["제목_원래"],
             "조사구분": C[t]["조사구분"], "대상": k.get("대상", []), "지표": k.get("지표", []), "축": k.get("축", []),
             "지역수준": k.get("지역수준", []), "시점": C[t]["시점"], "설명": k.get("설명", ""),
             "검사": k.get("검사", []), "검토": k.get("검토")}
            for t, k in K.items() if "오류" not in k]
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")      # 설명 속 '</' 가 script 를 닫지 않게
    html = (REVIEW / "review_template.html").read_text(encoding="utf-8").replace("/*__CARDS__*/", f"window.CARDS = {data};")
    page = REVIEW / ("review.html" if OUT.name == "full" else "review_sample.html")   # 표본 표는 페이지를 따로
    page.write_text(html, encoding="utf-8")

    print(f"카드 {len(K)}개 | 칸이 바뀐 카드 {changed_fields}개 | 수정본 반영 {applied}개")
    print(f"백업 → {backup.name}")
    print(f"검토 페이지 → {page}  ({len(rows)}개)")


if __name__ == "__main__":
    main()
