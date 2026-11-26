-- 백엔드 PostgreSQL (backend-server) · 서비스 기록
--
-- 대화 이력: POST /api/v1/chat 한 번 = chat_turn 한 행 (CHAT_HISTORY=on 일 때).
-- 진행 중인 질문·선택 상태(멀티턴 이어가기)는 Redis 에 두고(backend/db/sessions.py), 여기는 끝난 결과만 남긴다.

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.chat_session (
    session_id   text PRIMARY KEY,                  -- 프론트엔드 질문 id (RunRecord.id) 또는 서버가 만든 uuid
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    first_question text,
    n_turns      int NOT NULL DEFAULT 0,
    last_status  text
);

CREATE TABLE IF NOT EXISTS app.chat_turn (
    turn_id      bigserial PRIMARY KEY,
    session_id   text REFERENCES app.chat_session (session_id) ON DELETE CASCADE,
    turn_no      int NOT NULL DEFAULT 1,
    kind         text NOT NULL,                     -- ask | clarify | select (이어가기 종류)
    question     text NOT NULL,
    status       text,                              -- ok | needs_clarification | needs_selection | out_of_scope | error
    answer       text,
    tables       text[],                            -- 답변에 쓴 표 (tbl_id)
    request      jsonb,                             -- previous 를 뺀 요청 (selections · view_selections · overrides …)
    response     jsonb,                             -- 응답 전체 (CHAT_HISTORY_RESPONSE=summary 면 비움)
    timings      jsonb,
    error        text,
    elapsed_ms   int,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chat_turn_session ON app.chat_turn (session_id, turn_no);
CREATE INDEX IF NOT EXISTS chat_turn_created ON app.chat_turn (created_at DESC);
