# KOSIS 통계 에이전트 프론트엔드

사용자 화면과 관리자 콘솔(쿼리 테스트, 모듈별 에러 통계, History)이 들어 있습니다.

## 빠른 실행

**준비물:** Python 3.12, Node.js 24 이상, 백엔드 설정(`.env`)과 수집 데이터

Python 가상환경이 켜져 있다는 전제이며, 터미널 2개를 사용합니다.
관리자 페이지의 경우 frontend 관리자에게 url와 공개키를 받아야 합니다.


### 처음 한 번

**설정**

`admin/.env.local`에는 프론트 담당자에게 공유받은 값을 넣습니다.

- `admin/.env.example` 파일을 복사한 후 이름을 `.env.local`로 수정합니다.
- 그리고 아래 변수 내용을 채웁니다.

```text
VITE_SUPABASE_URL=
VITE_SUPABASE_PUBLISHABLE_KEY=
VITE_ADMIN_EMAIL_DOMAIN=
```

`service_role` 또는 `secret` 키는 절대 넣지 마세요.

**터미널 1: 백엔드 (저장소 루트에서)**

```bash
python -m uvicorn backend.main:app --port 8000   # 백엔드 서버 켜기
```

**터미널 2: 프론트 (저장소 루트에서)**

PowerShell:

```powershell
cd frontend\web                                    # 프론트 폴더로 이동
npm install                                        # 라이브러리 설치
npm run dev                                        # 사용자 화면 + 관리자 콘솔 켜기
```

Bash:

```bash
cd frontend/web                          # 프론트 폴더로 이동
npm install                              # 라이브러리 설치
npm run dev                              # 사용자 화면 + 관리자 콘솔 켜기
```



### 다음부터

```bash
# 터미널 1: 저장소 루트
python -m uvicorn backend.main:app --port 8000

# 터미널 2: 저장소 루트
cd frontend/web
npm run dev
```

### 접속 주소

| 화면 | 주소 | 이동 방법 |
|---|---|---|
| 사용자 화면 | <http://localhost:5173> | 관리자 콘솔 왼쪽 위 `T4core` |
| 관리자 콘솔 | <http://localhost:5174> | 사용자 화면 오른쪽 위 동그라미 버튼 |

| 명령 | 동작 |
|---|---|
| `npm run dev` | 사용자 화면 + 관리자 콘솔 |
| `npm run dev:web` | 사용자 화면만 |
| `npm run admin` | 관리자 콘솔만 |

> 쿼리를 실행하면 HCX 비용이 발생하고, 시작한 쿼리는 중간에 멈출 수 없습니다.

## 폴더 구조

```text
frontend/web/
├─ index.html              사용자 화면 시작 파일
├─ package.json            라이브러리와 실행 명령
├─ vite.config.ts          사용자 화면 개발 서버 설정
├─ .env.example            사용자 화면 설정 예시
├─ public/character/       3D 나무늘보 파일
├─ scripts/
│  ├─ dev.mjs              두 서버를 함께 켜고 끄는 스크립트
│  └─ generate-api-types.mjs  백엔드 스키마로 API 타입 생성
├─ src/                    사용자 화면
│  ├─ api/                 백엔드 호출과 응답 변환
│  ├─ character/           캐릭터 표시
│  ├─ components/          공통 화면 부품
│  ├─ data/                화면 데이터 타입과 예시 데이터
│  ├─ pages/               메인, 생성 중, 선택, 되묻기, 결과, 히스토리
│  ├─ store/               질문 전송과 브라우저 기록 저장
│  └─ styles/              디자인 토큰과 화면별 CSS
└─ admin/                  관리자 콘솔
   ├─ index.html           관리자 화면 시작 파일
   ├─ preview.html         실행 중 보여주는 실제 사용자 화면
   ├─ vite.config.ts       관리자 개발 서버 설정 (5174번 포트)
   ├─ .env.example         관리자 설정 예시
   ├─ supabase/            DB 구조(schema.sql)와 설정 안내(SETUP.md)
   └─ src/
      ├─ pages/            로그인, 쿼리 테스트, 에러 통계, History
      ├─ components/       결과 표, 단계별 중간 결과, 그래프
      ├─ runner/           쿼리 순차 실행, 결과 압축, CSV
      ├─ adapters/         응답을 모듈별 단계와 오류로 변환
      ├─ preview/          사용자 화면을 iframe으로 연결
      ├─ supabase/         로그인, 결과 저장, 리포트 조회
      └─ styles/           관리자 전용 CSS
```

Supabase 프로젝트와 팀원 계정 설정은 [admin/supabase/SETUP.md](admin/supabase/SETUP.md)를 따릅니다.

## 아키텍처

```text
[사용자 화면 :5173] ──/api/v1──▶ Vite 프록시 ──▶ [FastAPI :8000] ──▶ HCX · KOSIS 데이터
        ▲                                              ▲
        │ iframe으로 재사용                             │ /api/v1
        │                                              │
[관리자 콘솔 :5174] ────────────▶ Vite 프록시 ──────────┘
        │
        │ 로그인 · 실행 결과 · 해결 체크 · History
        ▼
   [Supabase DB] ◀── 팀원 전체가 같은 결과를 조회
```

- **사용자 화면:** 질문을 `POST /api/v1/chat`으로 보내고, 기록은 브라우저(`localStorage`, IndexedDB)에 저장합니다.
- **관리자 콘솔:** 실제 사용자 화면을 iframe으로 띄워 쿼리를 하나씩 실행하고, 되묻기와 표 선택도 그 화면에서 직접 고릅니다.
- **쿼리 실행:** 각자 PC의 백엔드에서 실행되며, 결과만 Supabase에 저장되어 팀원과 공유됩니다.
- **결과 저장:** 백엔드 응답을 압축해 저장하므로 History에서 차트, 답변, 중간 단계를 다시 볼 수 있습니다.
- **분리 구조:** `admin/`은 `src/`를 가져다 쓰지만, `src/`의 화면 코드는 `admin/`을 가져오지 않습니다.
- **보안:** `VITE_`로 시작하는 값은 브라우저에 공개되므로 비밀값을 넣지 않습니다. Supabase 데이터는 로그인한 팀원만 읽을 수 있습니다.
