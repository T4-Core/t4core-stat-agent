# KOS-50 Docker 배포

모든 Compose 명령은 저장소 루트에서 실행한다. 각 환경의 `.env`는 해당 호스트에서 작성한다. 저장소에는 `.env.example`만 커밋한다.

## 로컬 통합 테스트

`deploy/backend/.env.example`을 같은 폴더의 `.env`로 복사한다. `PG_PASSWORD`는 로컬 서비스 DB용으로 정하고, `STORAGE_HOST_DIR`와 `PG_HOST_DIR`에는 로컬 저장 경로를 지정한다. 원본 CSV가 다른 폴더에 있으면 `deploy/local/.env`의 `KOSIS_HOST_DIR`에 경로를 지정해 읽기 전용으로 연결한다.

`deploy/local/.env`에 `VECTOR_PG_PASSWORD`와 `VITE_USE_MOCK=true`를 설정한다.

```sh
docker compose --env-file deploy/local/.env -f deploy/local/compose.yml config --quiet
docker compose --env-file deploy/local/.env -f deploy/local/compose.yml up -d --build
```

`http://localhost/`, `/admin/`, `/health`를 확인한다. 실제 질의 테스트에는 백엔드의 HCX 설정이 필요하다. `VITE_USE_MOCK=false`로 바꾼 뒤 프론트엔드 이미지를 다시 빌드한다.

## AWS 개발 배포

### 벡터 DB EC2

`deploy/vector/.env.example`을 같은 폴더의 `.env`로 복사하고 `VECTOR_PG_PASSWORD`를 설정한다. SG는 5432 인바운드를 백엔드 EC2에서만 허용한다.

```sh
docker compose --env-file deploy/vector/.env -f deploy/vector/compose.yml up -d
docker compose --env-file deploy/vector/.env -f deploy/vector/compose.yml exec -T vector \
  psql -U t4core_vector -d t4core_vector -c "select extversion from pg_extension where extname='vector';"
```

`initdb/`의 SQL은 데이터 폴더가 비어 있을 때만 실행된다. 기존 데이터 폴더를 재사용해 조회 결과가 없으면 `CREATE EXTENSION vector;`를 직접 실행한다. `VECTOR_PG_USER`나 `VECTOR_PG_DB`를 바꿨다면 위 명령의 값도 바꾼다.

### 백엔드·프론트엔드 EC2

1. 백엔드 EC2의 저장소 경로에 `kosis_data` 원본 CSV와 메타데이터, Parquet, 표 색인, CSV 색인을 준비한다. 백엔드 실행 사용자에게 결과를 기록할 경로의 쓰기 권한을 준다.
2. 백엔드 EC2에서 환경설정을 작성하고 FastAPI와 PostgreSQL을 기동한다.

   ```sh
   docker compose --env-file deploy/backend/.env -f deploy/backend/compose.yml up -d --build
   ```

3. 프론트엔드 EC2에서 `BACKEND_UPSTREAM`을 백엔드 EC2의 `프라이빗 IP:8000`으로 지정한다. 환경설정을 작성하고 nginx를 기동한다.

   ```sh
   docker compose --env-file deploy/frontend/.env -f deploy/frontend/compose.yml up -d --build
   ```

4. nginx를 경유한 `/health`, 사용자 화면, `/admin/`을 확인한다. 서비스 DB 로그인과 벡터 DB EC2의 pgvector 연산은 각각 SQL로 검증한다.

이번 배포에서 통계 조회는 CSV와 Parquet를 사용한다. PostgreSQL 데이터 적재 및 조회 연동은 T1에서 진행한다.