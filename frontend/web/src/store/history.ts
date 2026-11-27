// 질문 기록을 브라우저에 저장합니다. 다른 PC나 브라우저와는 공유되지 않습니다.
import { useSyncExternalStore } from 'react';
import { USE_MOCK } from '../api/client';
import { createSeedRuns } from '../data/examples';
import type { RunRecord, TableChoice } from '../data/types';
import { deletePayload } from './payloads';
import { randomUUID } from '../utils/uuid';

// 예시 기록과 실제 기록이 섞이지 않도록 저장 위치를 나눕니다.
const STORAGE_KEY = USE_MOCK ? 'kosis.history.v1' : 'kosis.history.live.v1';
export const INTERRUPTED = '새로고침 등으로 응답을 받지 못했어요. 비용이 중복되지 않도록 자동으로 다시 보내지 않았습니다.';
const listeners = new Set<() => void>();

function load(): RunRecord[] {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      return (JSON.parse(saved) as RunRecord[]).map((run) => (
        run.status === 'pending' ? { ...run, status: 'error' as const, message: INTERRUPTED } : run
      ));
    }
  } catch {
    // 저장소를 쓸 수 없는 환경에서는 빈 기록으로 시작합니다.
  }
  return USE_MOCK ? createSeedRuns() : [];
}

let runs = load();

function commit(next: RunRecord[]) {
  runs = next;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // 저장에 실패해도 현재 화면은 계속 동작합니다.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useRuns() {
  return useSyncExternalStore(subscribe, () => runs);
}

export function useRun(id: string | undefined) {
  const all = useRuns();
  return all.find((run) => run.id === id);
}

export function listRuns() {
  return runs;
}

export function getRun(id: string) {
  return runs.find((run) => run.id === id);
}

export function createRun(input: Pick<RunRecord, 'question' | 'tags'> & Partial<RunRecord>) {
  const needsSelection = input.needsSelection ?? input.question.includes('1인 가구');
  const run: RunRecord = {
    // [CHANGED] 이전: id: crypto.randomUUID(),
    id: randomUUID(),
    status: 'pending',
    favorite: false,
    chartCount: 2,
    table: 'A',
    thumb: 'bars',
    createdAt: Date.now(),
    ...input,
    needsSelection,
  };
  commit([run, ...runs]);
  return run;
}

export function updateRun(id: string, patch: Partial<RunRecord>) {
  commit(runs.map((run) => (run.id === id ? { ...run, ...patch } : run)));
}

export function completeRun(id: string, table?: TableChoice) {
  commit(runs.map((run) => (run.id === id ? { ...run, status: 'done', table: table ?? run.table } : run)));
}

export function removeRun(id: string) {
  commit(runs.filter((run) => run.id !== id));
  void deletePayload(id);
}

export function toggleFavorite(id: string) {
  commit(runs.map((run) => (run.id === id ? { ...run, favorite: !run.favorite } : run)));
}

export function routeForRun(run: RunRecord) {
  switch (run.status) {
    case 'pending':
      return `/generating/${run.id}`;
    case 'needs_selection':
      return `/select/${run.id}`;
    case 'needs_clarification':
      return `/clarify/${run.id}`;
    case 'done':
      return `/result/${run.id}`;
    default:
      return `/notice/${run.id}`;
  }
}

export function getRunGroup(run: RunRecord) {
  if (!run.createdAt) return run.seedGroup ?? '지난 7일';
  const today = new Date();
  const date = new Date(run.createdAt);
  const days = Math.floor((new Date(today.toDateString()).getTime() - new Date(date.toDateString()).getTime()) / 86_400_000);
  if (days <= 0) return '오늘';
  if (days === 1) return '어제';
  return days < 7 ? '지난 7일' : '이전';
}

export function getRunTime(run: RunRecord) {
  if (!run.createdAt) return run.seedTime ?? '';
  const date = new Date(run.createdAt);
  const group = getRunGroup(run);
  if (group === '지난 7일' || group === '이전') return `${date.getMonth() + 1}.${String(date.getDate()).padStart(2, '0')}`;
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}
