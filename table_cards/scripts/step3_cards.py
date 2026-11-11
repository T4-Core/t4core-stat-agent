"""
표 데이터 재정의 [3] 더하기 — 카드 재료(pieces) → LLM 자연어 설명 → 검색 카드(cards.jsonl)

LLM 에게 주는 것 : 조사명·제목·주제·축·항목·대상·지표·주석 + 지역 '수준'만 + 같은 조사의 비슷한 표 제목(차이를 쓰게)
LLM 이 만드는 것 : 설명(2~3문장) · 일상어(사전 후보로만 보관)
금지             : 숫자·연도·지역 이름 (생성 후 자동 검사 → '검사' 칸에 표시)
동의어           : 카드에 넣지 않음 — 질의 쪽 팀 사전(dictionary_표명.json → term_dict.json)이 맡음 (11-10 삭제)

출력  table_cards/full/cards.jsonl   (재료가 같으면 다시 부르지 않음 — 재료_해시 캐시)

실행  저장소 루트에서:
  .venv/Scripts/python.exe table_cards/scripts/step3_cards.py --sample          # 샘플 10개
  .venv/Scripts/python.exe table_cards/scripts/step3_cards.py --ids DT_A DT_B    # 지정한 표
  .venv/Scripts/python.exe table_cards/scripts/step3_cards.py --all --workers 4  # 전체
"""
import argparse
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from step1_split import OUT, SIDO_RE                    # noqa: E402  (같은 폴더의 1단계 스크립트. CARD_SET 에 따라 OUT 이 정해짐)

CARDS = OUT / "cards.jsonl"
PROMPT_VER = "v4"     # v4: 질문예시 삭제 (11-11)
                      # v2: 축 값 전달, 일상어 예시, 추계 표는 전망 표현
                      # v3: 예시를 평가 문항과 겹치지 않는 주제(사망·이혼)로 교체, 같은뜻·사전후보는 검색 글에서 뺌
                      #     (동의어는 질의 쪽 사전이 맡음 — 두 곳에 두면 중복·관리 부담)

SAMPLE = ["DT_1JC1502", "DT_1BZ0502", "DT_1BPA003", "DT_1B28025", "TX_11025_A001_A",
          "DT_1IN2010", "DT_1PB1608", "DT_1B83A05", "DT_182001_A058_2025", "DT_1IN7501"]

SYSTEM = """너는 통계표 검색용 설명을 쓰는 사람이다. 사용자는 일상어로 질문하고, 너의 설명이 그 질문과 표를 이어 준다.
주어진 사실만 쓴다. 표에 없는 내용을 추측하지 않는다.

규칙
- 연도, 기간, 지역 이름(서울·대구·신안군 등)을 절대 쓰지 않는다. 지역은 '시도별', '시군구별'처럼 수준으로만 말한다.
- 설명: 2~3문장. ① 무엇을(누구를) 세었는지 ② 어떤 기준으로 나뉘는지 — 이때 '항목'과 '축 값'에서 사람들이 찾을 만한
  대표 값을 이름 그대로 넣는다 (예: 사망자 수, 협의 이혼, 재판 이혼) ③ 같은 주제의 다른 표와 무엇이 다른지.
- 조사명에 '추계'가 있으면 미래 전망 자료다: 설명에 '전망·예상'을 쓴다.
- 일상어: 대상·지표·대표 값을 사람들이 부르는 다른 말 3~6개. 공식 용어를 반복하지 말고 구어 표현을 쓴다.
  예) 사망자 → 돌아가신 분, 숨진 사람 / 이혼 → 갈라선 부부, 헤어진 부부
- 반드시 JSON 으로만 답한다: {"설명": "...", "일상어": ["...", ...]}"""

SCHEMA = {"type": "object", "properties": {
    "설명": {"type": "string"},
    "일상어": {"type": "array", "items": {"type": "string"}}}, "required": ["설명", "일상어"]}

YEAR_RE = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)")
DIGIT_RE = re.compile(r"\d")


def load(path):
    return {json.loads(l)["tbl_id"]: json.loads(l) for l in open(path, encoding="utf-8")}


def region_levels(names):
    lv = {0: "전국", 1: "시도", 2: "시군구", 3: "읍면동"}
    found = sorted({min(n.count(" ") + (0 if n == "전국" else 1), 3) for n in names})
    return [lv[x] for x in found]


def siblings(p, P):
    # 같은 조사·같은 주제의 다른 표 제목 (차이를 쓰게 하려고) — 최대 6개
    same = [x["제목"] for t, x in P.items() if t != p["tbl_id"] and x["조사명"] == p["조사명"] and x["주제"] == p["주제"]]
    return list(dict.fromkeys(s for s in same if s and s != p["제목"]))[:6]


def facts(p, c, P):
    notes = [n for n in p["주석"] if not SIDO_RE.search(n)][:5]
    f = {"조사명": p["조사명"], "표 이름": p["제목"], "주제": " > ".join(p["주제"]),
         "조사구분": c["조사구분"], "지역 수준": region_levels(c["지역"]),
         "나뉘는 기준(축)": [a["원래"] + (f"(역할: {a['역할']})" if a["역할"] else "") for a in p["축"]],
         "축 값": {a["원래"]: (a.get("값") or [])[:15] + ([f"… 총 {a['값_수']}개"] if a.get("값_수", 0) > 15 else [])
                  for a in p["축"]},
         "항목": p["항목"][:30], "대상(표준어)": p["대상"], "지표(표준어)": p["지표"],
         "주석": [n[:150] for n in notes], "같은 주제의 다른 표": siblings(p, P)}
    if c.get("지역2"):
        f["두 번째 지역"] = f"{c['지역2']['역할']} (지역별로 나뉨)"
    return f


def check(card):
    # 금지 규칙 검사: 설명에 지역 이름 · 연도가 있으면 표시
    text = card["설명"]
    issues = []
    if SIDO_RE.search(text):
        issues.append("지역이름:" + ",".join(sorted(set(SIDO_RE.findall(text)))))
    if YEAR_RE.search(text):
        issues.append("연도:" + ",".join(sorted(set(YEAR_RE.findall(text)))))
    return issues


def make_card(tid, P, C):
    from backend.core.llm import chat
    p, c = P[tid], C[tid]
    f = facts(p, c, P)
    h = hashlib.sha1((PROMPT_VER + json.dumps(f, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:16]
    t0 = time.time()
    res = chat([{"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(f, ensure_ascii=False, indent=1)}],
               schema=SCHEMA, temperature=0.2, max_tokens=800)
    sec = round(time.time() - t0, 1)
    if "_raw" in res:
        return {"tbl_id": tid, "오류": res["_raw"][:300], "재료_해시": h, "초": sec}
    axes = [a["표준"] or a["원래"] for a in p["축"]]
    card = {"tbl_id": tid, "조사명": p["조사명"], "제목": p["제목"], "대상": p["대상"], "지표": p["지표"], "축": axes,
            "지역수준": f["지역 수준"], "설명": res.get("설명", "").strip(),
            "사전후보": [w.strip() for w in res.get("일상어", [])][:6]}
    axis_vals = [v for a in p["축"] if a.get("값_수", 0) <= 30 for v in (a.get("값") or [])]
    # 사전후보(LLM 일상어)는 검색 글에 넣지 않음 — 팀 사전 보강 검토용으로만 보관
    card["bm25_text"] = " ".join([card["조사명"] or "", card["제목"], " ".join(card["대상"]), " ".join(card["지표"]),
                                  " ".join(axes), " ".join(p["항목"][:30]), " ".join(axis_vals)])
    card["dense_text"] = f"{card['조사명']} | {card['제목']}\n{card['설명']}"
    card["검사"] = check(card)
    card.update(재료_해시=h, 프롬프트=PROMPT_VER, 초=sec)
    return card


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--force", action="store_true", help="캐시 무시하고 다시 생성")
    a = ap.parse_args()

    P, C = load(OUT / "pieces.jsonl"), load(OUT / "conditions.jsonl")
    ids = SAMPLE if a.sample else (list(P) if a.all else a.ids or SAMPLE)
    done = load(CARDS) if CARDS.exists() else {}

    todo = []
    for t in ids:
        f = facts(P[t], C[t], P)
        h = hashlib.sha1((PROMPT_VER + json.dumps(f, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:16]
        if a.force or done.get(t, {}).get("재료_해시") != h or "오류" in done.get(t, {}):
            todo.append(t)
    print(f"대상 {len(ids)}개 중 새로 만들 것 {len(todo)}개 (나머지는 캐시)", flush=True)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(make_card, t, P, C): t for t in todo}
        for i, fu in enumerate(as_completed(futs), 1):
            t = futs[fu]
            try:
                done[t] = fu.result()
            except Exception as e:                       # 한 표가 실패해도 나머지는 계속
                done[t] = {"tbl_id": t, "오류": repr(e)[:300]}
            if i % 20 == 0 or i == len(todo):
                with CARDS.open("w", encoding="utf-8") as fo:      # 중간 저장 (끊겨도 이어서)
                    for v in done.values():
                        fo.write(json.dumps(v, ensure_ascii=False) + "\n")
                print(f"  {i}/{len(todo)}  경과 {time.time() - t0:.0f}초", flush=True)

    errs = [t for t in ids if "오류" in done.get(t, {})]
    flagged = [(t, done[t]["검사"]) for t in ids if done.get(t, {}).get("검사")]
    secs = [done[t].get("초") for t in todo if done.get(t, {}).get("초")]
    print(f"\n완료: 오류 {len(errs)}개, 금지 규칙 걸림 {len(flagged)}개, "
          f"호출당 평균 {sum(secs) / len(secs):.1f}초" if secs else "\n완료")
    for t, iss in flagged:
        print("  검사:", t, iss)
    for t in errs:
        print("  오류:", t, done[t]["오류"][:150])


if __name__ == "__main__":
    main()
