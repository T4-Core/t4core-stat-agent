// 쿼리 실행 순서: 서버 확인 → 묶음 생성 → 한 개씩 사용자 화면에서 실행 → 결과 저장 → 다음 쿼리
import { useCallback, useEffect, useRef, useState } from 'react';
import { checkHealth } from '../../../src/api/client';
import { toIssues, type AdminIssue } from '../adapters/issues';
import { toResponseViews, type ResponseView } from '../adapters/steps';
import { createBatch, deleteBatch, saveRun } from '../supabase/testRuns';
import { toRunDetail, toRunSummary } from './compact';
import { setRunBusy } from './guard';
import type { LiveStatus, ParentMessage, PreviewMessage, RunOutcome } from './protocol';
import { toStoredDetail } from './responseCodec';
import { randomUUID } from '../../../src/utils/uuid';

export type RunPhase = 'idle' | 'starting' | 'running' | 'paused' | 'done';
export type ItemState = 'queued' | 'running' | 'input' | 'saving' | 'saved' | 'save_failed' | 'skipped';

export type ItemResult = {
  status: RunOutcome['status'];
  message?: string;
  activeMs: number;
  summary: ReturnType<typeof toRunSummary>;
  detail: unknown;
  /** 압축한 백엔드 응답 전체. 단계별 중간 결과 화면에서 풀어 씁니다. */
  gz?: string;
  labels?: string[];
  issues: AdminIssue[];
  views: ResponseView[];
};

export type RunItem = {
  position: number;
  question: string;
  state: ItemState;
  live: LiveStatus;
  clarified: boolean;
  startedAt: number;
  result: ItemResult | null;
  saveError: string;
};

export type RunnerState = {
  phase: RunPhase;
  items: RunItem[];
  current: number;
  error: string;
  startedAt: number;
};

const INITIAL: RunnerState = { phase: 'idle', items: [], current: -1, error: '', startedAt: 0 };

function toResult(outcome: RunOutcome): ItemResult {
  // 응답 원본은 크므로 화면과 저장에 필요한 값만 남깁니다.
  return {
    status: outcome.status,
    message: outcome.message,
    activeMs: outcome.activeMs,
    summary: toRunSummary(outcome),
    detail: toRunDetail(outcome),
    labels: outcome.labels,
    issues: toIssues(outcome.responses),
    views: toResponseViews(outcome),
  };
}

export function useQueryRunner() {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const [state, setState] = useState<RunnerState>(INITIAL);
  const stateRef = useRef(state);
  const tokenRef = useRef<string | null>(null);
  const batchRef = useRef<string | null>(null);

  const update = useCallback((patch: Partial<RunnerState>) => {
    stateRef.current = { ...stateRef.current, ...patch };
    setState(stateRef.current);
  }, []);

  const patchItem = useCallback((index: number, patch: Partial<RunItem>) => {
    update({ items: stateRef.current.items.map((item, position) => (position === index ? { ...item, ...patch } : item)) });
  }, [update]);

  const postToFrame = useCallback((message: ParentMessage) => {
    frameRef.current?.contentWindow?.postMessage(message, window.location.origin);
  }, []);

  const finish = useCallback(() => {
    tokenRef.current = null;
    setRunBusy(false);
    const { items } = stateRef.current;
    if (!items.some((item) => item.state === 'saved')) {
      // 저장된 쿼리가 없으면 빈 묶음을 팀 DB에 남기지 않습니다.
      const batchId = batchRef.current;
      batchRef.current = null;
      if (batchId) void deleteBatch(batchId).catch(() => undefined);
    }
    if (items.every((item) => item.state === 'skipped')) {
      postToFrame({ source: 'adm-parent', type: 'reset' });
      stateRef.current = { ...INITIAL, error: '실행한 쿼리가 없어 저장하지 않았습니다.' };
      setState(stateRef.current);
      return;
    }
    update({ phase: 'done', current: -1 });
  }, [postToFrame, update]);

  const runIndex = useCallback((index: number) => {
    const item = stateRef.current.items[index];
    if (!item) {
      finish();
      return;
    }
    // [CHANGED] 이전: const token = crypto.randomUUID();
    const token = randomUUID();
    tokenRef.current = token;
    update({ phase: 'running', current: index });
    patchItem(index, { state: 'running', live: 'pending', startedAt: Date.now() });
    postToFrame({ source: 'adm-parent', type: 'reset' });
    postToFrame({ source: 'adm-parent', type: 'start', token, question: item.question });
  }, [finish, patchItem, postToFrame, update]);

  const persist = useCallback(async (index: number) => {
    const item = stateRef.current.items[index];
    const batchId = batchRef.current;
    if (!item?.result || !batchId) return;
    patchItem(index, { state: 'saving', saveError: '' });
    update({ phase: 'running' });
    try {
      const { summary, detail, issues } = item.result;
      await saveRun({
        batchId,
        position: item.position,
        query: item.question,
        status: summary.status,
        qaStatus: summary.qaStatus,
        hasAnswer: summary.hasAnswer,
        chartCount: summary.chartCount,
        timings: summary.timings,
        detail,
        issues,
      });
      patchItem(index, { state: 'saved' });
      runIndex(index + 1);
    } catch (cause) {
      // 저장되지 않는데 유료 호출을 계속하지 않도록 다음 쿼리 전에 멈춥니다.
      patchItem(index, { state: 'save_failed', saveError: cause instanceof Error ? cause.message : '결과를 저장하지 못했습니다.' });
      update({ phase: 'paused' });
    }
  }, [patchItem, runIndex, update]);

  useEffect(() => {
    const onMessage = (event: MessageEvent<PreviewMessage>) => {
      if (event.origin !== window.location.origin || event.source !== frameRef.current?.contentWindow) return;
      const message = event.data;
      if (message?.source !== 'adm-preview') return;
      if (message.type === 'ready') {
        setReady(true);
        return;
      }
      if (message.token !== tokenRef.current) return;
      const index = stateRef.current.current;
      if (message.type === 'status') {
        const waiting = message.status !== 'pending';
        const item = stateRef.current.items[index];
        patchItem(index, {
          state: waiting ? 'input' : 'running',
          live: message.status,
          clarified: Boolean(item?.clarified) || waiting,
          startedAt: !waiting && item?.state === 'input' ? Date.now() : item?.startedAt ?? Date.now(),
        });
      }
      if (message.type === 'finished') {
        tokenRef.current = null;
        const result = toResult(message.outcome);
        patchItem(index, { result, state: 'saving' });
        void toStoredDetail(result.detail, message.outcome.responses).then((stored) => {
          patchItem(index, { result: { ...result, ...stored } });
          return persist(index);
        });
      }
      if (message.type === 'cancelled') {
        tokenRef.current = null;
        patchItem(index, { state: 'skipped' });
        runIndex(index + 1);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [patchItem, persist, runIndex]);

  const start = useCallback(async (questions: string[]) => {
    const list = questions.map((item) => item.trim()).filter(Boolean);
    if (list.length === 0 || !ready || stateRef.current.phase !== 'idle') return;
    const items = list.map((question, position): RunItem => ({ position, question, state: 'queued', live: 'pending', clarified: false, startedAt: 0, result: null, saveError: '' }));
    update({ ...INITIAL, phase: 'starting', items, startedAt: Date.now() });
    setRunBusy(true);
    try {
      // 비용이 나가기 전에 백엔드와 저장 공간을 먼저 확인합니다.
      if (!(await checkHealth())) throw new Error('백엔드에 연결하지 못했습니다. 서버가 켜져 있는지 확인해 주세요.');
      const title = list.length === 1 ? list[0] : `${list[0]} 외 ${list.length - 1}개`;
      batchRef.current = await createBatch(title, list.length);
    } catch (cause) {
      setRunBusy(false);
      update({ ...INITIAL, error: cause instanceof Error ? cause.message : '실행을 시작하지 못했습니다.' });
      return;
    }
    runIndex(0);
  }, [ready, runIndex, update]);

  const retrySave = useCallback(() => {
    const { phase, current } = stateRef.current;
    if (phase === 'paused') void persist(current);
  }, [persist]);

  /** 저장에 실패한 쿼리는 그대로 두고 다음 쿼리로 넘어갑니다. */
  const skipSave = useCallback(() => {
    const { phase, current } = stateRef.current;
    if (phase === 'paused') runIndex(current + 1);
  }, [runIndex]);

  /** 아직 시작하지 않은 쿼리를 실행하지 않고 여기서 끝냅니다. */
  const endEarly = useCallback(() => {
    if (stateRef.current.phase !== 'paused') return;
    update({ items: stateRef.current.items.map((item) => (item.state === 'queued' ? { ...item, state: 'skipped' } : item)) });
    finish();
  }, [finish, update]);

  const reset = useCallback(() => {
    if (stateRef.current.phase !== 'done') return;
    tokenRef.current = null;
    batchRef.current = null;
    setRunBusy(false);
    postToFrame({ source: 'adm-parent', type: 'reset' });
    stateRef.current = INITIAL;
    setState(INITIAL);
  }, [postToFrame]);

  const rerun = useCallback((question: string) => {
    reset();
    void start([question]);
  }, [reset, start]);

  return { frameRef, ready, state, start, retrySave, skipSave, endEarly, reset, rerun };
}
