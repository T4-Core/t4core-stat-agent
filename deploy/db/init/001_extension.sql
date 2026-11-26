-- 처음 데이터 폴더를 만들 때 한 번 (docker-entrypoint-initdb.d). 스키마·표는 backend 가 만든다 (backend/db/sql/vector)
CREATE EXTENSION IF NOT EXISTS vector;
