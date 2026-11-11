# table_cards — 표 검색 카드·조건표 생성 코드

KOSIS 표의 메타데이터를 검색용으로 다시 정리하는 코드입니다. 데이터 파일은 git 에 올리지 않고, 아래 순서로 만듭니다.

- **조건표** `conditions.jsonl`: 표마다 있는 시점·지역. 검색 전에 조건이 맞지 않는 표를 거르는 데 씁니다.
- **검색 카드** `cards.jsonl`: `bm25_text`(대상·지표·축·항목), `dense_text`(제목·LLM 설명).

## 준비

1. `.env` 에 `KOSIS_API_KEY`, `HCX_API_KEY`, `HCX_BASE_URL`, `HCX_MODEL` (`.env.example` 참고)
2. `storage/kosis_data/` 에 `catalog.csv` 와 `meta/` (수집기 `backend/rag/ingestion/collector.py`)
3. 메타 프로필 생성: `python -m backend.rag.ingestion.meta_profile`

명령은 모두 저장소 루트에서 실행합니다.

## 표본 제외 표 (992개)

```bash
python table_cards/scripts/step1_split.py                 # 조건표 + 카드 재료
python table_cards/scripts/step3_cards.py --all --workers 4   # LLM 설명 (약 30분)
python table_cards/scripts/step4_refresh.py               # 검색 글 조립 + 검토 페이지
```

결과: `table_cards/full/`

## 표본조사 표 (1,372개)

표본 표는 공용 수집기가 받지 않으므로 메타를 따로 받습니다. `CARD_SET=sample` 을 주면 입력·출력이 표본 폴더로 바뀝니다. (PowerShell 은 먼저 `$env:CARD_SET="sample"`)

```bash
python table_cards/scripts/fetch_meta.py                  # 메타 수집 (약 40분)
python table_cards/scripts/make_profiles.py               # 메타 → 프로필
CARD_SET=sample python table_cards/scripts/step1_split.py
CARD_SET=sample python table_cards/scripts/step3_cards.py --all --workers 4   # LLM 설명 (1~2시간 이상)
CARD_SET=sample python table_cards/scripts/step4_refresh.py
```

결과: `table_cards/sample_meta/`, `table_cards/sample_cards/`

### 큰 표의 수치 데이터 (선택)

2015·2020년 표본 표 중 4만 셀이 넘는 표만 미리 받습니다. 나머지는 받지 않습니다.

```bash
python table_cards/scripts/size_report.py                 # 표 크기 계산 (fetch_meta 다음)
python table_cards/scripts/fetch_data.py                  # 수치 데이터 수집 (약 1시간 이상)
```

결과: `table_cards/sample/data/*.parquet`

## LLM 설명 검토

`step4_refresh.py` 가 `table_cards/scripts/review/review.html`(표본은 `review_sample.html`)을 만듭니다. 웹 서버로 열어 설명을 고친 뒤 "수정본 내보내기" 로 받은 파일을 반영합니다.

```bash
python -m http.server 8791 --bind 127.0.0.1 --directory table_cards/scripts/review
python table_cards/scripts/step4_refresh.py --edits <card_edits.json 경로>
```

`step3_cards.py` 는 재료가 바뀐 표만 LLM 을 다시 부릅니다. 반영한 설명을 지키려면 재료를 바꾼 뒤 `step3` 대신 `step4` 를 실행합니다.
