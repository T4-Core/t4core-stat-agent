"""
STEP 5 (학습용) — 검색 결과를 HCX 에게 보여 주고 자연어로 답 받기

흐름:  질문 → (STEP 4) 문서 검색 → 문서들을 [자료] 로 묶음 → HCX 에게 질문 + 자료 전달 → 답변 출력
여기서는 출처·차트·검증 없이 '답이 잘 나오는지'만 확인합니다.

※ STEP 4 의 Searcher 를 가져다 씁니다. .env 에 HCX_API_KEY 가 필요합니다.
실행
  python step5_hcx_answer.py "서울 주택은 몇 호야?"
  python step5_hcx_answer.py "주택 관련 통계에는 뭐가 있어?" --mode bm25
  python step5_hcx_answer.py              # 질문 없이 실행하면 예시 질문 3개
막히면: ../solutions/step5_hcx_answer.py
"""
import argparse

import hcx_client
from step4_retrieval import Searcher

# TODO(5-0): 시스템 프롬프트를 직접 써 보세요. (HCX 에게 주는 '역할과 규칙')
# 넣으면 좋은 규칙 예:
#   - [자료]에 있는 내용·숫자만 쓰고, 없으면 모른다고 말하기   ← 환각(지어내기) 방지
#   - 어떤 통계표를 보고 답했는지 표 이름 말하기
#   - 시점과 단위 밝히기
#   - 말투('~입니다'체)와 길이(3~5문장)
SYSTEM_PROMPT = """여기에 시스템 프롬프트를 작성하세요."""

EXAMPLES = ["지역별 주택 수를 알려줘", "주택 관련해서 어떤 통계표가 있어?", "주택이 가장 많은 지역은 어디야?"]


# ─────────────── 5-1. 검색 결과 → [자료] 문자열 ───────────────
def build_context(hits):
    """hits = [(문서 dict, 점수), ...]  →  '[자료 1]\n<text>\n\n[자료 2]\n<text> ...'"""
    # TODO(5-1): 위 모양의 문자열을 만들어 반환하세요.
    # 힌트: enumerate(hits, 1) 로 1부터 번호,  "\n\n".join([...])
    raise NotImplementedError("TODO 5-1")


# ─────────────── 5-2. HCX 에 보낼 메시지 ───────────────
def build_messages(question, context):
    # TODO(5-2): HCX 대화 형식의 메시지 리스트를 반환하세요.
    #   [{"role": "system", "content": SYSTEM_PROMPT},
    #    {"role": "user",   "content": "[질문]\n<질문>\n\n[자료]\n<context>"}]
    raise NotImplementedError("TODO 5-2")


# ─────────────── 5-3. 검색 + 답변 ───────────────
def ask(question, searcher, mode="hybrid", k=3):
    # TODO(5-3): ① searcher.search 로 k 개 검색  ② build_context  ③ build_messages
    #            ④ hcx_client.chat(messages) 로 답변 받기  →  (answer, hits) 반환
    raise NotImplementedError("TODO 5-3")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", default=None)
    ap.add_argument("--mode", default="hybrid", choices=["bm25", "dense", "hybrid"])
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args()

    searcher = Searcher()
    for q in ([args.query] if args.query else EXAMPLES):
        answer, hits = ask(q, searcher, args.mode, args.k)
        print("=" * 70)
        print(f"질문: {q}   (검색: {args.mode})")
        print("참고 문서: " + " / ".join(doc["title"] for doc, _ in hits))
        print(f"\n{answer}\n")
    # 🤔 실험해 보기
    #   1) SYSTEM_PROMPT 의 "자료에 없으면 모른다고 말하기" 규칙을 지우고 "2050년 주택 수는?" 을 물어보세요.
    #   2) --mode bm25 / dense / hybrid 로 같은 질문을 해 보고 답이 어떻게 달라지는지 비교하세요.
    #   3) --k 1 과 --k 5 의 차이는?


if __name__ == "__main__":
    main()
