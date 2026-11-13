# table_card_search — 카드용 검색 + 세 방법 비교

기존 검색(`backend.rag.retrieval`)과 **같은 단계**로 검색하고, **읽는 데이터만** 카드로 바꿉니다. backend·configs 파일은 수정하지 않았습니다. 카드용 부품은 `factory.register`로 등록합니다.

| 방법 | 1단계 BM25(kiwi) 50 | 조건 확인 → 상위 top_k | dense 재정렬 (cost, -dense) |
|---|---|---|---|
| `baseline` | 표 설명문 (table_text) | `meta_profiles.jsonl` → resolve.unmet | 표 설명문 (같은 글) |
| `table_card` | 카드 `bm25_text` | `conditions.jsonl`(+`pieces.jsonl`) → 프로필 → resolve.unmet | 카드 `dense_text` |
| `table_card_expend` | 카드 `bm25_text` | `conditions.jsonl`의 `프로필` → resolve.unmet | 카드 `dense_text` |

조건 비용(`unmet`·`period_cover`·`cost`)과 재정렬 계산은 기존 함수와 같습니다. 같은 프로필이면 같은 순위가 나오는지 테스트로 확인했습니다. dense는 `hcx`(기본, HCX bge-m3), `hash`(오프라인 확인용), `none`(조건까지만) 중에서 고릅니다.

## 검색

```bash
python -m table_card_search.search --method all "2020년 서울 혼자 사는 가구 수"
python -m table_card_search.search --method table_card_expend --dense none --set both "시군구별 고령자 인구"
```

코드에서 쓰는 방법입니다. 기존 View 단계에 그대로 끼울 수 있습니다.

```python
from table_card_search.search import get_pipeline_for, search_fn
p = get_pipeline_for("table_card_expend")
p.search("1인가구 수", filters={"지역": ["서울특별시"], "시점": [2020]})
views.run_query(bundle, search_fn=search_fn("table_card"))
```

카드 폴더는 기본 위치를 씁니다: `table_cards/full`, `table_cards/sample_cards`, `table_card_expend/out/{full,sample}`. `--set both`는 full과 표본을 합칩니다.

View 만들기(`build_view`)는 아직 `storage/kosis_data`의 표만 다룹니다. 그래서 표본 표는 검색까지만 됩니다.

## 세 방법 비교

```bash
python -m table_card_search.compare \
  --golden synthetic_gold_pipeline/outputs/datasets/synthetic_gold_dataset.jsonl \
  --dense hcx none --variants O P
```

- 질의 분석(v4)은 한 번만 하고 `analysis_cache.jsonl`에 저장합니다. 세 방법이 같은 검색 문장·슬롯을 받습니다.
- 지표
  - `Hit@1·3·5·10`, `MRR`
  - `Groups@5·10`: 모든 근거 그룹이 상위 k 안에 있는지
  - `BM25@50`: 1단계 후보 안에 정답이 있는지. 카드 글 품질을 봅니다.
  - `gold_unmet_any`: 정답 표가 조건에서 불일치로 나오는 비율. 조건표 품질을 봅니다.
  - `sibling_confusion`: 이름이 같은 다른 표(다른 연도판 등)를 1위로 뽑은 비율
- Hit@5 실패 원인은 다음으로 나눕니다: 코퍼스에 없음 / BM25 단계 누락 / 조건 단계에서 밀림 / 6~10위.
- 결과는 `table_card_search/runs/<시각>_compare/`에 생깁니다: `report.md`, `summary.json`, `per_query.csv`.

`O`는 원문 질문으로, 표 이름이 들어 있어 쉽습니다. `P`(일상어)를 주 지표로 보세요.

**손으로 만든 검색 골든셋** (`retrieval_golden.jsonl`: `qid`·`question`·`required`·`split`·`qtype`)도 같은 명령으로 읽습니다.

- `required`의 안쪽 목록 하나 = 근거 그룹 하나. 그 안의 표 중 하나만 찾으면 그 그룹은 맞은 것입니다.
- `answerable: false`(no_answer) 문항은 표 정답이 없어 건너뜁니다.
- 변형은 `O` 하나뿐입니다. `qtype`별·`split`별 표가 리포트에 나옵니다. `--split test`로 test만 볼 수 있습니다.
- 정답 후보가 이미 손으로 들어 있어 `--alt`(alt_gold)는 쓰지 않습니다.

## 정답 판정 — 대체 정답 (`alt_gold.py`)

골든셋 정답은 생성에 쓴 표 하나뿐이라, 같은 값을 가진 다른 표를 찾아도 오답으로 셉니다. `alt_gold` 는 정답 사실(시점·지역·항목·조건의 칸 값)을 다른 표에서도 그대로 얻을 수 있는지 **값으로** 확인해 대체 정답 표를 찾습니다. 이름·설명이 비슷한지는 보지 않습니다. 이름이 비슷해도 정의가 다른 표(주민등록인구 vs 인구총조사 인구)는 값이 달라 걸러집니다.

1. 후보 표: CSV 값 사전에서 같은 시점 ∩ 같은 항목 이름(분류 값으로 들어간 경우 포함) ∩ 같은 지역(총계면 생략) ∩ 다른 비총계 조건. 정답 표는 뺌
2. 값 확인: 후보 표의 원본 CSV 에서 같은 좌표 행의 값 × 단위 환산 = 정답 값
   - `exact`: 정답의 표시 자릿수 기준 ±0.5 안 (천명 ↔ 명 환산 포함)
   - `rounded`: 후보 표가 더 큰 단위로 반올림한 값 (1,450천명 ↔ 1,449,896명). `--alt-exact-only` 로 뺄 수 있음
   - 남은 분류가 총계가 아닌 행이 여러 개면 어느 행인지 정할 수 없어 인정하지 않음
3. 근거 그룹마다 그 그룹의 사실(최대 `--max-facts` 개, 지역별 벡터는 고르게 뽑음)을 모두 맞춘 표 = 그 그룹의 대체 정답

```bash
python -m backend.rag.csv_index build            # CSV 값 사전이 없으면 먼저
python -m table_card_search.alt_gold --golden synthetic_gold_pipeline/outputs/datasets/synthetic_gold_dataset.jsonl
python -m table_card_search.compare --golden … --alt synthetic_gold_pipeline/outputs/datasets/alt_positives.jsonl
```

`--alt` 를 주면 보고서에 **엄격 · 완화** 표가 추가됩니다 (`hit@k_alt`, `groups@k_alt`, `mrr_alt`, `with_alt` = 대체 정답이 있는 질문 비율). 엄격과 완화의 차이가 크면 검색이 틀린 게 아니라 평가가 박했던 것이고, 완화 기준에서도 낮으면 검색 문제입니다. 판정 결과는 레코드마다 한 줄씩 쓰여 중단 후 다시 실행하면 이어서 합니다 (`--restart` 로 처음부터).

```bash
python -m pytest -q table_card_search/tests
```
