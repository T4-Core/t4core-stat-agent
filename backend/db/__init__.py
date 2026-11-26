"""
AWS 배포용 저장소 연결 — PostgreSQL(통계값·대화 이력) · pgvector(임베딩) · Redis(멀티턴 세션)

  환경변수                 쓰는 곳                                   비우면
  STAT_BACKEND=postgres    통계값을 DATABASE_URL 의 kosis 스키마에서   parquet (지금과 같음)
  DATABASE_URL             backend-server 의 PostgreSQL                 -
  VECTOR_STORE=pgvector    임베딩 캐시·dense 문서 벡터를 VECTOR_DB_URL  file (sqlite·pickle, 지금과 같음)
  VECTOR_DB_URL            db-server 의 PostgreSQL + pgvector            -
  REDIS_URL                멀티턴 세션 (진행 중·선택 대기 응답)          세션 저장 안 함 (previous 로만 이어가기)
  CHAT_HISTORY=on          대화 이력을 DATABASE_URL 의 app 스키마에      off

CLI: python -m backend.db --help   (migrate · check · stats · vectors · bundle)
"""
