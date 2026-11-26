// 백엔드 호출 모음입니다. POST /chat 은 호출마다 유료 HCX 를 사용할 수 있습니다.
import { getJson, postJson } from './client';
import type { ChatRequest, ChatResponse, JudgeResult, SelectionItem } from './types';

export type ChatInput = {
  question: string;
  /** 서버(Redis)에 진행 상태를 두는 세션 id. 질문 기록 id 를 그대로 씁니다. */
  sessionId?: string;
  previous?: ChatResponse;
  selections?: Record<string, string[]>;
  view_selections?: SelectionItem[];
};

export function sendChat(input: ChatInput, signal?: AbortSignal): Promise<ChatResponse> {
  const body: ChatRequest = {
    question: input.question,
    session_id: input.sessionId,
    previous: input.previous as ChatRequest['previous'],
    selections: input.selections,
    view_selections: input.view_selections,
    answer_mode: 'modules', // 차트 그림과 근거 표까지 받는 모드
    auto_select: false, // 표마다 값이 다르면 사용자에게 선택을 묻기
    draw: true,
    // 시점·지역·대상이 빠지면 가정으로 진행하지 않고 되묻기로 멈춤 (서버 기본값 soft)
    overrides: { clarify_mode: 'strict' },
  };
  return postJson<ChatResponse>('/chat', body, signal);
}

/** 규칙 기반 판정이라 HCX 를 호출하지 않습니다. */
export function judgeChat(response: ChatResponse): Promise<JudgeResult> {
  return postJson<JudgeResult>('/rag/judge/from-chat', response);
}

export type SessionState = {
  session_id: string;
  status: string;
  question?: string;
  response?: ChatResponse | null;
  error?: string | null;
};

/** 새로고침으로 응답을 놓쳤을 때 서버에 남은 결과를 다시 받습니다. HCX 를 다시 부르지 않습니다. */
export function getSession(id: string, signal?: AbortSignal): Promise<SessionState> {
  return getJson<SessionState>(`/sessions/${encodeURIComponent(id)}`, signal);
}
