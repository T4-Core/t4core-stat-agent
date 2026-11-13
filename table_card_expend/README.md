# table_card_expend — 원본 CSV까지 읽어 만드는 표 검색 카드

`table_cards`와 같은 결과 모양(`conditions.jsonl` + `cards.jsonl`, `bm25_text`/`dense_text`)을 만들되, 입력을 더 넓게 읽고 검토에서 찾은 문제를 고친 버전입니다. 가공은 table_card와 **따로** 합니다. table_card의 결과나 LLM 설명을 가져다 쓰지 않습니다. `table_cards/`의 코드는 수정하지 않았습니다.

## 입력

| 묶음 | 위치 | 비고 |
|---|---|---|
| `full` | `storage/kosis_data/` (`KOSIS_DATA_DIR`) | 이미 받아 둔 전수·인구 14개 조사. 기본 대상은 catalog `selected` (table_card와 같은 992개). `--scope all`이면 원본 CSV가 있는 표 전체 |
| `sample` | `<KOSIS_EXTRA_DIR>/sample/` | 공용 다운로드 `kosis_fetch`로 받은 표본 표. collector와 같은 폴더 모양 |
| 통계설명 | `<KOSIS_EXTRA_DIR>/expl/<stat_id>.json` | `kosis_fetch expl`로 받았을 때만 사용 |
| 사전 | `backend/rag/query_analyzer/dictionary/` | 질의 쪽과 같은 사전으로 표를 번역 (table_card와 같은 방식) |

KOSIS 접근(다운로드)은 모두 `kosis_fetch` 한 곳에서 합니다. 이 폴더는 받은 파일을 읽기만 합니다.

## table_card 대비 바뀐 점

| 항목 | table_card | table_card_expend |
|---|---|---|
| 구조 근거 | 메타만 | 메타 + **원본 CSV 스캔**. CSV에 실제로 있는 코드·항목·단위만 남기고, 메타가 없으면 CSV만으로 만듦 |
| 시점 | 메타의 정의 범위 | **CSV의 실제 시점**. 5년 주기 표는 2015·2020처럼 해마다 따로 기록 → 조건 확인이 정확 |
| 지역 | 상위 코드가 없으면 `중구`만 남음 | 코드 앞자리로 시도·시를 이어 붙임 (`부산광역시 중구`). 옛 시도명(`부산직할시`)도 시도로 처리 |
| 지표 추론 | 글자 위주 (`출생연도별 인구`→출생아수, `% 비율`→가구수 등 오탐) | 항목마다 **측정 종류**(개수·비율·평균)를 단위·이름으로 정한 뒤, 개수 항목에서만 개수 지표를 붙임. 근거(`지표_추론`)를 남김 |
| 모집단 | 없음 | `12세 이상`·`내국인`·`외국인 제외`·`일반가구`·`집단가구 포함` 등 (제목 괄호·합계 항목·주석에서) |
| 주석 | 앞 5줄 (한 문장이 여러 줄로 쪼개진 채) | 줄을 문장으로 이어 붙이고, `☞`·`~란` 정의를 **용어 정의**로 분리 |
| bm25_text | 조사명·제목·대상·지표·축·항목·축 값 | + 메뉴 경로(주제)·모집단·지역 수준 단어·두 번째 지역 역할·정의 용어. 제목은 두 번 |
| dense_text | 제목 + LLM 설명 | 제목 + 설명 + **볼 수 있는 것(관점)** + 조사 목적 |
| 설명 | LLM (HCX) | 기본은 규칙 설명(재현 가능). `--llm hcx`면 HCX를 쓰고, 금지 규칙(연도·지역 이름·재료에 없는 숫자)을 어기면 규칙 설명으로 대체 |
| 비슷한 표와의 차이 | LLM에게 맡김 | 같은 조사·같은 메뉴 경로의 다른 표에 없는 축·모집단·지표를 규칙으로 계산 |
| 조건표 | 시점·지역·단위 | + `프로필`: `resolve.unmet`이 그대로 읽는 모양. 검색 쪽 조건 확인이 기존 함수로 계산됨 |

**관점**은 이 표로 답할 수 있는 질문의 모양입니다. 연도·지역 이름 없이 `시도별 성별 인구수`처럼 씁니다. 골든셋을 원본 CSV에서 View로 잘라 만드는 방식(지표 하나 × 나뉘는 기준)을 카드 글로 옮긴 것입니다. 골든셋 질문 문장 틀은 쓰지 않아 평가 누출을 피했습니다.

원본 CSV 스캔은 기존 CSV 값 사전 코드(`backend.rag.csv_index.scanner`)를 그대로 씁니다. `storage/csv_index/tables.jsonl`이 이미 있고 서명이 같으면 다시 읽지 않습니다. 없으면 `out/<set>/cache/scan/`에 캐시합니다.

## 실행 (저장소 루트)

```bash
python -m table_card_expend all --set full                  # 전수·인구 14개 조사 (selected)
python -m table_card_expend all --set sample                # 표본 표 (먼저 kosis_fetch)
python -m table_card_expend all --set full --llm hcx --workers 4   # 설명을 HCX로
python -m table_card_expend split --set full --limit 20     # 단계별: split → describe → assemble
```

결과는 `table_card_expend/out/<set>/`에 생깁니다 (git 제외).

- `conditions.jsonl`, `pieces.jsonl`, `descriptions.jsonl`, `cards.jsonl`
- `split_report.txt`, `report.txt`: 같은 표의 table_card 결과가 있으면 지표·시점·지역 차이를 함께 적음
- `unmapped.csv`: 사전에 없는 말

## 테스트

```bash
python -m pytest -q table_card_expend/tests
```
