// History에서 고른 쿼리를 쿼리 테스트 입력칸으로 전달합니다. 실행은 하지 않습니다.
import type { RunPhase } from './useQueryRunner';

export type QueryDraft = { id: number; questions: string[] };

let phase: RunPhase = 'idle';
let nextId = 1;
const phaseListeners = new Set<() => void>();
const draftListeners = new Set<(draft: QueryDraft) => void>();

export function setRunnerPhase(next: RunPhase) {
  if (phase === next) return;
  phase = next;
  phaseListeners.forEach((listener) => listener());
}

export const getRunnerPhase = () => phase;

export function subscribeRunnerPhase(listener: () => void) {
  phaseListeners.add(listener);
  return () => { phaseListeners.delete(listener); };
}

export function loadDraft(questions: string[]) {
  const draft = { id: nextId, questions };
  nextId += 1;
  draftListeners.forEach((listener) => listener(draft));
}

/** 다시 테스트: 입력칸에 넣기만 합니다. 실행 중이면 넣지 않습니다. */
export function requestDraft(questions: string[]) {
  if (phase === 'starting' || phase === 'running' || phase === 'paused') return false;
  if (phase === 'done' && !window.confirm('지금 보고 있는 실행 결과 화면이 닫히고 이 쿼리가 입력됩니다. 결과는 History에 남아 있습니다. 계속할까요?')) return false;
  loadDraft(questions);
  return true;
}

export function subscribeDraft(listener: (draft: QueryDraft) => void) {
  draftListeners.add(listener);
  return () => { draftListeners.delete(listener); };
}
