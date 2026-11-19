# Streamlit 확인용 화면

시안(`screens.html`)을 바탕으로 만든 확인용 화면입니다. 질문 → 질의 분석 → 검색·View → 답변(차트·표)을 실제 백엔드(`POST /api/v1/chat`)로 돌려 봅니다.
백엔드 코드는 건드리지 않고 HTTP 로만 부릅니다.

## 실행

```bash
# 1) 백엔드 (레포 루트)
uvicorn backend.main:app --port 8000

# 2) 화면 (다른 터미널)
pip install -r frontend/streamlit_app/requirements.txt
cd frontend/streamlit_app
streamlit run app.py            # http://localhost:8501
```

| 환경변수 | 기본 | 뜻 |
|---|---|---|
| `STAT_AGENT_API` | `http://localhost:8000` | 백엔드 주소 (화면 오른쪽 위 ⚙ 에서도 바꿈) |
| `STAT_AGENT_TIMEOUT` | `180` | `/chat` 기다리는 시간(초) |
| `UI_HISTORY_PATH` | `frontend/streamlit_app/.history.json` | 히스토리 저장 파일 (gitignore) |

`cd frontend/streamlit_app` 에서 실행해야 `.streamlit/config.toml` 의 색(시안 청록)이 적용됩니다.

## 화면 (시안 번호)

| 시안 | 화면 | 백엔드 |
|---|---|---|
| 01 | 메인 · 추천 질문 · 최근 질문 | — |
| 02~04 | 조건 고르기: 지역(시도 + 시군구) · 시점(한 해 · 기간 · 최신 + 주기) · 대상 | — |
| 05 | 이 조건으로 볼 수 있는 통계 3개 | `POST /api/v1/rag/search` |
| 06 | 진행 단계 (끝나면 단계별 소요 시간) | `POST /api/v1/chat` |
| 07 | 비슷한 통계표 고르기 (`status=needs_selection`) — 표 정보 · 값 미리보기 | `/chat` + `previous` · `view_selections` |
| — | 되묻기 (`status=needs_clarification`) | `/chat` + `previous` · `selections` |
| 08 | 결과: 시각화(차트 · 표) · 답변 · 핵심 요약 · 사용한 통계표 · 이어서 묻기 | |
| 09 | 크게 보기 (차트 + 표 + CSV · KOSIS 원본) | |
| 12~16 | 차트 2개 이상: 한 개씩(넘기기) · 한번에 · 넓게 나란히 · 크게 보기 나란히/한 개씩 | |
| 10 · 11 | 히스토리 (오늘 · 어제 · 지난 7일, 검색 · 즐겨찾기 · 미리보기 · 다시 열기) · 빈 화면 | — |

⚙ 설정
- **답변 방식** `modules`(기본): 모듈 2→3→5→6. 차트는 모듈 5 의 plotly 그림, 핵심 요약은 모듈 3 계산 요약, 표는 모듈 6 근거 표
  / `default`: 답변 HCX 1회. 차트는 `result.chart` 스펙(line·bar)을 화면에서 그림, 핵심 요약은 `key_points`
- **1순위로 바로 진행** 끄면(기본) 표마다 값이 다를 때 07 화면이 나옴
- **기준일** '작년'·'최근 N년' 의 기준 (비우면 오늘)

결과 화면의 **질문을 이렇게 이해했어요** 에 재작성 문장 · 조건 칩 · 메모 · 단계별 시간이 있어 파이프라인 확인에 씁니다.
못 맞춘 조건 · 계산하지 못한 이유(주의사항)는 답변 아래에 바로 보입니다.

## 시안과 다른 점

- 캐릭터 영역: `assets/sloth.png` 가 있을 때만 그림 (없으면 그 자리를 비움)
- 06 진행 단계: `/chat` 한 번 호출이라 단계별 진행을 실시간으로 받지 못함 → 끝난 뒤 단계별 소요 시간을 보여 줌
- 05 '이 통계로 보기': 표를 직접 지정하는 API 가 없어 질문 끝에 표 이름을 붙여 보냄
- 이어서 묻기: 백엔드에 대화 기억이 없어 칩은 '원래 질문 + 칩 문장' 으로, 입력은 새 질문으로 보냄
- PNG 내려받기 대신 CSV (차트는 plotly 도구 모음의 사진 저장으로)

## 구조

```
app.py         화면 (상태: 페이지 · 화면 · 조건 · 마지막 응답 · 히스토리)
view_model.py  /chat 응답 → 화면 값 (Streamlit 없이 테스트) · 조건 → 질문 문장
charts.py      모듈 5 plotly 그림 다시 칠하기 · default 차트 스펙 그리기
ui.py          시안 디자인 토큰 CSS · HTML 조각
api.py         백엔드 호출
```

테스트: `pytest -q tests/test_streamlit_app.py` (Streamlit 이 없으면 화면 테스트는 건너뜀)
