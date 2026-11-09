"""
1-1 검색용 문장 — RAG(표 설명문 BM25·dense) 검색에 맞춘 정제 문장

  mode = v3  (기본, 추가 HCX 없음)
    재작성 모듈 v3 의 HCX 문장(rewritten) → resolve.search_query (지역·시점·연령 표현 빼고 지표·대상 단어 더함)
    + CSV 표준 이름(접지된 지표) 보강.  지역·시점은 표를 고르는 말이 아니라 View 를 자르는 조건이라 뺌
  mode = llm (실험)
    질문 + 접지된 CSV 용어를 주고 HCX 가 검색 문장을 한 번 더 씀. 실패하면 v3 문장으로 (notes)
"""
from backend.rag.csv_index.store import norm

LLM_SYS = ("국가통계 표 검색용 문장을 쓴다. 지역·연도는 빼고, 무엇을 센 통계인지(지표·대상)와 분류 기준(성별·연령·시도별 등)을 "
           "명사 위주로 짧게. [CSV 용어]에 있는 표기를 우선 쓴다. 하위 질문이 있으면 각각 한 문장씩. JSON 만.")
LLM_SCHEMA = {"type": "object", "properties": {"search_text": {"type": "string"},
                                               "sub_texts": {"type": "array", "items": {"type": "string"}}},
              "required": ["search_text", "sub_texts"]}


def v3_text(text, view_filters, names=()):
    from backend.rag.ingestion.resolve import search_query
    import re
    q = search_query(text or "", view_filters or {})
    q = " ".join(t for t in q.split() if re.search(r"[0-9A-Za-z가-힣]", t))       # 시점을 뺀 뒤 남은 '~' 같은 기호 조각
    extra = [n for n in dict.fromkeys(names) if n and norm(n) not in norm(q)]
    return " ".join([q, *extra]).strip()


def llm_text(question, sub_questions, csv_terms, chat_fn=None):
    from backend.core.llm import chat
    chat_fn = chat_fn or chat
    user = (f"[질문] {question}\n[하위 질문] {' / '.join(sub_questions) or '없음'}\n"
            f"[CSV 용어] {', '.join(dict.fromkeys(csv_terms)) or '없음'}")
    out = chat_fn([{"role": "system", "content": LLM_SYS}, {"role": "user", "content": user}], schema=LLM_SCHEMA,
                  max_tokens=400)
    if not isinstance(out, dict) or not str(out.get("search_text") or "").strip():
        raise ValueError(f"응답 형식 오류: {str(out)[:120]}")
    subs = [str(x).strip() for x in out.get("sub_texts") or []]
    return out["search_text"].strip(), subs
