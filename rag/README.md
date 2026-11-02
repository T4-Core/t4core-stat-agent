# rag/ - 검색 모듈

`searcher.py` 하나로 이루어져 있고, 오케스트레이터가 넘긴 **views + 재작성된 질의**를 BM25 + Dense로 검색해 RRF로 합친 결과를 돌려준다.

## 1. 모듈 구조

```
[시스템 시작 시 1회]  원본 CSV -> view 생성 -> view 임베딩 저장        (B 모듈)
[질문마다]
  오케스트레이터 -> 재작성 모듈 -> QueryBundle                          (A 모듈)
                 -> view 모듈(질의로 조회) -> views (임베딩 포함 Record[]) (B 모듈)
                 -> Searcher.search(views, bundle, top_k) -> SearchResult (이 모듈)
```

### 입력

| 타입 | 주요 필드 |
|---|---|
| `QueryBundle` | `original`, `rewritten`, `sub_questions`, `intent`·`filters`·`sub_filters`(검색에 안 씀. 필터링은 하지 않는다) |
| `Record` | `id`, `lexical_text`, `dense_vectors`(벡터 1개 `[...]` 또는 여러 개 `[[...],[...]]`), `embedding_model`, `doc_type`, `parent_id`, `metadata`, `source` |

### 출력

`SearchResult(hits, debug)`. `Hit`에는 최종 순위, RRF 점수, 검색기별 원점수와 순위(`scores`), `metadata`, `source`가 담긴다.

## 2. 임베딩 모델은 검사하지 않고 출력만 한다

view 벡터를 만든 모델과 질문 임베딩 모델이 달라도 에러를 내지 않는다. (서로 다른 모델 조합을 실험해 볼 수 있게 하려는 것)
어떤 모델로 검색했는지는 `debug`에서 확인한다.

- `debug["retrievers"]`: 질문 임베딩 모델 (예: `"dense:fake-hash-64"`)
- `debug["view_embedding_models"]`: view 벡터를 만든 모델 목록 (예: `["fake-hash-64"]`)

**벡터 차원이 다르면 `ValueError("임베딩 모델 차원 불일치: ...")`를 낸다.** 질문 벡터와 view 벡터의 길이가 다르거나, view 끼리 길이가 다르면 내적을 계산할 수 없기 때문이다. 메시지에 차원과 모델 이름이 같이 나온다.

**주의:** 차원이 같아도 모델이 다르면 벡터 공간이 달라서 코사인 유사도가 의미 없는 값이 될 수 있다. 모델이 다른 조합의 점수는 해석에 주의한다.

## 3. 구조 설계: 요청별 상태를 검색 모델에 두지 않는다

`Retriever.build(records)`가 인덱스를 **돌려주고**, `search(index, query, ...)`가 그 인덱스를 **인자로 받는다.**
검색 모델 객체는 서버 시작 때 한 번 만들어 여러 요청이 같이 쓰므로, 객체 필드에 질문별 views를 저장하면 동시 요청이 서로의 문서를 덮어쓴다.
질문별 상태(views, 인덱스)는 `search()` 안의 지역 변수다. 공유 상태는 질문 임베딩 캐시뿐이고 잠금으로 보호한다.

## 4. 필터링은 하지 않는다 / 빈 입력 처리

- 이 모듈은 metadata 조건으로 view를 거르지 않는다. (`filter_mode`, `required_filter_keys`, `filter_empty`는 제거했다.) `QueryBundle.filters`, `sub_filters`는 스키마에만 남아 있고 검색에 쓰이지 않는다.
- "관련 있는 view인가"의 판단은 유사도 검사와 기준값으로 한다 (아래 7장 task 1). `metadata`는 `Hit`에 그대로 전달만 한다.
- `views`가 `None`이거나 비어 있으면 검색하지 않고 `hits=[]`, `debug["empty_views"]=True`로 돌려준다. 1개 이상이면 검색한다.

## 5. 알아둘 점

- `BM25Plus`는 단어가 없는 문서에도 모든 문서에 같은 값을 더해 준다. 순위에는 영향이 없지만 **원점수가 Okapi보다 커진다.** BM25 임계값을 정할 때 감안한다.
- 후보 view가 매우 적어도 BM25가 동작하지만, 통계(IDF)의 의미는 약해진다.
- 질문 임베딩 캐시는 1,000개를 넘으면 전부 비운다. 필요해지면 LRU로 바꾼다.

## 6. 실행과 검증

```bash
.venv/Scripts/python.exe tests/test_searcher.py       # 요약
.venv/Scripts/python.exe tests/test_searcher.py -v    # 질의마다 hits와 검색기별 점수까지 출력
```

- 테스트 데이터는 `tests/fixtures/searcher_cases.json`에 있다. 가짜 view 16개와 질의 8개로 구성되고, 모두 하이브리드(BM25 + Dense), `top_k=5`로 실행한다.
  질의마다 `expect`(`top1`, `contains`, `excludes`, `n_hits`)와 비교한다. 질의를 추가할 때는 JSON만 고치면 된다.
- 이어서 회귀 시험이 코드 리뷰 지적 사례(BM25 1~2건, 빈 토큰, top_k 경계, 캐시 동시성)와 필터 미적용, 빈·`None` views, 임베딩 모델 이름이 달라도 막히지 않고 `debug`에 출력되는지, 차원이 다르면 에러가 나는지를 다시 확인한다.
- 임베딩은 단어 해시 기반의 가짜 임베딩이라 API 호출이 없다. 실패가 있으면 종료 코드 1로 끝난다.
- 실제 KOSIS 데이터와 HCX 임베딩으로 눈으로 확인하려면 `rag/playground.py`(http://localhost:8765)를 쓴다.

## 7. 앞으로 할 일 (task)

1. **view 모듈이 넘긴 view와 사용자 쿼리의 유사도 평가 → 돌려보낼지 판단**
   - view 모듈이 골라 준 후보가 실제로 질문과 관련 있는지 이 모듈에서 다시 평가한다. (view 모듈의 점수는 받지 않으므로 BM25, Dense 점수로 직접 판단)
   - 관련도가 낮은 view는 결과(`hits`)에 넣지 않고 걸러낸다. 후보 전체가 기준 미달이면 "근거 view 없음"으로 판단해 돌려보낸다.
   - 정해야 할 것: 평가에 쓸 점수(BM25 원점수, 코사인 유사도, RRF 점수 중 무엇을 쓸지), 기준값, 두 검색기 결과가 엇갈릴 때의 규칙
2. 점수 임계값(검색기, 카테고리별)과 "답변 불가" 판정 정의
   - 위 1번의 판단 결과와 빈 views(`empty_views`)를 "답변 불가" 사유로 `SearchResult`에 담는다.
3. top-k 커트라인 고도화 (고정 k 대신 점수 급락 지점, 1등 대비 비율 등)
4. 실험 하네스: 토크나이저, 임베딩 모델, 검색 방식(BM25 / Dense / 하이브리드), 임계값 비교
5. 실험 결과로 `SearchConfig` 기본값 확정
