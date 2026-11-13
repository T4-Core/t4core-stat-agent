# kosis_fetch — 공용 KOSIS 추가 다운로드 (한 코드)

전수·인구 14개 조사는 이미 `storage/kosis_data/`에 있습니다 (collector.py, 약 48GB, 읽기만). 여기서는 **추가로 필요한 것만** 받습니다. 받은 파일은 table_card와 table_card_expend가 각자 읽어 따로 가공합니다.

| 단계 | 받는 것 | 저장 위치 (`KOSIS_EXTRA_DIR`, 기본 `storage/kosis_extra`) |
|---|---|---|
| `meta` | 표본 표 메타 (TBL·ITM·PRD·CMMT·SOURCE) | `sample/meta/<기관>_<표>.json`, `sample/catalog.csv` |
| `data` | 표본 표 수치 (원본 CSV, collector.KEEP_COLS) | `sample/raw/<조사>/<기관>_<표>.csv` |
| `expl` | 조사별 통계설명 (조사목적·대상범위·주요 용어 등) | `expl/<stat_id>.json` |

- **폴더 모양**: `sample/`은 collector 출력과 같은 모양이라 기존 코드(meta_profile, csv_index, normalize)가 그대로 읽습니다.
- **대상 표**: `storage/kosis_data/catalog.csv`에서 `is_sample == True`인 행입니다. 표본 catalog에서는 `selected=True`로 표시합니다.
- **seed**: `table_cards/sample_meta/*.json`, `table_cards/sample/data/*.parquet`가 있으면 API를 부르지 않고 그대로 가져옵니다. 두 가공이 같은 메타·수치를 보게 됩니다.
- **수집 방법**: collector.py 함수(get_meta·real_periods·plan·fetch_part·call)를 그대로 씁니다. 4만 셀 분할, 분당 호출 제한, 끊긴 뒤 이어받기도 같습니다.
- **API 키**: `.env`의 `KOSIS_API_KEY`를 씁니다. 오류 문장에 키가 섞이면 `***`로 가려서 기록합니다.

```bash
python -m kosis_fetch.fetch status --years 2015 2020        # 받을 양 확인 (호출 없음)
python -m kosis_fetch.fetch meta                            # seed 우선, 없는 것만 API
python -m kosis_fetch.fetch data --years 2015 2020 --max-cells 2000000
python -m kosis_fetch.fetch expl
python -m pytest -q kosis_fetch/tests
```

참고로 table_card의 표본 처리(`CARD_SET=sample`)는 지금 `table_cards/sample_meta`를 직접 읽습니다. 이 폴더의 `sample/meta`와 내용이 같습니다. table_card도 이 폴더를 읽게 하려면 `step1_split.py`의 `META_DIR` 한 줄만 바꾸면 됩니다 (권고만 하고 수정하지는 않았습니다).
