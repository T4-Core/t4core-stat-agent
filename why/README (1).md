# KOSIS 미니 RAG 실습 (학습용)

`kosis_rag_builder.py` 로 수집한 KOSIS 데이터 중 **주택** 표만 골라서,
데이터 열어보기 → EDA → RAG 문서 만들기 → 검색(BM25 / Dense / Hybrid) → HCX 답변까지
**작게 한 바퀴** 직접 구현해 보는 실습입니다.

본 프로젝트(`kosis_views.py`, `kosis_rag_qa.py`)는 같은 흐름을 훨씬 크게 만든 것이라,
이 실습을 끝내면 본 코드가 어디서 무엇을 하는지 읽을 수 있게 됩니다.

```
kosis_data/ (수집 결과)
   │  STEP 1  catalog.csv + raw CSV + meta JSON 열어보고 연결
   │  STEP 2  주택 표 하나로 간단 EDA (추이, 지역 비교, 그래프)
   ▼
study_out/docs.jsonl      STEP 3  표마다 문서 2개 (meta 설명 문서 + 최신값 table 문서)
   │
   │  STEP 4  BM25 / Dense(HCX 임베딩) / Hybrid(RRF) 검색
   ▼
HCX 답변                  STEP 5  검색한 문서를 [자료]로 붙여 자연어 답변
```

## 폴더 구성

```
kosis_study/
├── README.md
├── requirements.txt
├── exercises/          ← 여기서 공부합니다 (TODO 빈칸)
│   ├── hcx_client.py         HCX 호출 도우미 (빈칸 없음, 그냥 쓰면 됨)
│   ├── step1_load_data.py
│   ├── step2_eda.py
│   ├── step3_build_docs.py
│   ├── step4_retrieval.py
│   └── step5_hcx_answer.py
└── solutions/          ← 정답 (막혔을 때만!)
    └── (같은 파일 이름)
```

## 준비

1. 패키지 설치
   ```bash
   pip install -r requirements.txt
   ```
2. **실행 위치에** 수집 데이터 폴더 `kosis_data/` 가 있어야 합니다. (다른 곳에 있으면 `KOSIS_DATA=경로` 환경변수)
   필요한 것: `kosis_data/catalog.csv`, `kosis_data/raw/주택총조사/*.csv`, `kosis_data/meta/*.json`
3. STEP 4(Dense·Hybrid), STEP 5 는 HCX 키가 필요합니다. 실행 위치에 `.env`:
   ```
   HCX_API_KEY=nv-...
   HCX_BASE_URL=https://clovastudio.stream.ntruss.com
   HCX_MODEL=HCX-007
   ```

## 실습 방법

```bash
cd exercises                       # kosis_data/ 와 .env 는 이 폴더에 복사하거나 KOSIS_DATA 로 지정
python step1_load_data.py          # 실행 → NotImplementedError: TODO 1-1a 가 나오면 그 빈칸부터 채우기
```

- 각 파일의 `TODO(번호)` 를 **번호 순서대로** 채웁니다. 빈칸마다 힌트가 붙어 있습니다.
- 실행했을 때 `NotImplementedError: TODO x-y` 가 나오면 아직 그 빈칸이 남았다는 뜻입니다.
- 다음 STEP 은 앞 STEP 의 함수를 `import` 해서 씁니다. **STEP 1 → 5 순서로** 진행하세요.
- 파일 끝의 `🤔` 주석은 생각해 볼 거리/선택 과제입니다.
- 정답과 똑같을 필요는 없습니다. 출력이 비슷하게 나오면 성공입니다.

| STEP | 배우는 것 | 빈칸 | 확인 방법 |
|---|---|---|---|
| 1 | 수집 결과 3종(목록·데이터·메타)의 구조와 연결 키(`org_id`, `tbl_id`, 코드) | 8 | `[연결 확인] 5/5` 처럼 코드가 전부 연결됨 |
| 2 | 문자열 → 숫자, 결측, 분류 고정, 추이·비교, 그래프 | 7 | `study_out/eda_trend.png`, `eda_snapshot.png` |
| 3 | RAG 문서 설계: 자연어 메타 문서 + 숫자 표 문서 | 5 | `study_out/docs.jsonl` 의 text 가 읽기 좋은지 |
| 4 | 토큰화, BM25, 임베딩·코사인 유사도, RRF | 6 | 같은 질문에 세 방식 결과 비교 |
| 5 | 프롬프트, context 구성, LLM 호출 | 4 | HCX 가 자료의 숫자로 답하는지 |

HCX 키가 없으면 STEP 4 는 `--mode bm25` 로 먼저 완성할 수 있고, Dense 는 `(건너뜀)` 으로 표시됩니다.

## 실행 예시

```bash
python step1_load_data.py
TABLE_INDEX=1 python step2_eda.py                      # 다른 주택 표로 EDA
MAX_TABLES=10 python step3_build_docs.py               # 표 10개만 문서로
python step4_retrieval.py "빈집이 많은 지역"            # bm25 / dense / hybrid 비교
python step4_retrieval.py "서울 아파트" --mode bm25
python step5_hcx_answer.py "주택이 가장 많은 지역은?"
python step5_hcx_answer.py                             # 예시 질문 3개
```

## 다 하고 나면 (본 프로젝트와 비교)

| 이 실습 | 본 프로젝트 | 무엇이 더 좋아졌나 |
|---|---|---|
| 표 1개 = 문서 2개 | `kosis_views.py` 뷰(그래프 1개 단위) 수십 개 | 질문 하나에 딱 맞는 작은 단위로 검색 |
| 최신 시점 숫자만 문서에 | `source` 좌표로 parquet 재조회 | 문서는 찾기만, 숫자는 원본에서 정확하게 |
| 질문 그대로 검색 | 질의 재작성·분해 (`rewrite`) | 구어체·복합 질문 대응 |
| 자유 텍스트 답변 | JSON 구조화 출력 + 숫자 검증 | 근거·차트·출처를 함께 반환 |
| 단어 그대로 BM25 | 지역명 축약(서울특별시→서울) 토큰 | 키워드 검색 재현율 향상 |
