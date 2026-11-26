// 자동 생성 파일입니다. 직접 수정하지 말고 npm run gen:api 로 다시 만드세요.
export interface paths {
    "/api/v1/ingest/prepare": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 준비 한 번에: 메타 프로필 → 표 색인 → CSV 값 사전 (백그라운드)
         * @description 처음 한 번 (또는 catalog/meta/raw 가 바뀌었을 때). 표 정규화(parquet)는 검색에서 고른 표만 그때 한다.
         */
        post: operations["prepare_api_v1_ingest_prepare_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/ingest/prepare/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 준비 진행 상태 */
        get: operations["prepare_status_api_v1_ingest_prepare_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/ingest/meta/profiles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 메타 프로필 검색 (요약)
         * @description 표 고르기 전에 사람이 범위를 눈으로 확인하는 용도. 점수·판단은 하지 않는다.
         */
        get: operations["list_profiles_api_v1_ingest_meta_profiles_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/ingest/meta/profiles/{tbl_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 메타 프로필 1개 (전체) */
        get: operations["get_meta_profile_api_v1_ingest_meta_profiles__tbl_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/ingest/normalize/{tbl_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 표 하나 정규화 (캐시 있으면 재사용)
         * @description 검색이 고른 표를 이 시점에 정규화한다. 큰 표(740MB)는 1분 이상 걸릴 수 있다.
         */
        post: operations["normalize_api_v1_ingest_normalize__tbl_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/ingest/normalize/{tbl_id}/profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 정규화 프로필 조회 (정규화하지 않음) */
        get: operations["get_norm_profile_api_v1_ingest_normalize__tbl_id__profile_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/ingest/dict/{name}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 표기 통일 사전 (쿼리·RAG 모듈 공유용)
         * @description region_dict(시도 표준명·별칭), period_rules(시점 코드), symbol_dict(부호 의미), dim_kinds(분류 종류 판정 규칙)
         */
        get: operations["get_dict_api_v1_ingest_dict__name__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/csv-index/build": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 원본 CSV 스캔 → 값 사전 (바뀐 표만 다시) */
        post: operations["build_api_v1_csv_index_build_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/csv-index/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 값 사전 요약 */
        get: operations["summary_api_v1_csv_index_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/csv-index/values": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 슬롯 값 목록 (표 수 순) */
        get: operations["values_api_v1_csv_index_values_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/csv-index/find": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 값 → 그 값이 있는 표·위치 */
        get: operations["find_api_v1_csv_index_find_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/csv-index/tables/{tbl_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 표 하나의 구조 (열·분류 값·항목·단위·기간·주석) */
        get: operations["table_api_v1_csv_index_tables__tbl_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/analyze": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 질문 → QueryAnalysis (HCX 1회)
         * @description - **ok**: `view_bundle` → `POST /api/v1/rag/views`
         *     - **needs_clarification**: `clarifications[].options[].value` 중 고른 값을 `POST /api/v1/rag/clarify` 의
         *       `selections` 에, 이 응답 전체를 `previous` 에 넣어 다시 보냄
         *     - **out_of_scope**: 통계 수치를 묻지 않는 질문 (검색하지 않음)
         *     - `trace`: 단계별 params·출력·초
         */
        post: operations["analyze_api_v1_rag_analyze_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/clarify": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 되묻기 응답 → QueryAnalysis (previous 가 있으면 HCX 없음) */
        post: operations["clarify_api_v1_rag_clarify_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/lexicon/lookup": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 표현 → 표준 값 (사전·CSV 근거) */
        post: operations["lexicon_lookup_api_v1_rag_lexicon_lookup_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/lexicon/learn": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 학습 사전에 표현 추가 */
        post: operations["lexicon_learn_api_v1_rag_lexicon_learn_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/lexicon/pending": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 승인 대기 표현 */
        get: operations["lexicon_pending_api_v1_rag_lexicon_pending_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/decompose": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 슬롯 → 서브쿼리 (HCX 없음) */
        post: operations["decompose_api_v1_rag_decompose_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 지금 설정 (configs/pipeline.yaml) */
        get: operations["settings_api_v1_rag_settings_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/hcx-check": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** HCX 설정·호출 확인 (1회 호출) */
        get: operations["hcx_check_api_v1_rag_hcx_check_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 자연어 (+ 슬롯) → 표 후보 (View 는 만들지 않음) */
        post: operations["search_api_v1_rag_search_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/views": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 단위별 View 묶음 + Point 충돌 판정
         * @description - 입력: `question` · `analysis` · `view_bundle` 중 하나
         *     - **ok**: `records` → `POST /api/v1/agent/answer`
         *     - **needs_selection**: 같은 교차점(시점·지역·성별·연령·지표·단위) 값이 표마다 다름 → `pending[].options` 에서 하나를 골라
         *       `POST /api/v1/rag/views/select` 에 `{selection_token, option_id}` (+ 이 응답을 `previous` 로)
         *     - **needs_clarification / out_of_scope**: 질의 분석 단계 결과 (검색 안 함)
         */
        post: operations["views_api_v1_rag_views_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/views/select": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 선택 반영 (토큰 + option_id)
         * @description `previous` 를 주면 그 응답의 Record 를 그대로 쓰고 전체 `records` 를 다시 묶어 `viewset` 으로 돌려줌.
         *     없으면 토큰 안의 좌표(표·슬롯)로 View 를 다시 만들어 고른 Record 만 돌려줌
         */
        post: operations["select_api_v1_rag_views_select_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/views/points": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Record → Point + 충돌 판정 (검색 없음)
         * @description 이미 가진 View 카드끼리 비교만 해 볼 때. 순서 = 우선순위 (선택지 순서)
         */
        post: operations["points_api_v1_rag_views_points_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/judge": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * View ↔ 질문 조건 판정 (슬롯별 · View별 · 단위별 · 전체)
         * @description `POST /api/v1/rag/views` 응답을 **views** 에, analyze 응답의 **view_bundle** 을 **bundle** 에,
         *     **notes** 를 **upstream_notes** 에 넣는다.
         *
         *     결과의 `reasons` 로 오케스트레이터가 다음 행동을 고른다 (no_views · empty_view → 재검색,
         *     slot_dropped_upstream → 재작성 재시도, slot_substituted → 주의 문구 등).
         */
        post: operations["judge_views_api_v1_rag_judge_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/judge/config": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 기본 판정 기준 (JudgeConfig 기본값)
         * @description 이 값을 복사해서 POST /judge 의 `config` 에 고쳐 넣으면 기준을 바꿔 시험할 수 있다
         *     (예: pass_threshold 0.85, upstream_tier null).
         */
        get: operations["judge_config_api_v1_rag_judge_config_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/rag/judge/from-chat": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * POST /api/v1/chat 응답 통째 → 판정
         * @description bundle = analysis.view_bundle, views = views, upstream_notes = notes 로 조립한다.
         *     notes 중 정보 손실이 없는 메모는 판단 모듈이 무시한다.
         */
        post: operations["judge_from_chat_api_v1_rag_judge_from_chat_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/chat": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * ★ 질문 → 분석 → 검색·View → 답변
         * @description HCX 호출: 재작성 1회 + 임베딩(캐시 없을 때) + 답변 1회.
         *
         *     - **ok**: `result` 에 답변·차트·출처
         *     - **needs_clarification**: `analysis.clarifications` 에서 골라 `{previous: 이 응답, selections: {슬롯: [값]}}`
         *     - **needs_selection** (`auto_select=false`): `views.pending` 에서 골라 `{previous: 이 응답, view_selections: [...]}`
         *     - **out_of_scope**: 검색하지 않고 안내 답변
         *
         *     `answer_mode=modules` 이면 답변 대신 모듈 2→3→5→6 을 돌린다 (HCX: 모듈 2 0~1회 + 모듈 3 1회 + 모듈 6 1~2회).
         *     결과 전체는 `modules`, 답변 문장·출처·주의사항은 `result` 에도 같은 모양으로 들어간다.
         */
        post: operations["chat_api_v1_chat_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/answer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 질문 + Record 목록 → 답변 (HCX 1회)
         * @description `POST /api/v1/rag/views` 응답의 records 를 그대로 붙여 넣는다.
         *     notes 를 넣으면 조건을 못 맞춘 카드는 근거로 덜 쓰고 insufficient 판단에 반영
         */
        post: operations["agent_answer_api_v1_agent_answer_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agent/modules": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * ViewSet → 모듈 2→3→5→6 (차트 계획 → 계산 → 그림 → 답변 문장·근거 표)
         * @description `POST /api/v1/rag/views` 응답을 그대로 `views` 에 넣는다. 단계별로 보려면 /chart/decide → /chart/calc → /answer/compose.
         *
         *     - 충돌 선택이 끝난 카드(`views.records`)만 쓴다. `status` 가 ok 가 아니면 409
         *     - 역할 단위(분모·조건)는 따로 답할 질문이 아니라서 모듈 2·3 의 질문에서 빼고, 그 View 를 모든 세트에 붙인다
         */
        post: operations["agent_modules_api_v1_agent_modules_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/chart/decide": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * ② 모듈 2 — 질문 + View → 차트 계획 (charts · records 를 /calc 에 넣는다)
         * @description 모듈 2(`backend/agent/chart_decision`)를 실행하고, 결과를 모듈 3 입력(`ChartRequest`)으로 바꿔 돌려준다.
         *
         *     - 바꾸는 것(임시 어댑터): `fallback_charts` 목록 → `fallback_chart` 첫 값, `measure` None → raw, `'범위 밖'` → 차트 없음,
         *       하위 질문이 없을 때의 `sub_question_ids` `'main'` → `'{query_id}-1'`.
         *       바꾼 사실은 `reason` 에 남는다. 원래 값은 `chart_plan` 에 그대로 있다.
         *     - 모듈 2 의 `view_ids` 는 차트마다 그대로 전달된다 (세트 = 질문 · 차트 유형 · View). `records` 에 없는 View 가 있으면 `errors` 에 경고.
         *     - `chart_plan` 이 비어 있으면(`charts: []`) 이유는 `errors` 에 있다.
         */
        post: operations["chart_decide_api_v1_chart_decide_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/chart/calc": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 계산 계획 → 계산 → 차트 내용 구성·검증
         * @description `records` 에 `/api/v1/rag/views` 응답(Record 목록), `query_bundle` 에 query-rewrite 응답의 `view_bundle`,
         *     `charts` 에 모듈 2 의 차트 계획을 넣는다.
         *
         *     - `chart_contents` 에는 검증을 통과한 차트만 들어 있다. 빠진 차트의 사유는 `validation` 에 있다.
         *     - `calc_results` 는 차트와 관계없이 계산한다. 값과 `chart_contents.rows` 는 원래 정밀도이고, 표시는 `displays` 로 한다.
         *     - `chart_plan.notes` 에 HCX 가 고른 값 중 View 에 없는 것, 질문용 연산과 모듈 2 measure 의 차이 등이 남는다.
         */
        post: operations["chart_calc_api_v1_chart_calc_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/chart/calc/trace": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * /calc 와 같은 입력 → 단계별 중간 결과 (테스트 화면용)
         * @description `output` 은 `/calc` 응답과 같다. 그 밖에:
         *     `decide`(HCX 에 보낸 메시지 · 원 응답 · 버린 항목 · Decision), `charts`(차트별 원래 → 대체 시도의 내용과 검증),
         *     `calcs`(CalcResult + displays 를 적용한 표시값).
         *     화면: `http://localhost:8000/lab/chart-lab/`
         */
        post: operations["chart_calc_trace_api_v1_chart_calc_trace_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/chart/specs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 차트 15종 표 (필수 역할 · 행 구조 · 기본 requirements) */
        get: operations["chart_specs_api_v1_chart_specs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/answer/compose": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * 계산 결과 → 답변 문장 + 근거 표
         * @description `calc_results` · `displays` · `answer_steps` 는 `/api/v1/chart/calc` 응답에서
         *     (`answer_steps` 는 `chart_plan.answer_steps`), `records` · `query_bundle` 은 그 호출에 넣었던 것을 그대로 붙인다.
         *
         *     - `answer` 의 숫자는 HCX 가 쓴 것이 아니라 `calc_results` 값에서 채운 것이다 (`used_step_ids` = 인용한 계산).
         *     - `method`: `hcx`(첫 시도 통과) · `hcx_retry`(재시도 후 통과) · `template`(규칙 문장) · `none`(계산 결과 없음)
         *     - `tables`: 계산 요약 → 계산 목록 → 원본 View. `rows` 는 표시 문자열, `raw_rows` 는 원래 값. View 표의 `highlight_rows` 가 계산에 쓴 행이다.
         *     - `caveats`: View 가 못 맞춘 조건 · 계산하지 못한 이유. `notes` 에는 HCX 실패·재시도 사유가 남는다.
         */
        post: operations["answer_compose_api_v1_answer_compose_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/answer/compose/trace": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * /compose 와 같은 입력 → 시도별 중간 결과 (테스트 화면용)
         * @description `output` 은 `/compose` 응답과 같다. `attempts` 에 시도마다 HCX 에 보낸 메시지 · 원 응답 · 초안 · 채운 문장 · 걸린 문제가 있다.
         */
        post: operations["answer_compose_trace_api_v1_answer_compose_trace_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/data/source": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Record 또는 source 좌표 → 원본 parquet 재조회 + 차트 데이터
         * @description View 카드의 `source` (또는 카드 전체)를 넣으면 숫자를 parquet 에서 다시 꺼낸다 — 답변 숫자 검증용
         */
        post: operations["data_source_api_v1_data_source_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 상태 확인 */
        get: operations["health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/system/paths": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 데이터 경로 해석 결과 */
        get: operations["system_paths_api_v1_system_paths_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/system/pipelines": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 사용 가능한 파이프라인 (기본 + 개인 폴더 플러그인) */
        get: operations["system_pipelines_api_v1_system_pipelines_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AgeRange */
        AgeRange: {
            /**
             * From
             * @description 시작 나이 (포함)
             */
            from?: number | null;
            /**
             * To
             * @description 끝 나이 (포함). 없으면 상한 없음 (예: 65세 이상)
             */
            to?: number | null;
        };
        /**
         * AnalysisState
         * @description 되묻기 응답 때 previous.state 로 돌려보내면 HCX 를 다시 부르지 않음
         */
        AnalysisState: {
            /** Bundle */
            bundle: {
                [key: string]: unknown;
            };
            /** Raw Slots */
            raw_slots: {
                [key: string]: string[];
            };
            /**
             * Sub Slots
             * @default []
             */
            sub_slots?: {
                [key: string]: string[];
            }[];
            /**
             * Intents
             * @default []
             */
            intents?: string[];
            /**
             * Sub Intents
             * @default []
             */
            sub_intents?: (string | null)[];
            /**
             * Hcx Ok
             * @default true
             */
            hcx_ok?: boolean;
            /**
             * Hcx Error
             * @default
             */
            hcx_error?: string;
            /**
             * Thresholds
             * @description 숫자 기준 조건 [{말, 값, 단위, 비교, op, 표기, 지역_고르기}] ('가구원수가 99,000명 이상' — query_analyzer/roles.find_thresholds)
             */
            thresholds?: {
                [key: string]: unknown;
            }[];
        };
        /** AnalyzeRequest */
        AnalyzeRequest: {
            /**
             * Question
             * @example 2025년 대전 출생아 수와 사망자 수 차이
             */
            question: string;
            /**
             * Today
             * @description YYYY-MM-DD ('작년'·'최근 N년' 기준). 비우면 오늘
             */
            today?: string | null;
            /** Query Id */
            query_id?: string | null;
            /**
             * Overrides
             * @description configs/pipeline.yaml 값 일부 바꾸기 (예: {"base_year": 2025, "search_text_mode": "llm"})
             */
            overrides?: {
                [key: string]: unknown;
            } | null;
        };
        /** AnswerAttempt */
        AnswerAttempt: {
            /**
             * Messages
             * @description HCX 에 보낸 메시지
             */
            messages?: {
                [key: string]: string;
            }[];
            /**
             * Raw
             * @description HCX 원 응답
             */
            raw?: unknown;
            /**
             * Draft
             * @description 자리표시자가 든 초안
             */
            draft?: string | null;
            /**
             * Filled
             * @description 자리표시자를 채운 문장
             */
            filled?: string | null;
            /**
             * Problems
             * @description 검사에서 걸린 문제 (비어 있으면 통과)
             */
            problems?: string[];
        };
        /** AnswerDecision */
        AnswerDecision: {
            /** Join On */
            join_on?: string[] | null;
            denominator?: components["schemas"]["Denominator"] | null;
            /** From */
            from?: string | null;
            /** To */
            to?: string | null;
            /** Base */
            base?: string | null;
            /** Agg */
            agg?: string | null;
            /** Top N */
            top_n?: number | null;
            /** Kind */
            kind?: string | null;
            /** Order */
            order?: string | null;
            /** Sub Question Id */
            sub_question_id?: string | null;
            /**
             * Op
             * @enum {string}
             */
            op: "raw" | "change" | "growth_rate" | "cagr" | "index" | "share" | "diff" | "ratio" | "rank" | "extreme" | "aggregate" | "combine";
            /** Operands */
            operands?: components["schemas"]["Pick"][];
        };
        /** AnswerRequest */
        AnswerRequest: {
            /** Question */
            question: string;
            /** Records */
            records: components["schemas"]["Record"][];
            /**
             * Notes
             * @description record id → 못 맞춘 조건
             */
            notes?: {
                [key: string]: string[];
            };
            /**
             * Titles
             * @description record id → 표 이름 (없으면 lexical_text 앞부분)
             */
            titles?: {
                [key: string]: string;
            };
            /**
             * Max Rows
             * @description Record 하나당 LLM 에 넣을 최대 행 수
             * @default 40
             */
            max_rows?: number;
        };
        /** AnswerResult */
        AnswerResult: {
            /** Answer */
            answer: string;
            /**
             * Summary
             * @default
             */
            summary?: string;
            /** Key Points */
            key_points?: string[];
            /**
             * Insufficient
             * @default false
             */
            insufficient?: boolean;
            /**
             * Unverified Numbers
             * @description 자료에서 확인되지 않은 숫자 (계산값일 수 있음)
             */
            unverified_numbers?: string[];
            /** Used Ids */
            used_ids?: string[];
            /** Chart Id */
            chart_id?: string | null;
            chart?: components["schemas"]["ChartData"] | null;
            /** Sources */
            sources?: string[];
            /**
             * Caveats
             * @description View 생성 때 못 맞춘 조건
             */
            caveats?: string[];
            /**
             * Calculations
             * @description 코드 계산 결과 (플러그인 파이프라인이 채움)
             */
            calculations?: {
                [key: string]: unknown;
            }[];
        };
        /**
         * AnswerTable
         * @description 근거 표 하나. 화면은 rows(표시 문자열)를 그대로 그리고, QA(모듈 7)는 raw_rows 로 다시 계산해 본다
         */
        AnswerTable: {
            /**
             * Table Id
             * @example t_calc
             * @example t_a3
             * @example t_view_1
             */
            table_id: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "calc_summary" | "calc_list" | "view";
            /** Title */
            title: string;
            /** Columns */
            columns: string[];
            /**
             * Rows
             * @description displays 를 적용한 표시 문자열
             */
            rows: (string | null)[][];
            /**
             * Raw Rows
             * @description rows 와 같은 모양의 원래 값 (원래 정밀도)
             */
            raw_rows: unknown[][];
            /** Record Ids */
            record_ids?: string[];
            /**
             * Step Ids
             * @description 이 표를 만든 CalcResult.step_id
             */
            step_ids?: string[];
            /**
             * Highlight Rows
             * @description rows 안의 행 번호 (0부터). view 표에서 계산에 쓴 행
             */
            highlight_rows?: number[];
            /**
             * Truncated
             * @default false
             */
            truncated?: boolean;
            /**
             * Total Rows
             * @description 행 제한 전의 행 수
             */
            total_rows: number;
        };
        /** AxisSpec */
        AxisSpec: {
            /** Label */
            label?: string | null;
            /** Type */
            type?: ("time" | "category" | "numeric" | "region") | null;
            /** Scale */
            scale?: ("linear" | "log" | "percent" | "index") | null;
            /** Min */
            min?: number | null;
            /** Max */
            max?: number | null;
            /** Display Ref */
            display_ref?: string | null;
        };
        /**
         * CalcInput
         * @description 계산에 쓴 원래 값 하나 (QA 가 다시 계산할 때 쓴다)
         */
        CalcInput: {
            /** Role */
            role: string;
            /** Record Id */
            record_id: string;
            /** Item */
            item?: string | null;
            /**
             * Key
             * @description 이 값을 특정하는 열 값 (예: {'시점': '2021'})
             */
            key?: {
                [key: string]: unknown;
            };
            /** Value */
            value?: number | null;
            /** Unit */
            unit?: string | null;
        };
        /**
         * CalcRequest
         * @description Module3Request + 선택 필드 decision. 이 API 에서만 쓰는 입력이라 schemas/ 가 아니라 여기에 둔다
         * @example {
         *       "charts": [
         *         {
         *           "chart_id": "c1",
         *           "chart_type": "line",
         *           "fallback_chart": "bar",
         *           "measure": "raw",
         *           "requirements": [
         *             "time_axis_required",
         *             "min_points_3"
         *           ],
         *           "sub_question_ids": [
         *             "27077dec-1"
         *           ],
         *           "view_ids": [
         *             "view::101_DT_1B8000G::Y::27077dec-1-1::trend"
         *           ]
         *         }
         *       ],
         *       "decision": {
         *         "answers": [
         *           {
         *             "from": "2021",
         *             "op": "growth_rate",
         *             "operands": [
         *               {
         *                 "item": "혼인건수(건)",
         *                 "record_id": "view::101_DT_1B8000G::Y::27077dec-1-1::trend",
         *                 "select": {
         *                   "행정구역별": [
         *                     "전국"
         *                   ]
         *                 }
         *               }
         *             ],
         *             "sub_question_id": "27077dec-1",
         *             "to": "2025"
         *           }
         *         ],
         *         "charts": [
         *           {
         *             "chart_id": "c1",
         *             "record_id": "view::101_DT_1B8000G::Y::27077dec-1-1::trend",
         *             "select": {
         *               "시점": [
         *                 "2021",
         *                 "2022",
         *                 "2023",
         *                 "2024",
         *                 "2025"
         *               ],
         *               "항목": [
         *                 "혼인건수(건)"
         *               ],
         *               "행정구역별": [
         *                 "전국"
         *               ]
         *             }
         *           }
         *         ]
         *       },
         *       "query_bundle": {
         *         "original": "최근 5년 혼인건수 추이와 증감률",
         *         "query_id": "27077dec",
         *         "sub_questions": [
         *           "2021~2025년 전국 혼인건수 추이"
         *         ]
         *       },
         *       "records": [
         *         {
         *           "id": "view::101_DT_1B8000G::Y::27077dec-1-1::trend",
         *           "lexical_text": "인구동태건수 및 동태율 추이",
         *           "metadata": {
         *             "prd_se": "Y",
         *             "unit": "건",
         *             "view_type": "trend"
         *           },
         *           "parent_id": "table::101_DT_1B8000G",
         *           "table": {
         *             "columns": [
         *               "시점",
         *               "행정구역별",
         *               "항목",
         *               "값"
         *             ],
         *             "rows": [
         *               [
         *                 "2021",
         *                 "전국",
         *                 "혼인건수(건)",
         *                 192507
         *               ],
         *               [
         *                 "2022",
         *                 "전국",
         *                 "혼인건수(건)",
         *                 191690
         *               ],
         *               [
         *                 "2023",
         *                 "전국",
         *                 "혼인건수(건)",
         *                 193657
         *               ],
         *               [
         *                 "2024",
         *                 "전국",
         *                 "혼인건수(건)",
         *                 222412
         *               ],
         *               [
         *                 "2025",
         *                 "전국",
         *                 "혼인건수(건)",
         *                 240326
         *               ]
         *             ]
         *           }
         *         }
         *       ]
         *     }
         */
        CalcRequest: {
            /**
             * Records
             * @description 모듈 1 이 고른 View 들. 계산 근거는 Record.table.rows
             */
            records: components["schemas"]["Record"][];
            query_bundle: components["schemas"]["QueryBundle"];
            /** Charts */
            charts?: components["schemas"]["ChartRequest"][];
            /** Role Links */
            role_links?: components["schemas"]["RoleLink"][];
            /** @description HCX 가 정할 계획 결정을 직접 넣는다. 넣으면 HCX 를 부르지 않는다 (시험·재실행용). 비우면 HCX 가 정한다 */
            decision?: components["schemas"]["Decision"] | null;
        };
        /** CalcResult */
        CalcResult: {
            /** Step Id */
            step_id: string;
            /**
             * Sub Question Id
             * @description [NEW 11-20] 결과가 속한 하위 질문 ID (질문용 단계). 차트용 계산과 예전 입력은 None
             */
            sub_question_id?: string | null;
            /**
             * Op
             * @enum {string}
             */
            op: "raw" | "change" | "growth_rate" | "cagr" | "index" | "share" | "diff" | "ratio" | "rank" | "extreme" | "aggregate" | "combine";
            /**
             * Value
             * @description 원래 정밀도. 여러 값이면 list, 계산할 수 없으면 None
             */
            value?: number | unknown[] | null;
            /** Unit */
            unit?: string | null;
            /** Display Ref */
            display_ref?: string | null;
            /** Inputs */
            inputs?: components["schemas"]["CalcInput"][];
            /** Record Ids */
            record_ids?: string[];
            /** Scope Label */
            scope_label?: string | null;
            /**
             * Agg
             * @description aggregate 전용: sum(합계) / mean(평균). 그 밖의 연산은 null
             */
            agg?: ("sum" | "mean") | null;
            /**
             * Note
             * @description 계산하지 못한 이유 (기준값 0, 키 중복, truncated …)
             */
            note?: string | null;
        };
        /** CalcView */
        CalcView: {
            result: components["schemas"]["CalcResult"];
            /**
             * Display Text
             * @description displays 를 적용한 표시값 (format_value)
             */
            display_text?: string | (string | null)[] | null;
        };
        /** Candidate */
        Candidate: {
            /**
             * Rank
             * @description 최종 순위 (1부터)
             */
            rank: number;
            /** Tbl Id */
            tbl_id: string;
            /** Tbl Nm */
            tbl_nm: string;
            /** Survey Nm */
            survey_nm: string;
            /**
             * Score
             * @description 채널 점수 합 × 표 구조 계수
             */
            score: number;
            /**
             * Dense
             * @description 질문 ↔ 표 설명문 코사인 유사도
             */
            dense?: number | null;
            /** Bm25 Rank */
            bm25_rank?: number | null;
            /** Bm25 */
            bm25?: number | null;
            /**
             * Has View
             * @description View 카드를 만들었는지 (상위 n_views 개만)
             * @default false
             */
            has_view?: boolean;
            /**
             * Unmet
             * @description 표 메타데이터 기준으로 못 맞춘 조건
             */
            unmet?: components["schemas"]["Note"][] | null;
            /**
             * Cover
             * @description 요청 연도 중 표 기간 안에 든 비율 (0~1)
             */
            cover?: number | null;
            /** Cost */
            cost?: number | null;
        } & {
            [key: string]: unknown;
        };
        /** Caveat */
        Caveat: {
            /**
             * Source
             * @enum {string}
             */
            source: "view_note" | "calc_note" | "view_missing" | "plan_warning";
            /**
             * Ref
             * @description Record.id 또는 CalcResult.step_id
             */
            ref: string;
            /** Text */
            text: string;
        };
        /** ChartAttempt */
        ChartAttempt: {
            content: components["schemas"]["ChartContent"];
            check: components["schemas"]["CheckResult"];
        };
        /**
         * ChartContent
         * @description 최종 차트 하나. 대체되었으면 대체 차트의 내용이고, 대체도 실패한 차트는 만들지 않는다
         */
        ChartContent: {
            /** Chart Id */
            chart_id: string;
            /**
             * Chart Type
             * @description 최종 차트 유형
             * @enum {string}
             */
            chart_type: "line" | "bar" | "stacked_bar" | "pyramid" | "area" | "pie" | "donut" | "bubble" | "combo" | "radar" | "map" | "heatmap" | "treemap" | "scatter" | "dumbbell";
            /**
             * Measure
             * @enum {string}
             */
            measure: "raw" | "change" | "growth_rate" | "cagr" | "index" | "share" | "diff" | "ratio" | "rank" | "extreme" | "aggregate" | "combine";
            /** Title */
            title: string;
            /**
             * Encoding
             * @description {역할 코드: 열 이름}
             */
            encoding: {
                [key: string]: string;
            };
            /** Axis */
            axis?: {
                [key: string]: components["schemas"]["AxisSpec"];
            };
            /**
             * Options
             * @description marks · orientation · center_text · scope_label …
             */
            options?: {
                [key: string]: unknown;
            };
            /** Columns */
            columns: string[];
            /**
             * Rows
             * @description 값은 원래 정밀도. 표시 변환은 받는 쪽이 displays 로 한다
             */
            rows: unknown[][];
            /** Record Ids */
            record_ids?: string[];
            /** Warnings */
            warnings?: string[];
        };
        /** ChartData */
        ChartData: {
            /** Record Id */
            record_id: string;
            /**
             * Type
             * @description line | bar | table
             */
            type: string;
            /** Title */
            title: string;
            /** X */
            x?: string | null;
            /**
             * Y
             * @default 값
             */
            y?: string;
            /** Series */
            series?: string | null;
            /** Unit */
            unit?: string | null;
            /** Columns */
            columns: string[];
            /** Rows */
            rows: unknown[][];
        };
        /** ChartDecision */
        ChartDecision: {
            /** Join On */
            join_on?: string[] | null;
            denominator?: components["schemas"]["Denominator"] | null;
            /** From */
            from?: string | null;
            /** To */
            to?: string | null;
            /** Base */
            base?: string | null;
            /** Agg */
            agg?: string | null;
            /** Top N */
            top_n?: number | null;
            /** Kind */
            kind?: string | null;
            /** Order */
            order?: string | null;
            /** Chart Id */
            chart_id: string;
            /**
             * Title
             * @description 질문의 말로 쓴 차트 제목 (검사를 통과하면 Plan.title)
             */
            title?: string | null;
            /**
             * Record Id
             * @description 기본 View. operands 가 있으면 비워도 된다 (첫 피연산자의 View)
             */
            record_id?: string | null;
            /** Select */
            select?: {
                [key: string]: unknown[];
            };
            /**
             * Operands
             * @description 갈래가 여럿(combo·scatter·bubble)이거나 View 가 여럿(diff·ratio)일 때만 적는다
             */
            operands?: components["schemas"]["Pick"][];
        };
        /** ChartPlan */
        ChartPlan: {
            /** Plans */
            plans?: components["schemas"]["Plan"][];
            /**
             * Answer Steps
             * @description 질문용 계산. 차트가 없어도 만든다
             */
            answer_steps?: components["schemas"]["Step"][];
            /**
             * Answer Reuse
             * @description 질문용 단계 ID → 같은 계산인 차트 단계('{chart_id}.{step_id}'). 비어 있으면 모두 따로 계산
             */
            answer_reuse?: {
                [key: string]: string;
            };
            /** Notes */
            notes?: string[];
            /**
             * Warnings
             * @description 사용자에게 알려야 하는 사유 (계산 보류 등). 모듈 6 의 plan_warnings 로 넘긴다
             */
            warnings?: string[];
            /**
             * Withheld
             * @description [NEW 11-20] warnings 의 보류 사유에 범위(하위 질문·차트)를 붙인 것
             */
            withheld?: components["schemas"]["Withheld"][];
        };
        /**
         * ChartRequest
         * @description 모듈 2 의 차트 계획 하나 (charts[] 의 원소)
         *
         *     TODO(임시): 모듈 2 출력 스키마가 저장소에 없어 명세 2장의 필드 목록으로 임시 정의했다.
         *                 모듈 2 담당자 확인 후 필드 이름·타입을 맞춘다.
         */
        ChartRequest: {
            /**
             * Chart Id
             * @example c1
             */
            chart_id: string;
            /** Sub Question Ids */
            sub_question_ids?: string[];
            /**
             * Chart Type
             * @description None = 모듈 2 가 차트 없음으로 판단 (plans 를 만들지 않는다)
             */
            chart_type?: ("line" | "bar" | "stacked_bar" | "pyramid" | "area" | "pie" | "donut" | "bubble" | "combo" | "radar" | "map" | "heatmap" | "treemap" | "scatter" | "dumbbell") | null;
            /**
             * Measure
             * @default raw
             * @enum {string}
             */
            measure?: "raw" | "change" | "growth_rate" | "cagr" | "index" | "share" | "diff" | "ratio" | "rank" | "extreme" | "aggregate" | "combine";
            /**
             * Requirements
             * @description 검증 코드 (예: time_axis_required, min_points_3)
             */
            requirements?: string[];
            /** Fallback Chart */
            fallback_chart?: ("line" | "bar" | "stacked_bar" | "pyramid" | "area" | "pie" | "donut" | "bubble" | "combo" | "radar" | "map" | "heatmap" | "treemap" | "scatter" | "dumbbell") | null;
            /** Reason */
            reason?: string | null;
            /**
             * View Ids
             * @description 이 차트가 쓸 View 의 Record.id (모듈 2 의 view_ids). 일반 차트는 1개, combo 는 여러 개일 수 있다 (개수 제한 없음). chart_type 이 null 이어도 그 하위 질문의 질문용 계산이 쓸 View 를 담는다. 비어 있으면 records 전체가 후보
             */
            view_ids?: string[];
            /** @description 질문에서 지정한 차트 요청 (모듈 2 가 해석). 최종 안내가 쓴다 */
            request?: components["schemas"]["ChartRequestInfo"] | null;
            /**
             * M2 Warnings
             * @description 모듈 2 의 사용자용 경고 (진단용). ChartPlan.warnings · plan_warnings 에 합치지 않는다 — 확정 전 문장이 답변에 남는다
             */
            m2_warnings?: string[];
        };
        /** ChartRequestInfo */
        ChartRequestInfo: {
            /**
             * Preferred
             * @description 요청한 차트 (앞 이름이 우선)
             */
            preferred?: components["schemas"]["RequestedName"][];
            /**
             * Excluded
             * @description 사용자가 거부한 차트 ('막대 말고' 의 막대)
             */
            excluded?: components["schemas"]["RequestedName"][];
            /**
             * Scope
             * @description 적용되는 chart_id 목록
             * @default all
             */
            scope?: string[] | "all";
            stage?: components["schemas"]["RequestStage"];
        };
        /** ChartTrace */
        ChartTrace: {
            plan: components["schemas"]["Plan"];
            /**
             * Requirements
             * @description 원래 차트를 검증한 조건 (모듈 2 가 넘긴 것 + 차트 기본 조건)
             */
            requirements: string[];
            /**
             * Attempts
             * @description 원래 차트 → 대체 차트 순서. 실패한 시도도 담긴다
             */
            attempts?: components["schemas"]["ChartAttempt"][];
            validation: components["schemas"]["ChartValidation"];
        };
        /** ChartValidation */
        ChartValidation: {
            original: components["schemas"]["CheckResult"];
            /** @description 대체 차트를 시도하지 않았으면 None */
            fallback?: components["schemas"]["CheckResult"] | null;
            /** Final Chart Type */
            final_chart_type?: ("line" | "bar" | "stacked_bar" | "pyramid" | "area" | "pie" | "donut" | "bubble" | "combo" | "radar" | "map" | "heatmap" | "treemap" | "scatter" | "dumbbell") | null;
            /**
             * Content Built
             * @default false
             */
            content_built?: boolean;
        };
        /**
         * ChatJudgeRequest
         * @description /chat 응답을 그대로 붙여 넣고, 기준을 바꾸려면 judge_config 를 덧붙인다
         */
        ChatJudgeRequest: {
            /** Question */
            question: string;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "needs_clarification" | "needs_selection" | "out_of_scope";
            /** @description 질의 분석 결과 */
            analysis?: components["schemas"]["QueryAnalysis"] | null;
            /** @description 검색 단위별 View + 충돌 판정 */
            views?: components["schemas"]["ViewSet"] | null;
            /**
             * Records
             * @description 답변에 넘긴 카드
             */
            records?: components["schemas"]["Record"][];
            /** @description 답변 (status=ok · out_of_scope 일 때) */
            result?: components["schemas"]["AnswerResult"] | null;
            /** Notes */
            notes?: string[];
            /**
             * Timings
             * @description 단계별 소요 시간(초)
             */
            timings?: {
                [key: string]: number;
            };
            /**
             * Modules
             * @description answer_mode=modules 결과: charts · chart_errors · chart_plan(모듈 2) · module3 · drawn(모듈 5) · answer(모듈 6) · notes
             */
            modules?: {
                [key: string]: unknown;
            } | null;
            /** Saved */
            saved?: string | null;
            /**
             * Trace
             * @description 플러그인 파이프라인 단계 기록 (있으면)
             */
            trace?: {
                [key: string]: unknown;
            }[] | null;
            judge_config?: components["schemas"]["JudgeConfig"] | null;
        } & {
            [key: string]: unknown;
        };
        /**
         * ChatRequest
         * @example {
         *       "question": "작년 대구의 남자 20대 인구 수",
         *       "today": "2026-11-02"
         *     }
         * @example {
         *       "question": "2023년 충남 인구랑 시군구별 고령인구비율 순위",
         *       "today": "2026-11-02"
         *     }
         */
        ChatRequest: {
            /** Question */
            question: string;
            /**
             * Today
             * @description 상대 시점 기준일 YYYY-MM-DD (비우면 오늘)
             */
            today?: string | null;
            /**
             * Top K
             * @description 검색 단위마다 후보 표 수 (비우면 설정값)
             */
            top_k?: number | null;
            /**
             * N Views
             * @description 검색 단위마다 View 를 만들 표 수 (비우면 설정값)
             */
            n_views?: number | null;
            /**
             * Max Rows
             * @default 40
             */
            max_rows?: number;
            /**
             * Auto Select
             * @description 표마다 값이 다르면 검색 순위가 가장 높은 선택지로 바로 답변. false 면 status=needs_selection 으로 멈추고 views.pending 을 돌려줌
             * @default true
             */
            auto_select?: boolean;
            /**
             * Overrides
             * @description configs/pipeline.yaml 값 일부만 바꾸기
             */
            overrides?: {
                [key: string]: unknown;
            };
            /**
             * Previous
             * @description 이어서 할 때 직전 /chat 응답 그대로 (needs_clarification · needs_selection)
             */
            previous?: {
                [key: string]: unknown;
            } | null;
            /**
             * Selections
             * @description 되묻기 응답 (슬롯 → 값). previous 와 함께
             */
            selections?: {
                [key: string]: string[];
            } | null;
            /**
             * View Selections
             * @description 충돌 선택 (selection_token + option_id). previous 와 함께
             */
            view_selections?: components["schemas"]["SelectionItem"][] | null;
            /**
             * Save
             * @description true 면 ANSWERS_DIR 에 결과 JSON 저장
             * @default false
             */
            save?: boolean;
            /**
             * Session Id
             * @description 멀티턴 세션 id (REDIS_URL 이 있을 때). 주면 응답을 서버에 두어 GET /api/v1/sessions/{id} 로 다시 받을 수 있고, 이어서 할 때 previous 없이 selections · view_selections 만 보내도 된다 (previous 가 있으면 그것이 먼저)
             */
            session_id?: string | null;
            /**
             * Pipeline
             * @description default | 개인 폴더 파이프라인 이름 (GET /api/v1/system/pipelines)
             * @default default
             */
            pipeline?: string;
            /**
             * Answer Mode
             * @description default = 답변 HCX 1회 (agent/answer.py) · modules = 모듈 2→3→5→6 (차트 계획·계산·그림·답변 문장). modules 의 결과 전체는 응답 modules 에, 답변은 result 에도 같은 모양으로 넣는다
             * @default default
             * @enum {string}
             */
            answer_mode?: "default" | "modules";
            /**
             * Draw
             * @description answer_mode=modules 일 때 모듈 5 로 차트 그림(plotly JSON)도 만들지
             * @default true
             */
            draw?: boolean;
        };
        /** ChatResponse */
        ChatResponse: {
            /** Question */
            question: string;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "needs_clarification" | "needs_selection" | "out_of_scope";
            /** @description 질의 분석 결과 */
            analysis?: components["schemas"]["QueryAnalysis"] | null;
            /** @description 검색 단위별 View + 충돌 판정 */
            views?: components["schemas"]["ViewSet"] | null;
            /**
             * Records
             * @description 답변에 넘긴 카드
             */
            records?: components["schemas"]["Record"][];
            /** @description 답변 (status=ok · out_of_scope 일 때) */
            result?: components["schemas"]["AnswerResult"] | null;
            /** Notes */
            notes?: string[];
            /**
             * Timings
             * @description 단계별 소요 시간(초)
             */
            timings?: {
                [key: string]: number;
            };
            /**
             * Modules
             * @description answer_mode=modules 결과: charts · chart_errors · chart_plan(모듈 2) · module3 · drawn(모듈 5) · answer(모듈 6) · notes
             */
            modules?: {
                [key: string]: unknown;
            } | null;
            /** Saved */
            saved?: string | null;
            /**
             * Session Id
             * @description 요청의 session_id (세션 저장을 켰을 때)
             */
            session_id?: string | null;
            /**
             * Trace
             * @description 플러그인 파이프라인 단계 기록 (있으면)
             */
            trace?: {
                [key: string]: unknown;
            }[] | null;
        } & {
            [key: string]: unknown;
        };
        /** CheckResult */
        CheckResult: {
            /**
             * Chart Type
             * @enum {string}
             */
            chart_type: "line" | "bar" | "stacked_bar" | "pyramid" | "area" | "pie" | "donut" | "bubble" | "combo" | "radar" | "map" | "heatmap" | "treemap" | "scatter" | "dumbbell";
            /** Passed */
            passed: boolean;
            /** Checked */
            checked?: string[];
            /** Failed */
            failed?: string[];
            /** Reasons */
            reasons?: string[];
        };
        /** ChoiceOption */
        ChoiceOption: {
            /** Option Id */
            option_id: string;
            /**
             * Value
             * @description selections 에 그대로 넣을 값
             */
            value: string;
            /** Label */
            label: string;
            /**
             * N Tables
             * @default 0
             */
            n_tables?: number;
            /**
             * Example Tables
             * @default []
             */
            example_tables?: string[];
        };
        /** Clarification */
        Clarification: {
            /**
             * Slot
             * @enum {string}
             */
            slot: "시점" | "지역" | "대상";
            /** Reason */
            reason: string;
            /** Options */
            options: components["schemas"]["ChoiceOption"][];
            /**
             * Multi
             * @default true
             */
            multi?: boolean;
            /**
             * Answer Hint
             * @default
             */
            answer_hint?: string;
        };
        /** ClarifyRequest */
        ClarifyRequest: {
            /**
             * Question
             * @example 출생아 수 알려줘
             */
            question: string;
            /**
             * Selections
             * @description 되묻기 options[].value 중 고른 값 (슬롯 → 값 목록)
             * @example {
             *       "시점": [
             *         "2025년"
             *       ],
             *       "지역": [
             *         "대전광역시"
             *       ]
             *     }
             */
            selections: {
                [key: string]: string[];
            };
            /** @description 직전 /analyze 응답 (있으면 HCX 다시 안 부름) */
            previous?: components["schemas"]["QueryAnalysis"] | null;
            /** Today */
            today?: string | null;
            /** Query Id */
            query_id?: string | null;
            /** Overrides */
            overrides?: {
                [key: string]: unknown;
            } | null;
        };
        /**
         * ComposeRequest
         * @description Module6Request 와 같다. Swagger 예시를 붙이려고 이 API 에서만 한 번 감쌌다
         * @example {
         *       "answer_steps": [],
         *       "calc_results": [
         *         {
         *           "display_ref": "d1",
         *           "inputs": [
         *             {
         *               "item": "혼인건수(건)",
         *               "key": {
         *                 "시점": "2021"
         *               },
         *               "record_id": "view::101_DT_1B8000G::Y::27077dec-1-1::trend",
         *               "role": "value",
         *               "unit": "건",
         *               "value": 192507
         *             },
         *             {
         *               "item": "혼인건수(건)",
         *               "key": {
         *                 "시점": "2025"
         *               },
         *               "record_id": "view::101_DT_1B8000G::Y::27077dec-1-1::trend",
         *               "role": "value",
         *               "unit": "건",
         *               "value": 240326
         *             }
         *           ],
         *           "op": "growth_rate",
         *           "record_ids": [
         *             "view::101_DT_1B8000G::Y::27077dec-1-1::trend"
         *           ],
         *           "step_id": "a1",
         *           "unit": "%",
         *           "value": 24.84013568337775
         *         }
         *       ],
         *       "displays": {
         *         "d1": {
         *           "display_unit": "%",
         *           "source_unit": "%",
         *           "unit_scale": 1
         *         }
         *       },
         *       "query_bundle": {
         *         "original": "최근 5년 혼인건수 얼마나 변했어?",
         *         "query_id": "27077dec",
         *         "sub_questions": [
         *           "2021~2025년 전국 혼인건수 추이"
         *         ]
         *       },
         *       "records": [
         *         {
         *           "id": "view::101_DT_1B8000G::Y::27077dec-1-1::trend",
         *           "lexical_text": "인구동태건수 및 동태율 추이",
         *           "metadata": {
         *             "prd_se": "Y",
         *             "unit": "건",
         *             "view_type": "trend"
         *           },
         *           "parent_id": "table::101_DT_1B8000G",
         *           "table": {
         *             "columns": [
         *               "시점",
         *               "행정구역별",
         *               "항목",
         *               "값"
         *             ],
         *             "rows": [
         *               [
         *                 "2021",
         *                 "전국",
         *                 "혼인건수(건)",
         *                 192507
         *               ],
         *               [
         *                 "2022",
         *                 "전국",
         *                 "혼인건수(건)",
         *                 191690
         *               ],
         *               [
         *                 "2023",
         *                 "전국",
         *                 "혼인건수(건)",
         *                 193657
         *               ],
         *               [
         *                 "2024",
         *                 "전국",
         *                 "혼인건수(건)",
         *                 222412
         *               ],
         *               [
         *                 "2025",
         *                 "전국",
         *                 "혼인건수(건)",
         *                 240326
         *               ]
         *             ]
         *           }
         *         }
         *       ]
         *     }
         */
        ComposeRequest: {
            query_bundle: components["schemas"]["QueryBundle"];
            /**
             * Records
             * @description 모듈 3 에 넘겼던 View 들. 원본 View 표의 근거
             */
            records: components["schemas"]["Record"][];
            /**
             * Calc Results
             * @description 모듈 3 Module3Output.calc_results
             */
            calc_results?: components["schemas"]["CalcResult"][];
            /**
             * Displays
             * @description 모듈 3 Module3Output.displays
             */
            displays?: {
                [key: string]: components["schemas"]["Display"];
            };
            /**
             * Answer Steps
             * @description 모듈 3 Module3Output.chart_plan.answer_steps. 없어도 된다 — 있으면 극값 방향(kind)·집계 방식(agg)을 문장에 쓴다
             */
            answer_steps?: components["schemas"]["Step"][];
            /**
             * Plan Warnings
             * @description 모듈 3 Module3Output.chart_plan.warnings. 계산을 보류한 사유(질문의 지역 자료 없음, 분모 자료가 세트 밖 등)를 주의사항으로 전달한다
             */
            plan_warnings?: string[];
            /**
             * Withheld
             * @description 모듈 3 Module3Output.chart_plan.withheld. 보류한 하위 질문·차트 범위
             */
            withheld?: components["schemas"]["Withheld"][];
            /**
             * Role Links
             * @description split_roles 가 질문에서 뺀 역할 단위(분모·조건)와 그 View. 보조 결과를 가려낸다
             */
            role_links?: components["schemas"]["RoleLink"][];
            /**
             * Max Rows
             * @description 원본 View 표 하나의 최대 행 수. 계산에 쓴 행은 이 수와 관계없이 넣는다
             * @default 50
             */
            max_rows?: number;
        };
        /** Condition */
        Condition: {
            /**
             * Field
             * @description 분류 축 이름 (혼인상태, 가구원수). 원문에 없으면 None
             */
            field?: string | null;
            /**
             * Op
             * @default =
             * @enum {string}
             */
            op?: "=" | "!=" | ">" | ">=" | "<" | "<=";
            /**
             * Value
             * @description 미혼, 5, 99000 (숫자는 쉼표 없이)
             */
            value: string;
            /**
             * Unit
             * @description 명, 가구 (숫자 기준일 때)
             */
            unit?: string | null;
            /**
             * Text
             * @description 원문 표기 ('가구원수 99,000명 이상')
             */
            text: string;
            /**
             * Source
             * @default slot
             * @enum {string}
             */
            source?: "slot" | "threshold";
        };
        /** ConflictOption */
        ConflictOption: {
            /**
             * Option Id
             * @example opt-1
             */
            option_id: string;
            /**
             * Record Ids
             * @description 이 선택지의 View (값이 서로 같은 표들, 첫 번째가 대표)
             */
            record_ids: string[];
            /** Tbl Ids */
            tbl_ids: string[];
            /**
             * Tbl Nm
             * @default
             */
            tbl_nm?: string;
            /** Survey Nm */
            survey_nm?: string | null;
            /**
             * Value Preview
             * @description 다른 값이 나온 교차점: 이 선택지 값 + 다른 표 값
             */
            value_preview?: {
                [key: string]: unknown;
            }[];
            /**
             * Footnotes
             * @description 메타 주석 (통계표·항목·분류) {type, target, text}
             */
            footnotes?: {
                [key: string]: unknown;
            }[];
            /**
             * Description
             * @description 표 설명 (분류·항목·단위·기간·경로)
             * @default
             */
            description?: string;
            /**
             * Basis
             * @description 산출 기준: 조사·주기·기간·단위·항목·검색 순위·View 메모
             */
            basis?: {
                [key: string]: unknown;
            };
            /** Kosis Url */
            kosis_url?: string | null;
            /**
             * Same Value Tables
             * @default []
             */
            same_value_tables?: string[];
        };
        /** CsvIndexBuildRequest */
        CsvIndexBuildRequest: {
            /**
             * Scope
             * @description all = raw 폴더 전체 (조회 때 설정 csv_scope 로 거름) / selected
             * @default all
             * @enum {string}
             */
            scope?: "all" | "selected";
            /**
             * Limit
             * @description 앞에서부터 n개 표만 (빠른 확인)
             */
            limit?: number | null;
            /**
             * Force
             * @description 원본이 같아도 다시 스캔
             * @default false
             */
            force?: boolean;
            /**
             * Workers
             * @default 4
             */
            workers?: number;
        };
        /** CsvRow */
        CsvRow: {
            /** Tbl Id */
            tbl_id: string;
            /**
             * Kind
             * @description dim(분류 값) / item(항목) / obj(열 머리) / table(표 이름)
             */
            kind: string;
            /**
             * Slot
             * @description 지역 / 성별 / 연령 / 국적 / 분류 / 항목 / 열 / 표
             */
            slot: string;
            /**
             * Obj Nm
             * @default
             */
            obj_nm?: string;
            /** Name */
            name: string;
            /**
             * Code
             * @default
             */
            code?: string;
        };
        /** CsvValue */
        CsvValue: {
            /** Value */
            value: string;
            /** N Tables */
            n_tables: number;
            /**
             * Example Tables
             * @default []
             */
            example_tables?: string[];
        };
        /**
         * DecideRequest
         * @description 모듈 2 입력: 질문과, 그 질문으로 찾은 View. 모듈 2 가 하위 질문마다 차트 유형·measure 를 정한다
         */
        DecideRequest: {
            query_bundle: components["schemas"]["QueryBundle"];
            /** @description POST /api/v1/rag/views 응답(ViewSet) 그대로. 충돌 선택이 끝난 카드(records)만 쓴다 */
            view_input: components["schemas"]["ViewResult"];
            /**
             * Use Llm
             * @description False 면 모듈 2 가 HCX 를 부르지 않는다 (규칙으로 못 정한 measure 는 raw 로 대체된다)
             * @default true
             */
            use_llm?: boolean;
        };
        /** DecideResponse */
        DecideResponse: {
            /**
             * Charts
             * @description 어댑터를 거친 값. /calc 의 charts 에 그대로 넣는다
             */
            charts: components["schemas"]["ChartRequest"][];
            /**
             * Errors
             * @description 모듈 2 가 건너뛴 하위 질문(짝 없음 · 필터 0행 · 입력 문제) + query_id 불일치 경고
             */
            errors?: {
                [key: string]: unknown;
            }[];
            /**
             * Records
             * @description /calc 의 records 에 그대로 넣는다 (unit 마다 rank 1 View 하나씩. 세트의 view_ids 는 모두 여기 있다)
             */
            records?: components["schemas"]["Record"][];
            /**
             * Chart Plan
             * @description 모듈 2 원본 출력 (어댑터가 바꾸기 전). 차이를 눈으로 비교하는 용도
             */
            chart_plan?: {
                [key: string]: unknown;
            } | null;
        };
        /** DecideTrace */
        DecideTrace: {
            /**
             * Skipped
             * @description decision 을 직접 받아 HCX 를 부르지 않았다
             * @default false
             */
            skipped?: boolean;
            /**
             * Messages
             * @description HCX 에 보낸 system · user 메시지
             */
            messages?: {
                [key: string]: string;
            }[];
            /**
             * Raw
             * @description HCX 원 응답 (JSON 으로 읽은 것)
             */
            raw?: unknown;
            /**
             * Notes
             * @description 호출 실패 · 파싱하며 버린 항목
             */
            notes?: string[];
            decision: components["schemas"]["Decision"];
        };
        /** Decision */
        Decision: {
            /** Charts */
            charts?: components["schemas"]["ChartDecision"][];
            /** Answers */
            answers?: components["schemas"]["AnswerDecision"][];
        };
        /** DecomposeRequest */
        DecomposeRequest: {
            /**
             * Question
             * @example 2025년 대전 출생아 수와 사망자 수 차이
             */
            question: string;
            /**
             * Slots
             * @example {
             *       "시점": [
             *         "2025년"
             *       ],
             *       "지역": [
             *         "대전광역시"
             *       ],
             *       "지표": [
             *         "출생아수",
             *         "사망자수"
             *       ]
             *     }
             */
            slots: {
                [key: string]: string[];
            };
            /** Intents */
            intents?: string[];
            /** Overrides */
            overrides?: {
                [key: string]: unknown;
            } | null;
        };
        /** DecomposeResponse */
        DecomposeResponse: {
            /** Reason */
            reason: string;
            /** Sub Queries */
            sub_queries: components["schemas"]["SubQuery"][];
            /** Slots */
            slots: {
                [key: string]: components["schemas"]["SlotValue"][];
            };
        };
        /**
         * Denominator
         * @description share 의 분모 범위
         */
        Denominator: {
            /**
             * Scope
             * @enum {string}
             */
            scope: "question" | "selected";
            /**
             * Basis
             * @description 범위를 정한 근거 (예: 질문의 '전국 대비')
             */
            basis?: string | null;
            /** @description scope=question 일 때 총계를 가져올 곳 */
            operand?: components["schemas"]["Operand"] | null;
            /**
             * Label
             * @description 표시 문구. scope=selected 면 '선택 항목 내 비중'
             */
            label?: string | null;
        };
        /**
         * DictName
         * @enum {string}
         */
        DictName: "region_dict" | "period_rules" | "symbol_dict" | "dim_kinds";
        /** DifferingPoint */
        DifferingPoint: {
            /** Key */
            key: {
                [key: string]: unknown;
            };
            /** Key Str */
            key_str: string;
            /**
             * Values
             * @description 표마다 {record_id, tbl_id, value, unit, base_value, labels}
             */
            values: {
                [key: string]: unknown;
            }[];
        };
        /**
         * Display
         * @description 표시 방법: 원값 ÷ unit_scale → digits 자리로 한 번 반올림 → display_unit
         */
        Display: {
            /** Source Unit */
            source_unit: string;
            /** Display Unit */
            display_unit: string;
            /**
             * Unit Scale
             * @default 1
             */
            unit_scale?: number;
            /**
             * Digits
             * @description 생략하면 단위별 기본값 (agent/chart_calculate/display.py)
             */
            digits?: number | null;
        };
        /**
         * DocType
         * @enum {string}
         */
        DocType: "table" | "view" | "item";
        /**
         * Filters
         * @description 슬롯 dict. 빈 슬롯은 None (View 생성 때 기본값 적용)
         */
        Filters: {
            /**
             * 시점
             * @description 연도 목록. None 이면 값 조회=최신 연도, 추이=전체 기간
             */
            "\uC2DC\uC810"?: number[] | null;
            /**
             * 지역
             * @description 지역 표준명. None 이면 전국
             */
            "\uC9C0\uC5ED"?: string[] | null;
            /**
             * 대상
             * @description 무엇에 대한 통계인가 (인구, 출생아, 가구 …)
             */
            "\uB300\uC0C1"?: string[] | null;
            /**
             * 성별
             * @description 남자 / 여자
             */
            "\uC131\uBCC4"?: string[] | null;
            /** @description 나이 범위 {from, to} */
            "\uC5F0\uB839"?: components["schemas"]["AgeRange"] | null;
            /**
             * 지표
             * @description 무엇을 셌는가 (인구수, 출생아수, 고령인구비율 …)
             */
            "\uC9C0\uD45C"?: string[] | null;
            /**
             * 비교축
             * @description 비교·순위의 기준 축 (시도, 시군구, 행정구역, 지역 …)
             */
            "\uBE44\uAD50\uCD95"?: string | null;
            /**
             * 조건
             * @description 분류 값으로 찾을 말 (보증부월세, 재판이혼 …)
             */
            "\uC870\uAC74"?: string[] | null;
            /**
             * 국적
             * @description 국적 분류 값 (베트남, 중국 …)
             */
            "\uAD6D\uC801"?: string[] | null;
            /**
             * 출생연도
             * @description 출생연도(코호트) 분류 값 — 시점과 다름 (1983년생 → [1983])
             */
            "\uCD9C\uC0DD\uC5F0\uB3C4"?: number[] | null;
            /**
             * 원문표현
             * @description 질문 원문에 있던 CSV 표현 중 다른 슬롯에 없는 것 (대상·지표로 못 고른 분류·항목을 고를 때만 씀)
             */
            "\uC6D0\uBB38\uD45C\uD604"?: string[] | null;
            /**
             * 조건식
             * @description [NEW 11-20] 이 단위의 결과를 **제한하는** 조건 (열·연산자·값·단위). 역할 단위(분모·조건)에는 넣지 않고 역할이 없는 본 질문에만 넣는다
             */
            "\uC870\uAC74\uC2DD"?: components["schemas"]["Condition"][] | null;
            /**
             * 역할
             * @description 검색 단위의 역할: 분모 / 조건 (query_analyzer/roles.py). 분모 단위는 같은 조사·수준의 단순한 인구·가구 표를 찾음
             */
            "\uC5ED\uD560"?: string | null;
            /**
             * 의도
             * @description View 종류를 정하는 의도: 값 조회 / 추이 / 비교 / 순위
             */
            "\uC758\uB3C4"?: string | null;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HcxCheckResponse */
        HcxCheckResponse: {
            /**
             * Settings
             * @description 현재 설정 (키 값은 넣지 않음)
             */
            settings: {
                [key: string]: unknown;
            };
            /**
             * Check
             * @description {ok, elapsed_s, response 또는 error}
             */
            check: {
                [key: string]: unknown;
            };
        };
        /**
         * JudgeConfig
         * @description 통과 기준. 팀에서 아직 정하는 중이라 전부 설정값으로 뺐다 (기본값 = 임시값).
         *     평가셋으로 여러 설정을 돌려 비교한 뒤 확정한다.
         */
        JudgeConfig: {
            /**
             * Slot Tiers
             * @description 슬롯 이름 → 중요도 등급. 여기에 없는 슬롯은 판정만 하고 점수에는 넣지 않음
             */
            slot_tiers?: {
                [key: string]: components["schemas"]["SlotTier"];
            };
            /**
             * Tier Weights
             * @description 등급 → 가중 치
             */
            tier_weights?: {
                [key: string]: number;
            };
            /**
             * Status Score
             * @description 슬롯 상태 → 점수 (0~1)
             */
            status_score?: {
                [key: string]: number;
            };
            /**
             * Core Missing Is Fail
             * @description core 슬롯이 하나라도 missing 이면 점수와 관계없이 그 View 는 fail
             * @default true
             */
            core_missing_is_fail?: boolean;
            /**
             * @description 대체값(최신 연도 사용 등)을 어떤 상태로 볼지. 엄격하게 하려면 missing
             * @default partial
             */
            substitution_as?: components["schemas"]["SlotStatus"];
            /**
             * Unit Aggregate
             * @description 단위(상위 질의·서브질문) 판정을 합치는 규칙. all = 모든 단위 통과해야 통과 / any = 하나만 통과해도 / mean = 점수 평균
             * @default all
             * @enum {string}
             */
            unit_aggregate?: "all" | "any" | "mean";
            /**
             * Pass Threshold
             * @description 이 점수 이상이면 pass
             * @default 0.8
             */
            pass_threshold?: number;
            /**
             * Partial Threshold
             * @description 이 점수 이상이면 partial, 미만이면 fail
             * @default 0.5
             */
            partial_threshold?: number;
            /**
             * @description 재작성·변환 단계에서 빠진 슬롯(국적·전출지 등, slot_tiers 에 없는 것)을 점수에 넣을 등급. None 이면 점수에는 넣지 않고 reason(slot_dropped_upstream)만 남김
             * @default minor
             */
            upstream_tier?: components["schemas"]["SlotTier"] | null;
        };
        /**
         * JudgeRequest
         * @example {
         *       "bundle": {
         *         "filters": {
         *           "대상": [
         *             "인구"
         *           ],
         *           "성별": [
         *             "남자"
         *           ],
         *           "시점": [
         *             2025
         *           ],
         *           "연령": {
         *             "from": 20,
         *             "to": 29
         *           },
         *           "의도": "값 조회",
         *           "지역": [
         *             "대구광역시"
         *           ],
         *           "지표": [
         *             "인구수"
         *           ]
         *         },
         *         "original": "작년 대구의 남자 20대 인구 수",
         *         "query_id": "1"
         *       },
         *       "upstream_notes": [
         *         "[국적] ['한국'] — View 모듈에 아직 없는 슬롯 (검색 문장에는 들어 있음)"
         *       ],
         *       "views": {
         *         "filters": {
         *           "대상": [
         *             "인구"
         *           ],
         *           "성별": [
         *             "남자"
         *           ],
         *           "시점": [
         *             2025
         *           ],
         *           "연령": {
         *             "from": 20,
         *             "to": 29
         *           },
         *           "의도": "값 조회",
         *           "지역": [
         *             "대구광역시"
         *           ],
         *           "지표": [
         *             "인구수"
         *           ]
         *         },
         *         "original": "작년 대구의 남자 20대 인구 수",
         *         "query_id": "1",
         *         "units": [
         *           {
         *             "candidates": [],
         *             "filters": {
         *               "대상": [
         *                 "인구"
         *               ],
         *               "성별": [
         *                 "남자"
         *               ],
         *               "시점": [
         *                 2025
         *               ],
         *               "연령": {
         *                 "from": 20,
         *                 "to": 29
         *               },
         *               "의도": "값 조회",
         *               "지역": [
         *                 "대구광역시"
         *               ],
         *               "지표": [
         *                 "인구수"
         *               ]
         *             },
         *             "notes": [],
         *             "query": "2025년 대구광역시 남자 20~29세 인구수",
         *             "unit_id": "main",
         *             "views": [
         *               {
         *                 "notes": [
         *                   "요청 시점이 모두 없어 최신 2024 사용"
         *                 ],
         *                 "rank": 1,
         *                 "record": {
         *                   "id": "view::101_DT_1B04005N::Y::1-1::value",
         *                   "lexical_text": "행정구역별 성별 인구 주민등록인구현황 대구광역시 남자 총인구 명",
         *                   "metadata": {
         *                     "prd_from": "2024",
         *                     "prd_se": "Y",
         *                     "prd_to": "2024",
         *                     "view_type": "value"
         *                   },
         *                   "parent_id": "table::101_DT_1B04005N",
         *                   "source": {
         *                     "prd_se": "Y",
         *                     "tbl_id": "DT_1B04005N"
         *                   },
         *                   "table": {
         *                     "columns": [
         *                       "시점",
         *                       "행정구역(시도)별",
         *                       "성별",
         *                       "항목",
         *                       "값"
         *                     ],
         *                     "rows": [
         *                       [
         *                         "2024",
         *                         "대구광역시",
         *                         "남자",
         *                         "총인구",
         *                         1170000
         *                       ]
         *                     ]
         *                   }
         *                 },
         *                 "tbl_id": "DT_1B04005N"
         *               }
         *             ]
         *           }
         *         ]
         *       }
         *     }
         */
        JudgeRequest: {
            /** @description view_bundle (POST /rag/analyze 응답의 view_bundle 그대로) */
            bundle: components["schemas"]["QueryBundle"];
            /** @description View 결과 (POST /api/v1/rag/views 응답 그대로). 단위별 슬롯(units[].filters)과 Record 를 짝지어 판정한다 */
            views: components["schemas"]["ViewResult"];
            /**
             * Upstream Notes
             * @description 재작성 → View 입력 변환(adapter) 중 버리거나 바꾼 조건 메모 (analyze 응답의 notes). '[국적] … View 모듈에 아직 없는 슬롯' 처럼 [슬롯] 태그가 붙어 있어 unsupported 판정에 쓴다
             */
            upstream_notes?: string[];
            /** @description 통과 기준. 비우면 JudgeConfig 기본값 */
            config?: components["schemas"]["JudgeConfig"] | null;
        };
        /**
         * JudgeResult
         * @description 판단 모듈 출력 → 오케스트레이터
         */
        JudgeResult: {
            /** Query Id */
            query_id: string;
            verdict: components["schemas"]["Verdict"];
            /** Score */
            score: number;
            /**
             * Reasons
             * @description 모든 단위의 사유를 중복 없이 모은 것
             */
            reasons?: components["schemas"]["ReasonCode"][];
            /** Units */
            units?: components["schemas"]["UnitJudge"][];
            /** @description 이 판정에 쓴 기준 (나중에 기준을 바꿔도 결과를 재현할 수 있게 기록) */
            config_used: components["schemas"]["JudgeConfig"];
        };
        /** LearnRequest */
        LearnRequest: {
            /**
             * Surface
             * @example 아기 수
             */
            surface: string;
            /**
             * Value
             * @example 출생아수
             */
            value: string;
            /**
             * Slot
             * @default 지표
             */
            slot?: string | null;
            /**
             * Approve
             * @description true 면 바로 사용(active), false 면 승인 대기(pending)
             * @default false
             */
            approve?: boolean;
        };
        /** LexiconHit */
        LexiconHit: {
            /** Surface */
            surface: string;
            /** Value */
            value: string;
            /** Slot */
            slot: string | null;
            /**
             * Source
             * @description learned / rule / csv / term>csv / contains / term
             */
            source: string;
            /** Score */
            score: number;
            /**
             * Match
             * @default
             */
            match?: string;
            /** Grounded */
            grounded: boolean;
            /** N Tables */
            n_tables: number;
            /**
             * Tables
             * @default []
             */
            tables?: string[];
            /**
             * Csv
             * @default []
             */
            csv?: components["schemas"]["CsvRow"][];
        };
        /** LexiconLookupRequest */
        LexiconLookupRequest: {
            /**
             * Text
             * @example 신생아 수
             */
            text: string;
            /**
             * Slot
             * @description 슬롯 이름 (지역·성별·연령·대상·지표·국적·조건·이동·비교축). 비우면 전체
             * @default 지표
             */
            slot?: string | null;
            /**
             * Overrides
             * @description 설정 일부 바꾸기 (예: {"csv_scope": "all"})
             */
            overrides?: {
                [key: string]: unknown;
            } | null;
        };
        /** LexiconLookupResponse */
        LexiconLookupResponse: {
            /** Hits */
            hits: components["schemas"]["LexiconHit"][];
            /**
             * Suggestions
             * @description 비슷한 CSV 이름 (접지 실패 시 되묻기 후보)
             */
            suggestions?: string[];
        };
        /** Match */
        Match: {
            /**
             * Rank
             * @description 검색 순위 (1부터)
             */
            rank: number;
            /**
             * Cover
             * @description 요청 연도 중 표 기간 안에 든 비율 (0~1, 연도를 안 물었으면 1)
             */
            cover?: number | null;
            /**
             * Unmet
             * @description 표 메타데이터 기준으로 못 맞춘 조건
             */
            unmet?: components["schemas"]["Note"][];
        };
        /** Module3Output */
        Module3Output: {
            /** Query Id */
            query_id?: string | null;
            chart_plan: components["schemas"]["ChartPlan"];
            /** Chart Contents */
            chart_contents?: components["schemas"]["ChartContent"][];
            /** Calc Results */
            calc_results?: components["schemas"]["CalcResult"][];
            /**
             * Displays
             * @description {display_ref: 설정}
             */
            displays?: {
                [key: string]: components["schemas"]["Display"];
            };
            /**
             * Validation
             * @description {chart_id: 검증 결과}
             */
            validation?: {
                [key: string]: components["schemas"]["ChartValidation"];
            };
        };
        /** Module3Trace */
        Module3Trace: {
            decide: components["schemas"]["DecideTrace"];
            chart_plan: components["schemas"]["ChartPlan"];
            /** Displays */
            displays: {
                [key: string]: components["schemas"]["Display"];
            };
            /** Charts */
            charts?: {
                [key: string]: components["schemas"]["ChartTrace"];
            };
            /** Calcs */
            calcs?: components["schemas"]["CalcView"][];
            output: components["schemas"]["Module3Output"];
        };
        /** Module6Output */
        Module6Output: {
            /** Query Id */
            query_id?: string | null;
            /** Answer */
            answer: string;
            /**
             * Insufficient
             * @description 계산 결과가 없거나 모두 계산하지 못해 수치 답변을 하지 못했다
             * @default false
             */
            insufficient?: boolean;
            /**
             * Method
             * @description hcx = 첫 시도 통과 / hcx_retry = 재시도 후 통과 / template = 규칙 문장 / none = 답변할 계산 없음
             * @enum {string}
             */
            method: "hcx" | "hcx_retry" | "template" | "none";
            /**
             * Tables
             * @description 계산 요약 → 계산 목록 → 원본 View 순서
             */
            tables?: components["schemas"]["AnswerTable"][];
            /** Caveats */
            caveats?: components["schemas"]["Caveat"][];
            /**
             * Used Step Ids
             * @description 답변 문장이 실제로 인용한 CalcResult.step_id
             */
            used_step_ids?: string[];
            /**
             * Notes
             * @description HCX 실패·재시도 사유 등 (QA 가 본다)
             */
            notes?: string[];
        };
        /** Module6Trace */
        Module6Trace: {
            /** Attempts */
            attempts?: components["schemas"]["AnswerAttempt"][];
            output: components["schemas"]["Module6Output"];
        };
        /**
         * ModulesRequest
         * @description POST /api/v1/rag/views 응답(ViewSet) → 모듈 2→3→5→6 한 번에
         */
        ModulesRequest: {
            /** @description POST /api/v1/rag/views 응답 그대로 (status=ok) */
            views: components["schemas"]["ViewSet"];
            /**
             * Use Llm Chart
             * @description False 면 모듈 2 가 HCX 를 부르지 않는다 (규칙으로 못 정한 measure 는 raw)
             * @default true
             */
            use_llm_chart?: boolean;
            /**
             * Draw
             * @description 모듈 5 로 차트 그림(plotly JSON)도 만들지
             * @default true
             */
            draw?: boolean;
            /**
             * Max Rows
             * @description 근거 표에 넣을 원본 View 최대 행 수
             * @default 50
             */
            max_rows?: number;
        };
        /** NormalizeResult */
        NormalizeResult: {
            /** Table Key */
            table_key: string;
            /** Tbl Nm */
            tbl_nm: string;
            /**
             * Cached
             * @description true 면 기존 정규화 결과를 재사용
             */
            cached: boolean;
            /** Seconds */
            seconds: number;
            /** Row Check */
            row_check: {
                [key: string]: number;
            };
            /**
             * Profile
             * @description 정규화 프로필 (full=false 면 코드 목록 생략)
             */
            profile: {
                [key: string]: unknown;
            };
        };
        /**
         * Note
         * @description 못 맞춘 조건 하나 (build.note() 와 같은 모양)
         */
        Note: {
            /**
             * Slot
             * @description 시점 · 지역 · 성별 · 연령 · 지표 · 시나리오 · 행수
             */
            slot: string | null;
            /**
             * Dim
             * @description 표의 어느 분류에서 생겼는지 (예: 시나리오별, 항목)
             */
            dim?: string | null;
            /**
             * Type
             * @description missing · default · partial · latest_shift · truncated · empty
             */
            type: string;
            /**
             * Requested
             * @description 요청한 값 (예: [2025], ['부산광역시'], {'from': 20, 'to': 29})
             */
            requested?: unknown;
            /**
             * Applied
             * @description 실제로 쓴 값 (예: [2024], ['전국'])
             */
            applied?: unknown;
            /**
             * Text
             * @description 사람이 읽는 문장
             */
            text: string;
        };
        /** Operand */
        Operand: {
            /**
             * Role
             * @description 연산별 역할 이름 (diff·ratio: a, b / growth_rate: value / share: part / combine: term). denominator.operand 에서는 생략한다
             */
            role?: string | null;
            /**
             * Sign
             * @description [NEW] combine 전용: 더할지(+) 뺄지(-). 생략하면 +
             */
            sign?: ("+" | "-") | null;
            /**
             * Unit Source
             * @description item: 항목 이름의 괄호 / table: View 의 단일 단위 / hcx: HCX 가 고름 (확인 안 됨)
             */
            unit_source?: ("item" | "table" | "hcx") | null;
            /** Record Id */
            record_id: string;
            /**
             * Item
             * @description 대상 항목 (예: 인구수(명))
             */
            item?: string | null;
            /** Select */
            select?: {
                [key: string]: unknown[];
            };
            /**
             * Unit
             * @description 원 단위 (항목 이름의 괄호 부분)
             */
            unit?: string | null;
            /**
             * Note
             * @description 항목을 View 의 이름으로 바꾼 사유. CalcResult.note · ChartContent.warnings 로 전달
             */
            note?: string | null;
        };
        /** PendingSelection */
        PendingSelection: {
            /** Unit Id */
            unit_id: string;
            /** Selection Token */
            selection_token: string;
            /** Options */
            options: components["schemas"]["ConflictOption"][];
        };
        /**
         * Pick
         * @description View 에서 값을 가져올 곳 하나
         */
        Pick: {
            /**
             * Role
             * @description 차트 갈래면 축 역할(y, y2, x, size, start, end), 계산 피연산자면 a·b·value·part. 비우면 순서로 정한다
             */
            role?: string | null;
            /** Record Id */
            record_id: string;
            /** Item */
            item?: string | null;
            /** Select */
            select?: {
                [key: string]: unknown[];
            };
            /**
             * Sign
             * @description combine 전용: + 더하기, - 빼기 (생략하면 +)
             */
            sign?: ("+" | "-") | null;
            /**
             * Unit
             * @description HCX 가 고른 단위. item 괄호 단위가 없을 때만 쓰고, View metadata.unit 안에 있어야 한다
             */
            unit?: string | null;
            /**
             * Note
             * @description [NEW 11-18] 코드가 항목을 바꾼 사유. Operand.note 로 이어져 답변의 주의사항이 된다 (HCX 응답에는 없다)
             */
            note?: string | null;
        };
        /**
         * Plan
         * @description 차트 하나의 계획
         */
        Plan: {
            /** Chart Id */
            chart_id: string;
            /** Sub Question Ids */
            sub_question_ids?: string[];
            /**
             * Record Id
             * @description 기본 계산 대상 View. 단계에 operands 가 있으면 그쪽이 우선
             */
            record_id: string;
            /**
             * Chart Type
             * @description 모듈 2 의 원래 차트
             * @enum {string}
             */
            chart_type: "line" | "bar" | "stacked_bar" | "pyramid" | "area" | "pie" | "donut" | "bubble" | "combo" | "radar" | "map" | "heatmap" | "treemap" | "scatter" | "dumbbell";
            /** Fallback Chart */
            fallback_chart?: ("line" | "bar" | "stacked_bar" | "pyramid" | "area" | "pie" | "donut" | "bubble" | "combo" | "radar" | "map" | "heatmap" | "treemap" | "scatter" | "dumbbell") | null;
            /**
             * Measure
             * @enum {string}
             */
            measure: "raw" | "change" | "growth_rate" | "cagr" | "index" | "share" | "diff" | "ratio" | "rank" | "extreme" | "aggregate" | "combine";
            /** Select */
            select?: {
                [key: string]: unknown[];
            };
            /** Steps */
            steps?: components["schemas"]["Step"][];
            /**
             * Output
             * @description 갈래가 하나면 생략 → 마지막 단계를 쓴다
             */
            output?: components["schemas"]["PlanOutput"][] | null;
            /**
             * Title
             * @description 차트 제목 (HCX 작성, planner 가 검사). 없으면 규칙 제목
             */
            title?: string | null;
        };
        /** PlanOutput */
        PlanOutput: {
            /** Step Id */
            step_id: string;
            /**
             * Role
             * @enum {string}
             */
            role: "x" | "y" | "y2" | "series" | "value" | "label" | "size" | "region" | "parent" | "group" | "start" | "end";
        };
        /** PointConflict */
        PointConflict: {
            /** Unit Id */
            unit_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "ambiguous" | "partial" | "empty";
            /**
             * Views
             * @default []
             */
            views?: components["schemas"]["ViewCheck"][];
            /**
             * N Compared Keys
             * @description 두 표 이상에 있는 교차점 수
             * @default 0
             */
            n_compared_keys?: number;
            /**
             * N Agree
             * @default 0
             */
            n_agree?: number;
            /**
             * Differing Points
             * @default []
             */
            differing_points?: components["schemas"]["DifferingPoint"][];
            /**
             * Clusters
             * @default []
             */
            clusters?: string[][];
            /**
             * Options
             * @default []
             */
            options?: components["schemas"]["ConflictOption"][];
            /**
             * Selection Token
             * @description 선택할 때 option_id 와 함께 보냄
             */
            selection_token?: string | null;
            /** Selected Option */
            selected_option?: string | null;
            /**
             * Notes
             * @default []
             */
            notes?: string[];
        } & {
            [key: string]: unknown;
        };
        /** PointsRequest */
        PointsRequest: {
            /**
             * Records
             * @description 비교할 View 카드
             */
            records: components["schemas"]["Record"][];
            /**
             * Filters
             * @description 질문 슬롯 (view_bundle.filters)
             */
            filters?: {
                [key: string]: unknown;
            } | null;
            /** Overrides */
            overrides?: {
                [key: string]: unknown;
            };
        };
        /** PointsResponse */
        PointsResponse: {
            /**
             * Points
             * @description record_id → Point 목록 {key, key_str, value, raw_value, unit, labels}
             */
            points: {
                [key: string]: {
                    [key: string]: unknown;
                }[];
            };
            /**
             * Point Notes
             * @default {}
             */
            point_notes?: {
                [key: string]: string[];
            };
            conflict: components["schemas"]["PointConflict"];
        };
        /** QueryAnalysis */
        QueryAnalysis: {
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "needs_clarification" | "out_of_scope";
            /** Question */
            question: string;
            /** Query Id */
            query_id?: string | null;
            /**
             * Bundle
             * @description 재작성 결과 {original, rewritten, intent, filters, sub_questions, sub_filters}
             */
            bundle: {
                [key: string]: unknown;
            };
            /** @description status=ok 일 때 검색·View 입력 */
            view_bundle?: components["schemas"]["QueryBundle"] | null;
            /**
             * Search Text
             * @default
             */
            search_text?: string;
            /**
             * Slots
             * @default {}
             */
            slots?: {
                [key: string]: components["schemas"]["SlotValue"][];
            };
            /**
             * Clarifications
             * @default []
             */
            clarifications?: components["schemas"]["Clarification"][];
            /**
             * Sub Queries
             * @default []
             */
            sub_queries?: components["schemas"]["SubQuery"][];
            /**
             * Decompose Reason
             * @default
             */
            decompose_reason?: string;
            /**
             * Applied Rules
             * @default []
             */
            applied_rules?: string[];
            /**
             * Notes
             * @default []
             */
            notes?: string[];
            state: components["schemas"]["AnalysisState"];
            /**
             * Trace
             * @default []
             */
            trace?: components["schemas"]["StepTraceModel"][];
        };
        /**
         * QueryBundle
         * @example {
         *       "filters": {
         *         "대상": [
         *           "인구"
         *         ],
         *         "비교축": "시군구",
         *         "시점": [
         *           2023
         *         ],
         *         "의도": "값 조회",
         *         "지역": [
         *           "충청남도"
         *         ],
         *         "지표": [
         *           "인구수",
         *           "고령인구비율"
         *         ]
         *       },
         *       "intent": "값 조회",
         *       "original": "2023년 충남 인구랑 시군구별 고령인구비율 순위",
         *       "query_id": "q1",
         *       "rewritten": "2023년 충청남도 인구수 고령인구비율 시군구별 순위",
         *       "search_text": "충청남도 인구수 고령인구비율",
         *       "sub_filters": [
         *         {
         *           "대상": [
         *             "인구"
         *           ],
         *           "시점": [
         *             2023
         *           ],
         *           "의도": "값 조회",
         *           "지역": [
         *             "충청남도"
         *           ],
         *           "지표": [
         *             "인구수"
         *           ]
         *         },
         *         {
         *           "비교축": "시군구",
         *           "시점": [
         *             2023
         *           ],
         *           "의도": "순위",
         *           "지역": [
         *             "충청남도"
         *           ],
         *           "지표": [
         *             "고령인구비율"
         *           ]
         *         }
         *       ],
         *       "sub_questions": [
         *         "2023년 충청남도 인구수",
         *         "2023년 충청남도 고령인구비율 시군구별 순위"
         *       ]
         *     }
         */
        QueryBundle: {
            /**
             * Query Id
             * @description 질의 ID (Record id 에 쓰임). 없으면 자동 생성
             */
            query_id?: string | null;
            /**
             * Original
             * @description 사용자 질문
             */
            original: string;
            /**
             * Rewritten
             * @description 재작성 문장 ('2025년 대구광역시 남자 20~29세 인구수')
             */
            rewritten?: string | null;
            /**
             * Intent
             * @description 질문 의도 (Intent 9종 중 하나. View 종류는 filters.의도)
             */
            intent?: string | null;
            /** @description 슬롯 dict — View 를 자를 조건 */
            filters?: components["schemas"]["Filters"] | null;
            /**
             * Sub Questions
             * @description 서브쿼리 자연어
             */
            sub_questions?: string[];
            /**
             * Sub Filters
             * @description 서브쿼리 슬롯 dict (sub_questions 와 같은 순서)
             */
            sub_filters?: components["schemas"]["Filters"][] | null;
            /**
             * Search Text
             * @description 본 질의 검색 문장. 비우면 original
             */
            search_text?: string | null;
        };
        /**
         * ReasonCode
         * @description 오케스트레이터가 '다음에 무엇을 할지' 고를 때 쓰는 사유 코드.
         *     평가 모듈은 사유만 알려 주고, 재검색·재작성 여부는 오케스트레이터가 정한다.
         * @enum {string}
         */
        ReasonCode: "no_views" | "empty_view" | "core_slot_missing" | "slot_substituted" | "slot_dropped_upstream" | "intent_mismatch";
        /**
         * Record
         * @description View 카드 하나
         */
        Record: {
            /**
             * Id
             * @description view::표key::주기::질문ID-순위::종류 (예: view::101_DT_1B040A3::Y::12-1::trend)
             */
            id: string;
            /**
             * Lexical Text
             * @description BM25 입력 (표 이름·조사명·조건·항목·단위)
             */
            lexical_text: string;
            /** @description 자른 표 (전체 행) */
            table: components["schemas"]["ViewTable"];
            /** @default view */
            doc_type?: components["schemas"]["DocType"];
            /**
             * Parent Id
             * @description View 를 만든 표 (table::표key)
             */
            parent_id: string;
            /**
             * Metadata
             * @description survey_nm, category, survey_type, view_type, prd_se, prd_from, prd_to, is_latest, unit, geo_level, n_points, items, dims
             */
            metadata?: {
                [key: string]: unknown;
            };
            /**
             * Source
             * @description 다시 조회하는 좌표: table_key, file, org_id, tbl_id, prd_se, itm_id, dims{c1:{codes}}, period, kosis_url
             */
            source?: {
                [key: string]: unknown;
            };
            /**
             * Notes
             * @description View 를 만들 때 못 맞춘 조건 (빈 목록 = 다 맞춤)
             */
            notes?: components["schemas"]["Note"][];
            /** @description 표를 고를 때의 결과 (검색 순위, 요청 연도 중 담은 비율, 못 맞춘 조건) */
            match?: components["schemas"]["Match"] | null;
        };
        /**
         * RecordJudge
         * @description View(Record) 하나의 판정
         */
        RecordJudge: {
            /** Record Id */
            record_id: string;
            /** Tbl Id */
            tbl_id: string;
            verdict: components["schemas"]["Verdict"];
            /**
             * Score
             * @description 요청된 슬롯의 status_score × tier_weight 가중 평균
             */
            score: number;
            /**
             * Slots
             * @description 슬롯 이름 → 판정
             */
            slots?: {
                [key: string]: components["schemas"]["SlotCheck"];
            };
            /** Reasons */
            reasons?: components["schemas"]["ReasonCode"][];
        };
        /**
         * RequestStage
         * @description 모듈 2 단계의 구조화된 중간 사유. 설명 문장(ChartRequest.reason)은 reason_node 가 덮어쓰므로 쓰지 않는다
         */
        RequestStage: {
            /** Reason */
            reason?: ("ambiguous_scope" | "unsupported_type" | "data_mismatch" | "view_blocked" | "no_candidate") | null;
            /**
             * Selected
             * @description 모듈 2 가 고른 차트 유형 (진단용. 최종 유형은 validation 이 정한다)
             */
            selected?: ("line" | "bar" | "stacked_bar" | "pyramid" | "area" | "pie" | "donut" | "bubble" | "combo" | "radar" | "map" | "heatmap" | "treemap" | "scatter" | "dumbbell") | null;
            /**
             * Applied
             * @description 요청이 선택에 반영되었는가 (ambiguous_scope 이면 False)
             * @default true
             */
            applied?: boolean;
        };
        /** RequestedName */
        RequestedName: {
            /**
             * Text
             * @description 요청 원문 표현 (예: 히스토그램, 원그래프)
             */
            text: string;
            /**
             * Code
             * @description 지원하는 차트 코드. 미지원 이름이면 None
             */
            code?: ("line" | "bar" | "stacked_bar" | "pyramid" | "area" | "pie" | "donut" | "bubble" | "combo" | "radar" | "map" | "heatmap" | "treemap" | "scatter" | "dumbbell") | null;
            /**
             * Supported
             * @default false
             */
            supported?: boolean;
        };
        /**
         * RoleLink
         * @description [NEW 11-20] 역할 단위(분모·조건)가 어느 본 질문을 지원하는가. split_roles 가 역할 단위를 질문에서 빼기 전에 남긴다
         *     (뺀 뒤에는 모듈 6 이 어느 결과가 보조 결과인지 알 방법이 없다)
         */
        RoleLink: {
            /**
             * Unit Id
             * @description 뺀 하위 질문 ID ('{query_id}-{순번}')
             */
            unit_id: string;
            /**
             * Role
             * @enum {string}
             */
            role: "분모" | "조건";
            /**
             * Term
             * @description 역할 단위의 말 (가구원수)
             * @default
             */
            term?: string;
            /**
             * Supports
             * @description 이 단위가 지원하는 본 하위 질문 ID. add_role_units 가 대상을 기록하지 않아 남은 본 질문 전부
             */
            supports?: string[];
            /**
             * Record Ids
             * @description 이 단위에서 세트에 붙인 View 의 Record.id
             */
            record_ids?: string[];
        };
        /** SearchRequest */
        SearchRequest: {
            /**
             * Query
             * @example 최근 5년간 대전의 인구 변화 추이
             */
            query: string;
            /**
             * Top K
             * @default 10
             */
            top_k?: number;
            /** @description 슬롯 (있으면 표 구조 계수에 반영) */
            filters?: components["schemas"]["Filters"] | null;
        };
        /** SearchResult */
        SearchResult: {
            /** Query */
            query: string;
            /** Candidates */
            candidates: components["schemas"]["Candidate"][];
        };
        /** SelectRequest */
        SelectRequest: {
            /** Selections */
            selections: components["schemas"]["SelectionItem"][];
            /**
             * Previous
             * @description POST /rag/views 응답 전체. 있으면 그 Record 를 그대로 쓰고 records 를 다시 묶음. 없으면 토큰의 좌표로 View 를 다시 만들어 선택한 것만 돌려줌
             */
            previous?: {
                [key: string]: unknown;
            } | null;
        };
        /** SelectResponse */
        SelectResponse: {
            viewset?: components["schemas"]["ViewSet"] | null;
            /** Records */
            records?: components["schemas"]["Record"][];
            /**
             * Applied
             * @default []
             */
            applied?: {
                [key: string]: unknown;
            }[];
        } & {
            [key: string]: unknown;
        };
        /** SelectionItem */
        SelectionItem: {
            /** Selection Token */
            selection_token: string;
            /**
             * Option Id
             * @example opt-1
             */
            option_id: string;
        };
        /**
         * SlotCheck
         * @description 슬롯 하나의 판정 + 근거. 오케스트레이터·답변 단계가 '무엇이 왜 틀렸는지' 를 그대로 보여줄 수 있게
         */
        SlotCheck: {
            status: components["schemas"]["SlotStatus"];
            /**
             * Requested
             * @description 요청값 (예: [2024], ['대구광역시'], {'from': 20, 'to': 29})
             */
            requested?: unknown;
            /**
             * Found
             * @description View 에 실제로 담긴 값 (예: ['2023'])
             */
            found?: unknown;
            /**
             * Evidence
             * @description 사람이 읽는 근거 (예: '요청 2024 → 표 최신 2023 사용')
             * @default
             */
            evidence?: string;
            /** @description 이 슬롯이 만든 사유 코드 (예: 대체 → slot_substituted, 의도 불일치 → intent_mismatch). status 만으로는 '대체' 와 '일부만 있음' 이 둘 다 partial 이라 구별되지 않아서 따로 둔다 */
            reason?: components["schemas"]["ReasonCode"] | null;
        };
        /**
         * SlotStatus
         * @description 슬롯 하나의 판정 결과
         * @enum {string}
         */
        SlotStatus: "match" | "partial" | "missing" | "unsupported" | "not_requested" | "unknown";
        /**
         * SlotTier
         * @description 슬롯의 중요도 등급 — 빠졌을 때 얼마나 치명적인가
         * @enum {string}
         */
        SlotTier: "core" | "minor" | "shape";
        /** SlotValue */
        SlotValue: {
            /** Raw */
            raw: string;
            /**
             * Value
             * @description 표준 값 (연도 int · 지역 표준명 · 연령 {from,to} · CSV 이름)
             */
            value: unknown;
            /** Source */
            source: string;
            /**
             * Match
             * @description CSV 일치 방식: exact(띄어쓰기만 다름) / variant(괄호·'수' 등 표기 변형) / contains
             * @default
             */
            match?: string;
            /**
             * Grounded
             * @description CSV 값 사전에 근거가 있는가
             */
            grounded: boolean;
            /** N Tables */
            n_tables: number;
            /**
             * Tables
             * @default []
             */
            tables?: string[];
            /**
             * Csv
             * @default []
             */
            csv?: components["schemas"]["CsvRow"][];
            /**
             * Candidates
             * @default []
             */
            candidates?: {
                [key: string]: unknown;
            }[];
            /**
             * Note
             * @default
             */
            note?: string;
        };
        /**
         * Step
         * @description Calculate 호출 하나. plans[].steps(차트용) 와 answer_steps(질문용) 가 같은 모양을 쓴다
         */
        Step: {
            /**
             * Step Id
             * @example s1
             * @example a1
             */
            step_id: string;
            /**
             * Op
             * @enum {string}
             */
            op: "raw" | "change" | "growth_rate" | "cagr" | "index" | "share" | "diff" | "ratio" | "rank" | "extreme" | "aggregate" | "combine";
            /**
             * Operands
             * @description plans[].steps 에서 생략하면 상위 record_id·select 를 피연산자 하나로 쓴다. answer_steps 에서는 항상 적는다
             */
            operands?: components["schemas"]["Operand"][] | null;
            /**
             * Join On
             * @description 여러 피연산자를 짝지을 열 (예: ['시점']). 피연산자가 둘 이상이면 필수
             */
            join_on?: string[] | null;
            /**
             * Input
             * @description 앞 단계의 step_id (그 결과를 입력으로 쓴다)
             */
            input?: string | null;
            /** @description share 전용 */
            denominator?: components["schemas"]["Denominator"] | null;
            /**
             * Display Ref
             * @description displays 의 키
             */
            display_ref?: string | null;
            /**
             * Sub Question Id
             * @description 질문용 단계가 속한 하위 질문 ID. 차트 단계와 예전 입력은 None
             */
            sub_question_id?: string | null;
            /**
             * From
             * @description 기간 시작 시점
             */
            from?: string | null;
            /**
             * To
             * @description 기간 끝 시점
             */
            to?: string | null;
            /**
             * Base
             * @description 기준 시점. 'prev' = 직전 시점
             */
            base?: string | null;
            /** Agg */
            agg?: ("sum" | "mean") | null;
            /** Top N */
            top_n?: number | null;
            /**
             * Kind
             * @description extreme 전용: 최댓값(max, 기본) / 최솟값(min)
             */
            kind?: ("max" | "min") | null;
            /**
             * Order
             * @description rank 전용: 큰 값부터(desc, 기본) / 작은 값부터(asc)
             */
            order?: ("desc" | "asc") | null;
        } & {
            [key: string]: unknown;
        };
        /** StepTraceModel */
        StepTraceModel: {
            /** Step */
            step: string;
            /**
             * Params
             * @default {}
             */
            params?: {
                [key: string]: unknown;
            };
            /** Output */
            output?: unknown;
            /**
             * Notes
             * @default []
             */
            notes?: string[];
            /**
             * Seconds
             * @default 0
             */
            seconds?: number;
            /** Error */
            error?: string | null;
        };
        /** SubQuery */
        SubQuery: {
            /** Id */
            id: string;
            /** Text */
            text: string;
            /** Slots */
            slots: {
                [key: string]: string[];
            };
            /** Intent */
            intent?: string | null;
            /** Reason */
            reason: string;
            /**
             * Candidate Tables
             * @default []
             */
            candidate_tables?: string[];
        };
        /**
         * UnitJudge
         * @description 검색 단위 하나 (상위 질의 'main' 또는 서브질문) 의 판정
         */
        UnitJudge: {
            /**
             * Unit Id
             * @description ViewResult.units[].unit_id 와 같음
             */
            unit_id: string;
            /** Query */
            query: string;
            verdict: components["schemas"]["Verdict"];
            /**
             * Score
             * @description 이 단위에서 가장 잘 맞는 View 의 점수 (View 하나로도 답할 수 있으므로)
             */
            score: number;
            /**
             * Best Record Id
             * @description 가장 잘 맞는 View. View 가 없으면 None
             */
            best_record_id?: string | null;
            /** Records */
            records?: components["schemas"]["RecordJudge"][];
            /** Reasons */
            reasons?: components["schemas"]["ReasonCode"][];
        };
        /** UnitResult */
        UnitResult: {
            /**
             * Unit Id
             * @description 'main' 또는 서브쿼리 ID
             */
            unit_id: string;
            /**
             * Query
             * @description 검색 단위 문장
             */
            query: string;
            filters?: components["schemas"]["Filters"] | null;
            /**
             * Candidates
             * @default []
             */
            candidates?: components["schemas"]["Candidate"][];
            /**
             * Views
             * @default []
             */
            views?: components["schemas"]["ViewItem"][];
            /**
             * Notes
             * @default []
             */
            notes?: string[];
        } & {
            [key: string]: unknown;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
        /**
         * Verdict
         * @description 최종 판정 3단계
         * @enum {string}
         */
        Verdict: "pass" | "partial" | "fail";
        /** ViewCheck */
        ViewCheck: {
            /** Record Id */
            record_id: string;
            /** Tbl Id */
            tbl_id: string;
            /** Rank */
            rank?: number | null;
            /**
             * Usable
             * @description 필수 메타를 모두 썼는가 (False 면 비교에서 빠짐)
             */
            usable: boolean;
            /**
             * Used
             * @default {}
             */
            used?: {
                [key: string]: boolean;
            };
            /**
             * Checks
             * @default {}
             */
            checks?: {
                [key: string]: {
                    [key: string]: unknown;
                };
            };
            /**
             * Notes
             * @default []
             */
            notes?: string[];
            /**
             * N Points
             * @default 0
             */
            n_points?: number;
        } & {
            [key: string]: unknown;
        };
        /** ViewItem */
        ViewItem: {
            record: components["schemas"]["Record"];
            /**
             * Notes
             * @description 표에 없어 못 맞춘 조건
             */
            notes?: string[];
            /** Rank */
            rank: number;
            /** Tbl Id */
            tbl_id: string;
        } & {
            [key: string]: unknown;
        };
        /** ViewResult */
        ViewResult: {
            /** Query Id */
            query_id: string;
            /** Original */
            original: string;
            filters?: components["schemas"]["Filters"] | null;
            /** Units */
            units: components["schemas"]["UnitResult"][];
        } & {
            [key: string]: unknown;
        };
        /** ViewSet */
        ViewSet: {
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "needs_selection" | "needs_clarification" | "out_of_scope";
            /** Query Id */
            query_id?: string | null;
            /** Original */
            original?: string | null;
            /**
             * Units
             * @default []
             */
            units?: components["schemas"]["ViewUnit"][];
            /**
             * Records
             * @description 답변으로 넘길 카드
             */
            records?: components["schemas"]["Record"][];
            /**
             * Pending
             * @default []
             */
            pending?: components["schemas"]["PendingSelection"][];
            /** Analysis Status */
            analysis_status?: string | null;
            /**
             * Clarifications
             * @default []
             */
            clarifications?: {
                [key: string]: unknown;
            }[];
            /**
             * Notes
             * @default []
             */
            notes?: string[];
            /** Seconds */
            seconds?: number | null;
            /** View Bundle */
            view_bundle?: {
                [key: string]: unknown;
            } | null;
        } & {
            [key: string]: unknown;
        };
        /** ViewTable */
        ViewTable: {
            /**
             * Columns
             * @example [
             *       "시점",
             *       "행정구역(시군구)별",
             *       "항목",
             *       "값"
             *     ]
             */
            columns: string[];
            /**
             * Rows
             * @example [
             *       [
             *         "2025",
             *         "서울특별시",
             *         "총인구수",
             *         9299548
             *       ]
             *     ]
             */
            rows: unknown[][];
        };
        /** ViewUnit */
        ViewUnit: {
            /**
             * Unit Id
             * @description 'main' 또는 서브쿼리 ID
             */
            unit_id: string;
            /**
             * Query
             * @description 검색 단위 문장
             */
            query: string;
            filters?: components["schemas"]["Filters"] | null;
            /**
             * Candidates
             * @default []
             */
            candidates?: components["schemas"]["Candidate"][];
            /**
             * Views
             * @default []
             */
            views?: components["schemas"]["ViewItem"][];
            /**
             * Notes
             * @default []
             */
            notes?: string[];
            /**
             * Search Query
             * @default
             */
            search_query?: string;
            conflict: components["schemas"]["PointConflict"];
            /** Selected */
            selected?: {
                [key: string]: unknown;
            } | null;
        } & {
            [key: string]: unknown;
        };
        /**
         * ViewsRequest
         * @description 셋 중 하나: question(분석부터) · analysis(/rag/analyze 응답) · view_bundle
         * @example {
         *       "view_bundle": {
         *         "filters": {
         *           "시점": [
         *             2025
         *           ],
         *           "의도": "값 조회",
         *           "지역": [
         *             "대전광역시"
         *           ],
         *           "지표": [
         *             "인구수"
         *           ]
         *         },
         *         "original": "2025년 대전 인구 수",
         *         "query_id": "demo",
         *         "search_text": "대전광역시 인구수"
         *       }
         *     }
         * @example {
         *       "question": "작년 대전 인구 수"
         *     }
         */
        ViewsRequest: {
            /**
             * Question
             * @description 질문 — 분석(HCX 1회)부터
             */
            question?: string | null;
            /** Today */
            today?: string | null;
            /**
             * Analysis
             * @description POST /api/v1/rag/analyze (또는 /clarify) 응답 그대로
             */
            analysis?: {
                [key: string]: unknown;
            } | null;
            view_bundle?: components["schemas"]["QueryBundle"] | null;
            /** Top K */
            top_k?: number | null;
            /**
             * N Views
             * @description 단위마다 View 를 만들어 비교할 표 수
             */
            n_views?: number | null;
            /**
             * Overrides
             * @description configs/pipeline.yaml 값 일부만 바꾸기
             */
            overrides?: {
                [key: string]: unknown;
            };
            /**
             * Auto Select
             * @description first = 충돌이 있으면 검색 순위가 가장 높은 선택지를 자동으로
             */
            auto_select?: "first" | null;
        };
        /**
         * Withheld
         * @description [NEW 11-20] 계산을 보류한 범위. warnings(문자열)는 어느 하위 질문의 것인지 알 수 없어 답변의 주의사항이 질문 전체에 붙었다 (M6-2)
         */
        Withheld: {
            /**
             * Sub Question Id
             * @description 보류된 질문용 계산의 하위 질문 ID
             */
            sub_question_id?: string | null;
            /**
             * Chart Id
             * @description 보류된 차트 계획 ID
             */
            chart_id?: string | null;
            /**
             * Op
             * @description 보류된 연산
             */
            op?: string | null;
            /**
             * Text
             * @description 사용자에게 보여 줄 사유 (warnings 와 같은 문장)
             */
            text: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    prepare_api_v1_ingest_prepare_post: {
        parameters: {
            query?: {
                workers?: number;
                /** @description CSV 값 사전 전체 다시 스캔 */
                force?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    prepare_status_api_v1_ingest_prepare_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    list_profiles_api_v1_ingest_meta_profiles_get: {
        parameters: {
            query?: {
                /** @description 표 이름·조사명·항목명에 포함된 단어 */
                q?: string | null;
                /** @description 이 분류 종류가 있는 표만 (regions, sex, ages, scenario …) */
                kind?: string | null;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_meta_profile_api_v1_ingest_meta_profiles__tbl_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tbl_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    normalize_api_v1_ingest_normalize__tbl_id__post: {
        parameters: {
            query?: {
                /** @description 원본이 그대로여도 다시 정규화 */
                force?: boolean;
                /** @description true 면 프로필에 코드 목록까지 포함 */
                full?: boolean;
            };
            header?: never;
            path: {
                tbl_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NormalizeResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_norm_profile_api_v1_ingest_normalize__tbl_id__profile_get: {
        parameters: {
            query?: {
                /** @description true 면 코드 목록까지 */
                full?: boolean;
            };
            header?: never;
            path: {
                tbl_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_dict_api_v1_ingest_dict__name__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: components["schemas"]["DictName"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    build_api_v1_csv_index_build_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CsvIndexBuildRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    summary_api_v1_csv_index_summary_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    values_api_v1_csv_index_values_get: {
        parameters: {
            query?: {
                /** @description 지역 / 성별 / 연령 / 국적 / 분류 / 항목 / 열 / 표 */
                slot?: string;
                /** @description selected = catalog.csv selected 표만 (검색 대상과 같음) / all */
                scope?: string;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CsvValue"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    find_api_v1_csv_index_find_get: {
        parameters: {
            query: {
                text: string;
                slot?: string | null;
                /** @description selected = catalog.csv selected 표만 (검색 대상과 같음) / all */
                scope?: string;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CsvRow"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    table_api_v1_csv_index_tables__tbl_id__get: {
        parameters: {
            query?: {
                /** @description 분류마다 보여 줄 값 수 */
                max_values?: number;
            };
            header?: never;
            path: {
                tbl_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    analyze_api_v1_rag_analyze_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AnalyzeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QueryAnalysis"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    clarify_api_v1_rag_clarify_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ClarifyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QueryAnalysis"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    lexicon_lookup_api_v1_rag_lexicon_lookup_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LexiconLookupRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LexiconLookupResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    lexicon_learn_api_v1_rag_lexicon_learn_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LearnRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    lexicon_pending_api_v1_rag_lexicon_pending_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    decompose_api_v1_rag_decompose_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DecomposeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DecomposeResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    settings_api_v1_rag_settings_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    hcx_check_api_v1_rag_hcx_check_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HcxCheckResponse"];
                };
            };
        };
    };
    search_api_v1_rag_search_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SearchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SearchResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    views_api_v1_rag_views_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ViewsRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ViewSet"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    select_api_v1_rag_views_select_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SelectRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SelectResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    points_api_v1_rag_views_points_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PointsRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PointsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    judge_views_api_v1_rag_judge_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["JudgeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JudgeResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    judge_config_api_v1_rag_judge_config_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JudgeConfig"];
                };
            };
        };
    };
    judge_from_chat_api_v1_rag_judge_from_chat_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChatJudgeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JudgeResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    chat_api_v1_chat_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChatRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChatResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    agent_answer_api_v1_agent_answer_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AnswerRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AnswerResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    agent_modules_api_v1_agent_modules_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ModulesRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    chart_decide_api_v1_chart_decide_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DecideRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DecideResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    chart_calc_api_v1_chart_calc_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CalcRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Module3Output"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    chart_calc_trace_api_v1_chart_calc_trace_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CalcRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Module3Trace"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    chart_specs_api_v1_chart_specs_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    answer_compose_api_v1_answer_compose_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ComposeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Module6Output"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    answer_compose_trace_api_v1_answer_compose_trace_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ComposeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Module6Trace"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    data_source_api_v1_data_source_post: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": {
                    [key: string]: unknown;
                };
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    system_paths_api_v1_system_paths_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    system_pipelines_api_v1_system_pipelines_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
}
