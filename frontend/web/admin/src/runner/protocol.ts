// 관리자 화면과 작은 사용자 화면(iframe)이 주고받는 메시지 모양입니다.
import type { ChatResponse } from '../../../src/api/types';

export type RunRound = { status: string; timings: Record<string, number> };

export type RunOutcome = {
  status: 'ok' | 'out_of_scope' | 'error';
  responses: ChatResponse[];
  labels?: string[];
  message?: string;
  rounds: RunRound[];
  activeMs: number;
};

export type LiveStatus = 'pending' | 'needs_clarification' | 'needs_selection';

export type ParentMessage =
  | { source: 'adm-parent'; type: 'start'; token: string; question: string }
  | { source: 'adm-parent'; type: 'reset' };

export type PreviewMessage =
  | { source: 'adm-preview'; type: 'ready' }
  | { source: 'adm-preview'; type: 'status'; token: string; status: LiveStatus }
  | { source: 'adm-preview'; type: 'finished'; token: string; outcome: RunOutcome }
  | { source: 'adm-preview'; type: 'cancelled'; token: string };
