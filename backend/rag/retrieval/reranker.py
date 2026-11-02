"""[NEW, 자리만] Cross-encoder 리랭커

아직 구현 없음. 현재 '재정렬'은 table_search.search() 2단계(bge-m3 코사인)가 맡는다.
리랭커를 붙일 때 입력·출력은 table_search.search() 결과(Candidate dict 목록)와 같게 맞추면
ingestion/views.run_query 를 고치지 않고 끼울 수 있다.
"""


def rerank(query, candidates, top_n=None):
    """pass-through: 받은 순서 그대로 (rank 만 다시 매김)"""
    out = [{**c, "rank": i} for i, c in enumerate(candidates, 1)]
    return out[:top_n] if top_n else out
