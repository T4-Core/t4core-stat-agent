# AWS 배포 — EC2 3대 + Docker (KOS-50 · DB 연동)

DB 구조와 결정 사항은 [docs/AWS_DB.md](../docs/AWS_DB.md)에 있다. 이 문서는 순서대로 따라 하는 절차다. Compose 명령은 모두 저장소 루트에서 실행하고, `.env` 는 각 서버에서 만든다 (저장소에는 `.env.example` 만 올린다).

```
[팀 PC: 원본 56.9 GiB]                         [AWS us-west-2 · 같은 VPC]
 prepare → stats normalize → bundle  ──scp──▶  backend-server  FastAPI · PostgreSQL(kosis·app) · Redis
                                                    │ 프라이빗 IP:5432
                                                    ▼
                                               db-server       PostgreSQL + pgvector (vec)
                                               front-server    nginx ──프라이빗 IP:8000──▶ backend
```

### 원본 CSV(약 58 GiB)를 올리지 않아도 서버만으로 도나?

돈다. 서버가 답변할 때 쓰는 **검색 대상 표 1,092개의 값은 모두 backend-server 의 PostgreSQL 에 들어간다** (`stats load --all`). 팀 PC 를 꺼도 서버는 혼자 답한다 (`tests/test_db_aws.py` 가 원본 CSV · parquet 를 지운 상태에서 같은 질문의 답이 같은지 확인한다).

| | 원본 CSV (`kosis_data/raw`) | PostgreSQL `kosis` |
|---|---|---|
| 담긴 것 | KOSIS 응답 그대로 (이름·단위 글자가 행마다 반복) + 검색 대상이 아닌 표까지 (`estimate` 가 selected 몫을 보여 줌) | selected 표의 **모든 값** (코드 사전으로 정리) |
| 서버가 쓰나 | 안 씀 — 정규화 · CSV 값 사전 · 수집을 다시 할 때만 | 질문마다 씀 |

원본은 "데이터를 다시 만들 때의 재료"라 갱신 작업을 하는 곳에만 있으면 된다. 전부 서버에 두고 싶으면:

- 검색 대상이 아닌 표까지 DB 에: `stats normalize --catalog-all` → `bundle create` → 서버에서 `stats load --all` (검색에는 안 나오고 DB 에만 있음)
- 원본 자체도 서버에: `stats estimate` 의 원본 크기 + PostgreSQL 예상 크기가 약 80 GB 를 넘지 않을 때만 (`scp -r kosis_data/raw` 를 `/srv/t4core/kosis_data/raw` 로). 그러면 서버에서도 `normalize` · `prepare` 를 돌릴 수 있다. 넘으면 관리자에게 디스크 증설(EBS)을 요청한다.

| 순서 | 어디서 | 하는 일 | 걸리는 시간 (대략) |
|---|---|---|---|
| 1 | 팀 PC | 패치 적용 · 데이터 정규화 · 묶음 만들기 | 정규화 1~2시간 (처음 한 번) |
| 2 | AWS 콘솔 · 관리자 | 보안 그룹 확인 · 서버 켜기 · 프라이빗 IP 적기 | 10분 |
| 3 | db-server | Docker · pgvector 컨테이너 | 10분 |
| 4 | backend-server | Docker · 묶음 풀기 · PostgreSQL 적재 · 벡터 올리기 · FastAPI | 적재 = 행 1억 개에 10분 안팎 |
| 5 | front-server | Docker · nginx | 10분 (이미지 빌드) |
| 6 | 브라우저 | 확인 체크리스트 | 5분 |

---

## 1. 팀 PC — 패치와 데이터 준비

원본(`kosis_data`)이 있는 PC 에서 한다. 아래 명령은 Windows PowerShell 과 macOS·Linux 가 같다 (가상환경을 켠 상태).

### 1-1. 패치 적용

```sh
git checkout RAG_Module                  # develop 과 같은 상태
git apply --check t4core-aws-db.patch    # 충돌 없는지 먼저
git apply t4core-aws-db.patch
pip install -r requirements-dev.txt      # psycopg · psycopg-pool · redis 가 추가됨
pytest -q                                # 기존 테스트 그대로 통과 (DB 시험은 건너뜀)
```

서버에서도 같은 코드를 써야 하므로, 적용한 내용을 팀 브랜치에 커밋·푸시해 두면 서버에서 `git clone -b <브랜치>` 로 받기 쉽다. 푸시하지 않을 거면 패치 파일을 서버에 `scp` 로 올려 똑같이 `git apply` 한다.

### 1-2. 색인과 정규화

```sh
python -m backend.core.config                     # KOSIS_DATA_DIR ✓ 확인
python -m backend.rag.ingestion.prepare           # 메타 프로필 · 표 색인 · CSV 값 사전 (이미 했으면 바뀐 것만)
python -m backend.db stats normalize --all        # catalog.csv 의 selected 표 1,092개 → 정규화 parquet + 프로필
python -m backend.db stats estimate               # PostgreSQL 에 올릴 크기 어림
```

- `normalize` 는 이미 정규화한 표(원본보다 새 parquet)는 건너뛰므로 중간에 끊겨도 다시 실행하면 이어진다. 큰 표(원본 740 MB)는 1분 이상 걸린다.
- `estimate` 가 보여 주는 GiB 가 **60 GiB 를 넘으면** 4단계에서 `--max-rows` 로 큰 표를 parquet 로 남긴다 (backend 디스크 100 GB = OS·Docker 약 15 GB + 묶음 + PostgreSQL).

### 1-3. 임베딩 미리 만들기 (선택, HCX 비용 절약)

PC 에 이미 `storage/indices/embed_cache.sqlite` 가 있으면 건너뛴다. 없으면 한 번 만들어 두면 서버에서 HCX 를 다시 부르지 않는다 (표 설명문 1,092건).

```sh
python -c "from backend.rag.search.engine import get_search; get_search(log=print)"
```

### 1-4. 묶음 만들기

```sh
python -m backend.db bundle create --out t4core_bundle.tar.gz
```

| 묶음 안 | 내용 |
|---|---|
| `storage/parquet/processed/` · `profiles/` | 정규화 parquet · 프로필 → 서버에서 PostgreSQL 로 |
| `storage/parquet/meta_profiles.jsonl` · `dict/` · `series.json` · `storage/indices/table_index/` · `storage/csv_index/` · `storage/okf*/` | 검색 색인 (파일로 사용) |
| `kosis_data/catalog.csv` · `kosis_data/meta/` | 카탈로그 · 메타 (원본 CSV `raw/` 는 넣지 않음) |
| `storage/indices/embed_cache.sqlite` | HCX 임베딩 캐시 → 서버에서 pgvector 로 |

### 1-5. (선택) 내 PC 에서 먼저 확인

Docker Desktop 이 있으면 세 서버를 한 번에 띄워 볼 수 있다.

```sh
cp deploy/backend/.env.example deploy/backend/.env
#   PG_PASSWORD=아무값, HCX_API_KEY=키, STORAGE_HOST_DIR=./storage 의 절대 경로, KOSIS_HOST_DIR=kosis_data 절대 경로
#   VECTOR_DB_URL=postgresql://t4core_vector:<아래 비밀번호>@vector:5432/t4core_vector
printf "VECTOR_PG_PASSWORD=localpw\nVITE_USE_MOCK=false\n" > deploy/local/.env
docker compose --env-file deploy/local/.env -f deploy/local/compose.yml up -d --build
docker compose --env-file deploy/local/.env -f deploy/local/compose.yml run --rm backend python -m backend.db stats load --all
```

DB 연동 자동 시험 (같은 질문의 답이 parquet 모드와 PostgreSQL 모드에서 같은지, 세션·이력·벡터까지):

```sh
T4_TEST_DATABASE_URL=postgresql://... T4_TEST_VECTOR_DB_URL=postgresql://... T4_TEST_REDIS_URL=redis://localhost:6379/15 \
  pytest tests/test_db_aws.py -q
```

---

## 2. AWS — 보안 그룹 · 서버 켜기

### 2-1. 보안 그룹 (관리자에게 요청)

세 서버가 같은 VPC 에 있어야 프라이빗 IP 로 통신한다. 콘솔 요약에 보이는 **프라이빗 IP 세 개를 적어 둔다** (중지·시작해도 바뀌지 않는다).

| 서버 | 인바운드 | 출처 |
|---|---|---|
| front-server | TCP 80 | 0.0.0.0/0 (또는 팀 IP 만) |
| front-server | TCP 22 | 팀 IP |
| backend-server | TCP 8000 | **front-server 프라이빗 IP/32** |
| backend-server | TCP 22 | 팀 IP |
| db-server | TCP 5432 | **backend-server 프라이빗 IP/32** |
| db-server | TCP 22 | 팀 IP |

backend 의 PostgreSQL(5432)과 Redis 는 바깥에 열지 않는다 (compose 가 127.0.0.1 · 컨테이너 안에만 묶음).

### 2-2. 켜기와 접속

웹 콘솔에서 **db-server → backend-server → front-server** 순서로 시작 버튼을 누른다. 공인 IP 는 켤 때마다 바뀌니 접속할 때마다 콘솔에서 확인한다.

```sh
# macOS · Linux
chmod 400 team-key.pem
ssh -i team-key.pem ubuntu@<공인 IP>          # Amazon Linux 면 ec2-user@
# Windows PowerShell (키 권한 오류가 나면)
icacls .\team-key.pem /inheritance:r /grant:r "$($env:USERNAME):R"
ssh -i .\team-key.pem ubuntu@<공인 IP>
```

### 2-3. 세 서버 공통 준비

```sh
git clone -b develop https://github.com/T4-Core/t4core-stat-agent.git ~/t4core   # 또는 패치를 푸시한 브랜치
cd ~/t4core
# 브랜치에 패치를 푸시하지 않았다면: (PC 에서) scp -i team-key.pem t4core-aws-db.patch ubuntu@<공인 IP>:~/
git apply ~/t4core-aws-db.patch
sudo bash deploy/scripts/ec2_bootstrap.sh backend    # db-server 는 db, front-server 는 front
exit                                                 # docker 그룹 적용을 위해 다시 접속
```

`ec2_bootstrap.sh` 는 Docker·Compose 설치, 부팅 때 Docker 자동 시작, `/srv/t4core` 폴더, (4 GiB 서버) 스왑 2 GiB 를 한다.

---

## 3. db-server (pgvector)

```sh
cd ~/t4core
cp deploy/db/.env.example deploy/db/.env
nano deploy/db/.env                    # VECTOR_PG_PASSWORD=긴 비밀번호 (backend 의 VECTOR_DB_URL 에 같은 값)
docker compose --env-file deploy/db/.env -f deploy/db/compose.yml up -d
docker compose --env-file deploy/db/.env -f deploy/db/compose.yml ps        # healthy 확인
docker compose --env-file deploy/db/.env -f deploy/db/compose.yml exec vector \
  psql -U t4core_vector -d t4core_vector -c "SELECT extversion FROM pg_extension WHERE extname='vector';"
```

스키마(`vec`)는 backend 가 시작할 때 만든다.

---

## 4. backend-server (FastAPI · PostgreSQL · Redis)

### 4-1. 묶음 올리기 · 풀기

```sh
# 팀 PC 에서
scp -i team-key.pem t4core_bundle.tar.gz ubuntu@<backend 공인 IP>:/srv/t4core/
# backend-server 에서
cd /srv/t4core && tar -xzf t4core_bundle.tar.gz && rm t4core_bundle.tar.gz
ls /srv/t4core/storage /srv/t4core/kosis_data        # storage/{parquet,indices,csv_index,okf…} · kosis_data/{catalog.csv,meta}
sudo chown -R 1000:1000 /srv/t4core/storage          # 컨테이너 사용자(app, uid 1000)가 쓸 수 있게
```

### 4-2. 환경설정

```sh
cd ~/t4core
cp deploy/backend/.env.example deploy/backend/.env
nano deploy/backend/.env
#   PG_PASSWORD=긴 비밀번호
#   VECTOR_DB_URL=postgresql://t4core_vector:<db-server 비밀번호>@<db-server 프라이빗 IP>:5432/t4core_vector
#   HCX_API_KEY=…   ADMIN_TOKEN=…(대화 이력 조회용)
alias dcb='docker compose --env-file deploy/backend/.env -f deploy/backend/compose.yml'
```

### 4-3. 이미지 · DB 띄우기 · 연결 확인

```sh
dcb build backend
dcb up -d postgres redis
timeout 3 bash -c '</dev/tcp/<db-server 프라이빗 IP>/5432' && echo 열림   # 아무것도 안 나오면 보안 그룹 확인
dcb run --rm backend python -m backend.db migrate        # kosis · app · vec 스키마
dcb run --rm backend python -m backend.db check          # database · vector_db · redis 모두 "ok": true
```

### 4-4. 통계값 적재 (PostgreSQL)

오래 걸리므로 컨테이너를 백그라운드로 띄우고 로그를 본다 (SSH 가 끊겨도 계속).

```sh
dcb run -d --name t4-load backend python -m backend.db stats load --all
docker logs -f t4-load          # [load] 표마다 행 수·초 → 마지막 줄 "올림 N · 그대로 0 · 실패 0"
docker rm t4-load
dcb run --rm backend python -m backend.db stats verify --sample 200    # "같음 N · 다름 0"
dcb run --rm backend python -m backend.db stats status                 # 표 수 · 행 수 · GiB · 행당 B
df -h /
```

- 디스크가 모자라면: `stats load --all --max-rows 30000000` — 3천만 행이 넘는 표는 올리지 않고 서버의 parquet 로 읽는다 (그 표의 parquet 는 지우지 말 것).
- 적재·확인이 끝나면 PostgreSQL 에 올린 표의 parquet 는 지워도 된다 (`rm -rf /srv/t4core/storage/parquet/processed`). 남겨 두면 PostgreSQL 이 멈췄을 때 `STAT_BACKEND=parquet` 로 바로 되돌릴 수 있다.
- `stat_table.load_report.code_variants` 에 0 이 아닌 표가 있으면, 같은 코드에 이름이 여러 개인 표다 (가장 많이 쓴 이름으로 통일). `verify` 가 다름을 알리면 그 표 이름을 팀에 공유한다.

### 4-5. 벡터 올리기 (db-server)

```sh
dcb run --rm backend python -m backend.db vectors import-sqlite /app/storage/indices/embed_cache.sqlite
dcb run --rm backend python -m backend.db vectors sync      # dense 문서 묶음 (없는 임베딩만 HCX 호출)
dcb run --rm backend python -m backend.db vectors nearest "대전 인구 추이"   # 가까운 표가 나오면 ok
```

### 4-6. FastAPI 시작

```sh
dcb up -d backend
dcb logs -f backend                         # Uvicorn running on http://0.0.0.0:8000
curl -s localhost:8000/health               # stat_backend: postgres · n_pg_tables: 1092 근처
curl -s localhost:8000/api/v1/system/db     # database · vector_db · redis 모두 ok
```

첫 질문 때 검색기(BM25 · Kiwi · dense)를 메모리에 올리느라 수십 초 걸린다. 미리 데우려면 `curl -s -X POST localhost:8000/api/v1/chat -H 'Content-Type: application/json' -d '{"question":"작년 서울 인구"}'`.

---

## 5. front-server (nginx)

```sh
cd ~/t4core
cp deploy/frontend/.env.example deploy/frontend/.env
nano deploy/frontend/.env
#   BACKEND_UPSTREAM=<backend-server 프라이빗 IP>:8000
#   VITE_USE_MOCK=false
#   (관리자 화면 쓰면) VITE_SUPABASE_URL · VITE_SUPABASE_PUBLISHABLE_KEY
curl -s http://<backend-server 프라이빗 IP>:8000/health      # 보안 그룹 확인
docker compose --env-file deploy/frontend/.env -f deploy/frontend/compose.yml up -d --build
```

`VITE_*` 값은 이미지에 빌드 때 들어가므로 바꾸면 `--build` 로 다시 빌드한다. `BACKEND_UPSTREAM` 만 바꿀 때는 `up -d` 만 하면 된다.

---

## 6. 확인 체크리스트

| 확인 | 방법 | 기대 |
|---|---|---|
| 화면 | 브라우저 `http://<front 공인 IP>/` | 첫 화면 |
| 백엔드 경유 | `http://<front 공인 IP>/health` | `"status":"ok"`, `"stat_backend":"postgres"` |
| 질문 | 화면에서 "최근 5년간 대전의 인구 변화 추이" | 답변 · 차트 · 근거 표 |
| 표 선택 이어가기 | 선택 화면이 나오는 질문 → 표 고르기 | 답변 (HCX 재작성 다시 안 함) |
| 새로고침 복구 | 답변 생성 중 새로고침 | 잠시 뒤 결과가 붙음 (같은 질문을 다시 보내지 않음) |
| 세션 | `curl localhost:8000/api/v1/sessions/<질문 id>` (backend) | `status`, `response` |
| 대화 이력 | `curl -H "X-Admin-Token: …" localhost:8000/api/v1/history?limit=5` | 방금 질문들 |
| 관리자 화면 | `http://<front 공인 IP>/admin/` | 로그인 화면 |

---

## 7. 매일 운영

- **켜는 순서**: db-server → backend-server → front-server. Docker 와 컨테이너(`restart: unless-stopped`)는 부팅 때 자동으로 뜬다. 웹 콘솔의 자동 중지를 켜 두어도 다시 켜면 그대로 돌아온다.
- db-server 가 꺼진 채로 backend 를 쓰면: 질문 임베딩 캐시는 HCX 로 대신 계산하고, dense 점수는 backend 에 남긴 파일 사본으로 계산한다. 사본이 없으면 "벡터 DB 에 연결하지 못함" 오류 → db-server 를 켜면 다음 요청부터 정상.
- front-server 공인 IP 가 켤 때마다 바뀌므로 시연 주소가 바뀐다. 고정 주소가 필요하면 관리자에게 front-server 탄력적 IP 를 요청한다.
- 로그: `dcb logs --tail 200 backend` · 자원: `docker stats` · 디스크: `df -h /`, `docker system df`.
- 코드 갱신: `git pull` (또는 새 패치 apply) → `dcb build backend && dcb up -d backend` / front 는 `up -d --build`.

## 8. 데이터 갱신 (주기적으로)

```sh
# 팀 PC: 수집(바뀐 표만) → 색인 → 정규화 → 묶음
python -m backend.rag.ingestion.prepare
python -m backend.db stats normalize --all
python -m backend.db bundle create --out t4core_bundle.tar.gz
scp -i team-key.pem t4core_bundle.tar.gz ubuntu@<backend 공인 IP>:/srv/t4core/
# backend-server
cd /srv/t4core && tar -xzf t4core_bundle.tar.gz && rm t4core_bundle.tar.gz && sudo chown -R 1000:1000 storage
cd ~/t4core
dcb run --rm backend python -m backend.db stats load --all          # 바뀐 표만 (서버를 켠 채로 바꿔 끼움)
dcb run --rm backend python -m backend.db vectors import-sqlite /app/storage/indices/embed_cache.sqlite
dcb restart backend                                                  # 새 색인 파일을 메모리로
dcb run --rm backend python -m backend.db vectors prune --keep 1     # 옛 dense 묶음 정리
```

색인만 바뀌었으면 `bundle create --parts indices,profiles,embed` 로 작게 만든다. 표 몇 개만 다시 올릴 때는 `stats load --tables DT_1B040A3 DT_1IN1503`.

## 9. 백업 (후순위)

```sh
# 대화 이력 (다시 만들 수 없는 것)
dcb exec -T postgres pg_dump -U t4core -d t4core -n app -Fc > ~/app_$(date +%F).dump
# 복구
dcb exec -T postgres pg_restore -U t4core -d t4core --clean < ~/app_2026-12-01.dump
```

`kosis`(통계값)와 `vec`(임베딩)은 묶음으로 다시 만들 수 있어 백업하지 않아도 된다. Redis 세션은 AOF 로 디스크(`/srv/t4core/redis`)에 남는다.

## 10. 문제 해결

| 증상 | 확인 | 해결 |
|---|---|---|
| `/health` 의 `n_pg_tables` 가 null | `dcb run --rm backend python -m backend.db check` | `DATABASE_URL`·비밀번호, `dcb ps` 로 postgres healthy |
| 409 "준비 데이터 없음" | `ls /srv/t4core/storage/indices/table_index` | 묶음의 색인이 안 풀렸음 → 4-1 다시 |
| 409 "원본 CSV 가 없어" | `stats status` 에 그 표가 있는지 | 그 표만 `stats load --tables …` (parquet 가 있어야 함) |
| "벡터 DB(VECTOR_DB_URL)에 연결하지 못함" | backend 에서 `timeout 3 bash -c '</dev/tcp/<db IP>/5432' && echo 열림` | db-server 켜기 · 보안 그룹 5432 · 비밀번호 |
| `PoolTimeout` | `docker stats`, PostgreSQL 로그 | `DB_POOL_MAX`(기본 10) · `max_connections` |
| 502 (nginx) | front 에서 `curl <backend IP>:8000/health` | `BACKEND_UPSTREAM`, 보안 그룹 8000 |
| Permission denied (storage) | `ls -ln /srv/t4core/storage` | `sudo chown -R 1000:1000 /srv/t4core/storage` |
| 디스크 부족 | `df -h /`, `docker system df` | 적재한 표의 parquet 삭제, `docker image prune -f`, `--max-rows` |
| 세션 409 "만료" | `curl …/api/v1/sessions/<id>` | 24시간 지남 → 질문을 다시 보냄 (`SESSION_TTL_SECONDS`) |

되돌리기: `deploy/backend/.env` 에 `STAT_BACKEND=parquet`, `VECTOR_STORE=file` 을 넣고 `dcb up -d backend` 하면 parquet·sqlite 로 돌아간다 (parquet 를 지우지 않았을 때).

## 11. 팀원이 RAG · 에이전트 코드를 고칠 때

서버는 **코드는 git 으로, 데이터는 묶음으로** 받는다. 질의 분석 · 검색 순위 · 차트 · 답변 문장 · 프롬프트 · `configs/*.yaml` 처럼 데이터 모양을 바꾸지 않는 수정은 `git pull` → `dcb build backend && dcb up -d backend` 만 하면 된다.

`.github/workflows/ci.yml` 이 push · PR 마다 아래를 확인한다 (실제 PostgreSQL · pgvector · Redis 를 띄워서). 빨간불이면 서버에서도 깨진다.

| 고친 것 | 서버에서 할 일 | CI 가 잡는 것 |
|---|---|---|
| RAG · 에이전트 로직, 프롬프트, configs | 이미지 다시 빌드 | 기존 테스트 전부 + parquet ↔ PostgreSQL 같은 답 (`test_db_aws.py`) |
| `requirements.txt` | 이미지 다시 빌드 | Docker 이미지 빌드 · import |
| 프론트엔드 | front 에서 `up -d --build` | `npm run build` · `build:admin` |
| prepare 산출물(색인·사전) 추가·변경 | 팀 PC 에서 `prepare` → `bundle create --parts indices,profiles,embed` → 서버에 풀고 `dcb restart backend` | 새 storage 산출물이 묶음에 들어가는지 (`test_db_guards.py`) |
| 정규화 규칙 (`normalize.py`, `KIND_RULES_VERSION`) | 팀 PC 에서 `stats normalize --all` → 묶음 → 서버 `stats load --all` (바뀐 표만) | parquet 열이 바뀌었는데 DB 쪽을 안 고치면 실패 (`test_db_guards.py`) · 옛 규칙 표는 `stats status` 와 서버 로그가 알려 줌 |
| 통계값을 읽는 새 코드 | - | `read_parquet(...)` 로 직접 읽으면 실패 → `stat_store.relation(con, prof, where, base=VIEW_OUT_DIR)` 로 읽을 것 |
| 검색 dense 설정 (`dense_docs` · 임베더) | 없음 — 첫 검색 때 새 묶음을 db-server 에 만듦 (없는 임베딩만 HCX) · 나중에 `vectors prune` | DB 점수 = 메모리 점수 |

규칙은 두 가지다. **통계값은 `stat_store` 로만 읽는다.** 정규화 결과의 열을 바꾸면 `backend/db/sql/main/001_kosis.sql` · `stat_store.py` · `stats.py` 를 함께 고친다 (테스트 실패 메시지가 파일을 알려 준다).
