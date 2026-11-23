// 백엔드 응답은 쿼리당 최대 700KB 정도라 필요한 내용만 줄여서 저장합니다.
import type { ChatResponse } from '../../../src/api/types';
import { toResponseViews } from '../adapters/steps';
import type { RunOutcome } from './protocol';

const MAX_BYTES = 240_000;
const STEP_TEXT_LIMIT = 2_000;
const MAX_TABLES = 4;
const MAX_ROWS = 30;

type Dict = Record<string, unknown>;

const asDict = (value: unknown): Dict | null => (typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Dict : null);
const asList = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const clip = (value: unknown, length = 500) => (typeof value === 'string' ? value.slice(0, length) : value);
const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;

function compactResponse(response: ChatResponse) {
  const modules = asDict(response.modules);
  const qa = asDict(modules?.qa);
  const answer = asDict(modules?.answer);
  const analysis = bytes(response.analysis ?? null) <= 8_000 ? response.analysis ?? null : null;
  return {
    status: response.status,
    analysis,
    answer: answer ? {
      answer: clip(answer.answer, 6_000),
      insufficient: answer.insufficient,
      method: answer.method,
      caveats: asList(answer.caveats).slice(0, 12).map((item) => clip(item)),
      tables: asList(answer.tables).slice(0, MAX_TABLES).map((item) => {
        const table = asDict(item);
        return { kind: table?.kind, title: clip(table?.title, 200), columns: table?.columns, rows: asList(table?.rows).slice(0, MAX_ROWS) };
      }),
    } : { answer: clip(response.result?.answer, 6_000) },
    charts: asList(modules?.drawn).map((item) => {
      const drawn = asDict(item);
      return { chart_id: drawn?.chart_id, chart_type: drawn?.chart_type, status: drawn?.status, title: clip(drawn?.title, 200), reason: clip(drawn?.reason), warnings: asList(drawn?.warnings).slice(0, 8).map((warning) => clip(warning)) };
    }),
    chart_errors: asList(modules?.chart_errors).slice(0, 40),
    notes: [...(response.notes ?? []), ...asList(modules?.notes)].slice(0, 30).map((note) => clip(note)),
    qa: qa ? { status: qa.status, stopped_stage: qa.stopped_stage, message: clip(qa.message), counts: qa.counts, checked: qa.checked, skipped: qa.skipped, retries: qa.retries, dropped: qa.dropped } : null,
  };
}

const clipStep = (value: string) => (value.length > STEP_TEXT_LIMIT ? `${value.slice(0, STEP_TEXT_LIMIT)}\n… (저장 한도를 넘어 생략했습니다)` : value);

export function toRunDetail(outcome: RunOutcome) {
  const detail = {
    version: 2,
    message: clip(outcome.message),
    rounds: outcome.rounds,
    active_ms: outcome.activeMs,
    labels: outcome.labels,
    responses: outcome.responses.map(compactResponse),
    // History에서 결과를 다시 볼 때 쓰는 단계별 요약·입력·출력
    step_views: toResponseViews(outcome).map((view) => view.steps.map(({ key, state, time, summary, input, output }) => ({
      key, state, time, summary, input: clipStep(input), output: clipStep(output),
    }))) as unknown[] | undefined,
  };
  if (bytes(detail) <= MAX_BYTES) return detail;
  // 그래도 크면 근거 표부터 뺍니다.
  const smaller = {
    ...detail,
    step_views: undefined,
    trimmed: true,
    responses: detail.responses.map((response) => ({ ...response, analysis: null, answer: { ...response.answer, tables: [] } })),
  };
  return bytes(smaller) <= MAX_BYTES ? smaller : { version: 2, trimmed: true, message: clip(outcome.message), rounds: outcome.rounds, active_ms: outcome.activeMs };
}

export function toRunSummary(outcome: RunOutcome) {
  const first = outcome.responses[0];
  const modules = outcome.responses.map((response) => asDict(response.modules));
  const qaStatuses = modules.map((item) => asDict(item?.qa)?.status).filter((value): value is string => typeof value === 'string');
  const qaStatus = qaStatuses.includes('stopped') ? 'stopped' : qaStatuses.includes('warned') ? 'warned' : qaStatuses[0] ?? null;
  const chartCount = modules.reduce((total, item) => total + asList(item?.drawn).filter((drawn) => asDict(drawn)?.status === 'drawn').length, 0);
  const hasAnswer = outcome.status === 'ok' && outcome.responses.some((response) => {
    // QA가 중단하면 result 칸에 안내 문구가 들어오므로, 모듈 응답이 있으면 모듈 6의 답변만 인정합니다.
    const modules = asDict(response.modules);
    return Boolean(modules ? asDict(modules.answer)?.answer : response.result?.answer);
  });
  return { status: outcome.status, qaStatus, chartCount, hasAnswer, timings: first?.timings ?? null };
}
