# KOSIS 통계 에이전트 프론트엔드

## 빠른 실행

**준비물:** Python 3.12, Node.js 24 이상, KOSIS·HCX API 키, 수집 데이터(`storage/kosis_data`)

아래 명령은 Windows PowerShell 기준이며, 터미널 2개를 사용합니다. **터미널 1은 Python 가상환경이 이미 켜져 있다는 전제입니다.**

### 처음 한 번

**터미널 1: 백엔드 (저장소 루트)**

```powershell
python -m pip install -r requirements-dev.txt    # 백엔드에 필요한 Python 패키지 설치
Copy-Item .env.example .env                      # 백엔드 설정 파일(.env)을 예시에서 복사
notepad .env                                     # KOSIS_API_KEY, HCX_API_KEY 등을 입력하고 저장
python -m backend.rag.ingestion.prepare          # 수집 데이터로 검색 색인과 값 사전 만들기
python -m uvicorn backend.main:app --port 8000   # 백엔드 서버 켜기 (8000번 포트)
```

**터미널 2: 프론트 (저장소 루트에서 시작)**

```powershell
cd frontend\web                      # 프론트 폴더로 이동
npm install                          # 화면에 필요한 라이브러리 설치
Copy-Item .env.example .env.local    # 프론트 설정 파일(.env.local)을 예시에서 복사
npm run dev                          # 프론트 개발 서버 켜기 (5173번 포트)
```

브라우저에서 <http://localhost:5173>을 엽니다.

### 다음부터

```powershell
# 터미널 1: 저장소 루트
python -m uvicorn backend.main:app --port 8000   # 백엔드 서버 켜기 (8000번 포트)

# 터미널 2: 저장소 루트
cd frontend\web    # 프론트 폴더로 이동
npm run dev        # 프론트 개발 서버 켜기 (5173번 포트)
```

### Bash로 실행

Windows Git Bash 기준이며, 터미널 1은 Python 가상환경이 이미 켜져 있다는 전제입니다. macOS·Linux에서는 `notepad`를 `nano`로 바꿉니다.

**처음 한 번: 터미널 1, 백엔드 (저장소 루트)**

```bash
python -m pip install -r requirements-dev.txt    # 백엔드에 필요한 Python 패키지 설치
cp .env.example .env                             # 백엔드 설정 파일(.env)을 예시에서 복사
notepad .env                                     # KOSIS_API_KEY, HCX_API_KEY 등을 입력하고 저장
python -m backend.rag.ingestion.prepare          # 수집 데이터로 검색 색인과 값 사전 만들기
python -m uvicorn backend.main:app --port 8000   # 백엔드 서버 켜기 (8000번 포트)
```

**처음 한 번: 터미널 2, 프론트 (저장소 루트에서 시작)**

```bash
cd frontend/web               # 프론트 폴더로 이동
npm install                   # 화면에 필요한 라이브러리 설치
cp .env.example .env.local    # 프론트 설정 파일(.env.local)을 예시에서 복사
npm run dev                   # 프론트 개발 서버 켜기 (5173번 포트)
```

**다음부터**

```bash
# 터미널 1: 저장소 루트
python -m uvicorn backend.main:app --port 8000   # 백엔드 서버 켜기 (8000번 포트)

# 터미널 2: 저장소 루트
cd frontend/web    # 프론트 폴더로 이동
npm run dev        # 프론트 개발 서버 켜기 (5173번 포트)
```

> **비용 주의:** 화면에서 질문을 보내면 유료 HCX가 호출됩니다. 백엔드나 API 키 없이 화면만 보려면 `frontend\web\.env.local`에서 `VITE_USE_MOCK=true`로 바꾸고 터미널 2만 실행하세요.

---

사용자가 통계를 질문하면 답변, 차트, 근거 표를 보여주는 React 웹 화면입니다. 기본값은 **실제 FastAPI 백엔드 연결**이며, `VITE_USE_MOCK=true`로 바꾸면 HCX 비용 없이 예시 데이터로 볼 수 있습니다.

식당에 비유하면 프론트엔드는 **홀**, 백엔드는 **주방**입니다. 프론트는 주문(질문)을 주방에 전달하고, 완성된 음식(답변)을 받아 보기 좋게 내놓습니다.

## 1. 결정 사항

| 항목 | 결정 |
|---|---|
| 화면 | React 19, TypeScript, Vite |
| 디자인 기준 | Figma `Kosis_UI` **Page 2** (Page 1은 이전 와이어프레임) |
| 글꼴 | **Pretendard만 사용** (시안의 Noto Sans KR, Arial도 Pretendard로 통일) |
| 화면 크기 | 1440×900 기준, 다른 PC 크기는 비율 유지, 모바일 제외 |
| 데이터 | 예시 모드는 `src/data/examples.ts`, 실제 모드는 FastAPI 응답 |
| 히스토리 | 브라우저에 저장 (목록은 `localStorage`, 실제 응답은 IndexedDB) |
| 차트 | 예시 모드는 SVG, 실제 모드는 백엔드 Plotly JSON에 Figma 색상·글꼴 적용 |
| 나무늘보 | 지금은 Figma 이미지 사용, 이후 캐릭터 담당자가 R3F로 교체 |
| 백엔드 | 기존 FastAPI를 HTTP로만 호출, **백엔드 코드는 수정하지 않음** |

## 2. 실행하기

필요한 프로그램: Node.js 24 이상

**터미널 1: 가상환경이 켜진 상태로 저장소 루트에서 백엔드 실행**

```powershell
python -m uvicorn backend.main:app --port 8000
```

**터미널 2: 이 폴더에서 프론트 실행**

```powershell
npm install
Copy-Item .env.example .env.local
npm run dev
```

macOS·Linux에서는 `Copy-Item` 대신 `cp .env.example .env.local`을 사용합니다. 브라우저에서 <http://localhost:5173>을 엽니다.

> **비용 주의:** 질문 1개는 HCX를 약 3~5회 호출할 수 있습니다. 둘 다 비교는 추가로 약 4~8회 호출합니다. 화면만 확인할 때는 `.env.local`에서 `VITE_USE_MOCK=true`로 바꾸세요.

| 명령 | 하는 일 |
|---|---|
| `npm run dev` | 개발 서버 실행 |
| `npm run typecheck` | TypeScript 오류 검사 |
| `npm run build` | 오류 검사 후 배포용 파일을 `dist/`에 생성 |
| `npm run preview` | 빌드 결과를 로컬에서 확인 |
| `npm run gen:api` | 켜져 있는 백엔드의 스키마로 API 타입 재생성 (HCX 호출 없음) |

히스토리를 처음 상태로 되돌리려면 브라우저 개발자 도구에서 `localStorage`의 `kosis.history.v1`(예시) 또는 `kosis.history.live.v1`(실제)을 삭제합니다.

## 3. 화면과 주소

| 화면 | 주소 | Figma |
|---|---|---|
| Main, 지역·시점·대상 선택, 추천 | `/` | 1, 1-1 ~ 1-4 |
| 답변 생성 중 | `/generating/:id` | 2 |
| 통계표 선택 | `/select/:id` | 3 |
| 되묻기 | `/clarify/:id` | 시안 없음, 기존 칩 디자인 사용 |
| 범위 밖, 오류 안내 | `/notice/:id` | 시안 없음, 기존 빈 화면 디자인 사용 |
| 결과 (한 개씩·한번에, 차트 2~5개) | `/result/:id` | 4, 4-2 |
| 크게 보기 (나란히·한 개씩·겹쳐서) | `/result/:id` 안의 팝업 | 4-3 |
| 사용한 통계표 상세 | `/result/:id/tables/:viewNo` | 4-1 |
| 히스토리, 빈 화면 | `/history` | 5, 5-1 |

### 프로토타입과 다르게 연결한 동작

시안의 디자인은 유지하고, 실제 서비스에 맞지 않는 클릭 동작만 아래처럼 바꿨습니다.

- 최근 질문과 `결과 다시 열기`는 해당 결과로 이동합니다.
- `이어서 질문`은 해당 결과의 입력창으로 이동합니다.
- 답변 생성 후에는 백엔드의 `status`에 따라 결과, 되묻기, 통계표 선택, 안내 화면으로 이동합니다. 예시 모드에서는 질문에 `1인 가구`가 있으면 통계표 선택으로 갑니다.
- `질문 다시 쓰기`는 Main으로 이동합니다.
- 시점 탭, 적용, 차트 넘기기, 복사, 헤더, 상세의 돌아가기처럼 시안에 연결이 빠진 동작을 채웠습니다.
- 통계표 상세 2번은 시안에 상단 버튼이 없지만, 돌아갈 수 있도록 1번과 같은 상단 영역을 유지했습니다.

## 4. 폴더와 파일

```text
frontend/
├─ index.html                   브라우저가 처음 여는 빈 페이지
├─ package.json                 필요한 라이브러리와 실행 명령
├─ package-lock.json            라이브러리의 정확한 버전 기록 (자동 생성)
├─ tsconfig.json                TypeScript 검사 규칙
├─ vite.config.ts               개발 서버 설정, /api 요청을 백엔드로 전달
├─ .env.example                 팀원이 복사해서 쓰는 환경변수 예시
├─ .env.local                   내 PC 전용 설정 (git 제외)
├─ .gitignore                   git에 올리지 않을 파일 목록
├─ scripts/
│  └─ generate-api-types.mjs    백엔드 스키마로 API 타입 생성
└─ src/
   ├─ main.tsx                  프로그램 시작점, 글꼴과 CSS 로드
   ├─ App.tsx                   주소별 화면 연결
   ├─ api/                      백엔드와 연락하는 곳
   │  ├─ client.ts              공통 요청, 시간 제한, 에러 처리
   │  ├─ chat.ts                POST /chat, 조건 판정 호출
   │  ├─ adapters.ts            백엔드 응답을 화면 데이터로 변환
   │  ├─ openapi.d.ts           자동 생성된 API 타입 (직접 수정 금지)
   │  └─ types.ts               API 타입의 짧은 이름
   ├─ assets/figma/             Figma에서 내려받은 나무늘보 이미지와 아이콘
   ├─ character/index.tsx       캐릭터의 유일한 입구
   ├─ components/
   │  ├─ Layout.tsx             1440×900 화면 틀, 헤더, 태그, 질문 표시
   │  ├─ FilterPanels.tsx       지역·시점·대상 드롭다운
   │  ├─ StatChart.tsx          예시 차트, 실제 차트 분기
   │  ├─ PlotlyChart.tsx        백엔드 Plotly 차트에 디자인 적용
   │  ├─ EvidenceTable.tsx      근거 표
   │  ├─ ResultDetailModal.tsx  차트 크게 보기 팝업
   │  └─ download.ts            CSV, PNG 내려받기
   ├─ data/
   │  ├─ types.ts               화면에서 쓰는 데이터 모양
   │  └─ examples.ts            예시 통계, 선택지, 히스토리
   ├─ pages/
   │  ├─ MainPage.tsx           Main
   │  ├─ GeneratingPage.tsx     답변 생성 중
   │  ├─ SelectPage.tsx         통계표 선택
   │  ├─ ClarifyPage.tsx        되묻기
   │  ├─ NoticePage.tsx         범위 밖, 오류 안내
   │  ├─ ResultPage.tsx         결과
   │  ├─ ViewDetailPage.tsx     통계표 상세 (예시)
   │  ├─ LiveViewDetail.tsx     통계표 상세 (실제)
   │  └─ HistoryPage.tsx        히스토리
   ├─ store/
   │  ├─ agent.ts               질문 전송, 중복 호출 방지, 응답 처리
   │  ├─ history.ts             질문 기록 저장, 삭제, 즐겨찾기
   │  └─ payloads.ts            실제 응답을 IndexedDB에 저장
   └─ styles/                   디자인 토큰과 화면별 CSS
```

## 5. 나중에 할 일

### 중단 기능

현재 `중단`은 **화면 대기만 멈춥니다.** 이미 시작된 `/chat` 작업과 HCX 호출은 서버에서 끝까지 실행되어 비용이 발생합니다.

- [ ] **방법 A (백엔드 수정 없음):** `/chat` 대신 `/rag/analyze` → `/rag/views` → `/agent/modules`를 순서대로 호출하고, 단계 사이에서 중단 여부를 확인합니다. 다음 단계의 HCX를 막을 수 있고 실제 진행 단계도 표시할 수 있습니다.
  - `/agent/modules` 실행 중에는 멈출 수 없습니다.
  - `/agent/modules`는 `/chat`의 "표에 없는 지표" 사전 검사와 주의사항 처리를 하지 않으므로 이 규칙을 프론트에 옮겨야 합니다.
- [ ] **방법 B (백엔드 수정 필요):** 취소 API를 추가하고 HCX 호출 직전마다 취소 여부를 확인합니다. 백엔드 담당자와 협의와 허락이 필요합니다. 이미 전송된 HCX 1회는 취소되지 않습니다.

### 실제 호출 검증

- [ ] 실제 백엔드와 HCX로 정상, 되묻기, 표 선택, 둘 다 비교를 확인합니다. 약 13~23회의 HCX 호출이 예상되며 실행 전 승인이 필요합니다.
- [ ] 막대 외의 실제 차트 종류(선, 도넛, 지도 등)가 디자인에 맞게 표시되는지 확인합니다. 저장된 실제 응답에는 막대 차트만 있습니다.

### 임시로 구현한 기능

- [ ] **진행 단계:** 시간 기준 표시입니다. 진행 이벤트(SSE 등)나 단계별 호출이 생기면 실제 단계로 교체합니다.
- [ ] **이어서 질문:** 백엔드가 대화를 기억하지 않아 직전 질문을 앞에 붙여 보냅니다.
- [ ] **추천 질문과 조건 추천:** 고정 문구입니다. `/rag/search` 연결은 비용 확인 후 진행합니다.
- [ ] **히스토리:** 브라우저에만 저장됩니다. 계정별로 유지하려면 백엔드 API가 필요합니다.

### 그 외

- [ ] 캐릭터 담당자의 R3F 캐릭터로 교체합니다.
- [ ] 배포 방식과 `/api` 전달 서버를 정합니다.

## 6. 백엔드 연결 방식

프론트는 백엔드의 **폴더 위치를 모르고 HTTP 주소만** 사용합니다. 이 폴더를 어디로 옮겨도 `.env.local`만 맞추면 됩니다.

```text
브라우저 → /api/v1/chat → Vite 개발 서버 → BACKEND_URL/api/v1/chat → FastAPI
```

| 환경변수 | 의미 | 기본값 |
|---|---|---|
| `BACKEND_URL` | FastAPI 서버 주소 | `http://localhost:8000` |
| `VITE_API_BASE_PATH` | API 공통 경로 | `/api/v1` |
| `VITE_USE_MOCK` | `false`면 실제 백엔드 호출, `true`면 예시 모드 | `false` |

- 백엔드에 CORS 설정이 없으므로 개발 서버의 프록시를 사용합니다.
- 배포할 때는 Nginx 같은 서버가 정적 파일을 제공하고 `/api` 요청을 백엔드로 전달해야 합니다.
- `VITE_`로 시작하는 값은 브라우저에 공개됩니다. **환경변수에 API 키 같은 비밀값을 넣지 마세요.**

## 7. 캐릭터 담당자 안내

나머지 화면은 아래 사용법만 알고 있습니다. 이 사용법을 유지하면 `src/character/` 내부는 자유롭게 구성할 수 있습니다.

```tsx
<Character motion="thinking" size="L" className="generating-sloth" />
```

| `motion` | 의미 |
|---|---|
| `idle` | 질문을 기다리는 중 |
| `thinking` | 답변 생성 중 |
| `success` | 답변 완료 |
| `asking` | 통계표 선택 필요 |
| `error` | 연결 실패 또는 답변 불가 |

`size`는 `S`(127×141), `M`(224×241), `L`(331×367)입니다. R3F는 React 19에 맞는 `@react-three/fiber` v9를 사용합니다.

## 8. 작업 규칙

- 백엔드(`backend/`) 코드는 수정하지 않습니다.
- 프론트 코드에 절대 경로나 프론트 폴더 바깥을 가리키는 import를 넣지 않습니다.
- 백엔드 호출은 `src/api/`에서만 합니다.
- `src/api/openapi.d.ts`는 직접 고치지 말고 `npm run gen:api`로 다시 만듭니다.

## 9. 저장소 배치

- 이 폴더는 저장소의 `frontend/web/`에 두는 것을 권장합니다. 백엔드 폴더 위치에 의존하지 않고 `BACKEND_URL`로만 연결합니다.
- `node_modules/`, `dist/`, `.env.local`은 git에 올리지 않습니다.
- 저장소 루트 `.gitignore`가 `package-lock.json`을 제외하므로, 이 폴더의 `.gitignore`에서 잠금 파일만 다시 포함합니다.
- 백엔드는 루트 `frontend/` 전체를 `/lab` 주소로 공개합니다. 이 폴더의 환경변수 파일에 API 키 같은 비밀값을 넣지 마세요.
