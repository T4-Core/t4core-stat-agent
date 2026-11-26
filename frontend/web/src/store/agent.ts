// 질문 전송과 응답 처리를 맡습니다. 유료 호출이 중복으로 나가지 않도록 여기서만 백엔드를 부릅니다.
import { useEffect, useMemo, useState } from 'react';
import { toResultView, toTags, thumbOf } from '../api/adapters';
import { getSession, sendChat, type ChatInput } from '../api/chat';
import { ApiError, USE_MOCK } from '../api/client';
import type { ChatResponse, SelectionItem } from '../api/types';
import { getResultView } from '../data/examples';
import type { ResultView, RunRecord } from '../data/types';
import { completeRun, getRun, INTERRUPTED, listRuns, removeRun, updateRun } from './history';
import { loadPayload, peekPayload, savePayload, type RunPayload } from './payloads';

const MOCK_MS = 4400;
const inflight = new Map<string, AbortController>();

function requestText(run: RunRecord) {
  return run.requestQuestion ?? run.question;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : '알 수 없는 오류가 발생했어요.';
}

function statusPatch(response: ChatResponse): Partial<RunRecord> {
  return { tags: toTags(response), thumb: thumbOf(response), chartCount: 0, message: undefined };
}

async function applyResponse(id: string, payload: RunPayload) {
  if (!getRun(id)) return;
  await savePayload(id, payload);
  if (!getRun(id)) return;
  const response = payload.responses[0];
  const patch = statusPatch(response);
  switch (response.status) {
    case 'ok':
      updateRun(id, { ...patch, status: 'done' });
      break;
    case 'needs_selection':
    case 'needs_clarification':
      updateRun(id, { ...patch, status: response.status });
      break;
    default:
      updateRun(id, { ...patch, status: 'out_of_scope', message: response.result?.answer ?? '이 질문에는 답변하기 어려워요.' });
  }
}

async function send(id: string, work: (signal: AbortSignal) => Promise<RunPayload>) {
  const controller = new AbortController();
  inflight.set(id, controller);
  updateRun(id, { status: 'pending', sentAt: Date.now(), message: undefined });
  try {
    await applyResponse(id, await work(controller.signal));
  } catch (error) {
    if (!(error instanceof ApiError && error.aborted) && getRun(id)) {
      updateRun(id, { status: 'error', message: errorMessage(error) });
    }
  } finally {
    inflight.delete(id);
  }
}

/** 화면이 다시 그려져도 같은 질문은 한 번만 보냅니다. */
export function startRun(id: string) {
  const run = getRun(id);
  if (!run || run.status !== 'pending' || run.sentAt || inflight.has(id)) return;
  if (USE_MOCK) {
    const controller = new AbortController();
    inflight.set(id, controller);
    updateRun(id, { sentAt: Date.now() });
    window.setTimeout(() => {
      inflight.delete(id);
      if (controller.signal.aborted || !getRun(id)) return;
      if (run.needsSelection) updateRun(id, { status: 'needs_selection' });
      else completeRun(id);
    }, MOCK_MS);
    return;
  }
  void send(id, async (signal) => ({ responses: [await sendChat({ question: requestText(run), sessionId: id }, signal)] }));
}

/** 화면 대기만 멈춥니다. 이미 시작된 백엔드 작업과 HCX 비용은 취소되지 않습니다. */
export function stopRun(id: string) {
  inflight.get(id)?.abort();
  inflight.delete(id);
  removeRun(id);
}

export function continueRun(id: string, previous: ChatResponse, input: Pick<ChatInput, 'selections' | 'view_selections'>) {
  const run = getRun(id);
  if (!run || inflight.has(id)) return;
  void send(id, async (signal) => ({
    responses: [await sendChat({ question: requestText(run), sessionId: id, previous, ...input }, signal)],
  }));
}

/** 둘 다 비교: 백엔드는 표를 하나씩만 고를 수 있어 두 번 호출합니다. */
export function compareTables(id: string, previous: ChatResponse, picks: { selection: SelectionItem; label: string }[]) {
  const run = getRun(id);
  if (!run || inflight.has(id)) return;
  void send(id, async (signal) => {
    const responses: ChatResponse[] = [];
    const labels: string[] = [];
    for (const pick of picks) {
      try {
        const response = await sendChat({ question: requestText(run), sessionId: id, previous, view_selections: [pick.selection] }, signal);
        if (response.status === 'ok') {
          responses.push(response);
          labels.push(pick.label);
        }
      } catch (error) {
        if (responses.length === 0 || (error instanceof ApiError && error.aborted)) throw error;
      }
    }
    if (responses.length === 0) throw new ApiError('선택한 통계표로 답변을 만들지 못했어요.');
    return { responses, labels };
  });
  updateRun(id, { table: 'both' });
}

const RECOVER_POLL_MS = 5_000;
const RECOVER_MAX_POLLS = 40;
const RECOVER_WITHIN_MS = 24 * 60 * 60 * 1000;
let recovering = false;

/** 새로고침 전에 보낸 질문의 결과를 서버 세션(Redis)에서 다시 받습니다. 같은 질문을 다시 보내지 않습니다. */
export async function recoverInterrupted() {
  if (USE_MOCK || recovering) return;
  recovering = true;
  const targets = listRuns().filter((run) => (
    run.status === 'error' && run.message === INTERRUPTED && Date.now() - (run.sentAt ?? run.createdAt ?? 0) < RECOVER_WITHIN_MS
  ));
  await Promise.all(targets.map(async (run) => {
    for (let i = 0; i < RECOVER_MAX_POLLS; i += 1) {
      let state;
      try {
        state = await getSession(run.id);
      } catch {
        return; // 세션 없음(404)·저장 꺼짐 → 그대로 둡니다.
      }
      if (state.status === 'running') {
        await new Promise((resolve) => window.setTimeout(resolve, RECOVER_POLL_MS));
        continue;
      }
      if (state.response && getRun(run.id)) await applyResponse(run.id, { responses: [state.response] });
      return;
    }
  }));
  recovering = false;
}

export function usePayload(id: string | undefined) {
  const [loaded, setLoaded] = useState<{ id?: string; payload: RunPayload | null }>({ payload: null });
  const cached = id ? peekPayload(id) : undefined;

  useEffect(() => {
    if (!id || USE_MOCK || cached) return;
    let cancelled = false;
    void loadPayload(id).then((payload) => { if (!cancelled) setLoaded({ id, payload }); });
    return () => { cancelled = true; };
  }, [cached, id]);

  if (USE_MOCK) return { payload: null, loading: false };
  if (cached) return { payload: cached, loading: false };
  return loaded.id === id ? { payload: loaded.payload, loading: false } : { payload: null, loading: true };
}

/** 예시 모드는 예시 결과를, 실제 모드는 저장된 응답을 화면 데이터로 바꿉니다. */
export function useRunView(run: RunRecord | undefined): { view: ResultView | null; loading: boolean } {
  const { payload, loading } = usePayload(run?.id);
  const chartCount = run?.chartCount;
  const table = run?.table;
  const view = useMemo(() => {
    if (USE_MOCK) return chartCount !== undefined && table ? getResultView({ chartCount, table }) : null;
    return payload ? toResultView(payload.responses, payload.labels) : null;
  }, [chartCount, payload, table]);
  return { view, loading };
}
