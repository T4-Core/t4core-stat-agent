// 팀 DB에 저장된 실행 결과를 결과 화면에서 쓰는 모양으로 되돌립니다.
import type { ChatResponse } from '../../../src/api/types';
import type { RunRound } from '../runner/protocol';
import type { ItemResult, RunItem } from '../runner/useQueryRunner';
import { MODULES, summarizeIssues, type AdminIssue, type ModuleKey } from './issues';
import { viewOf, type ResponseView, type StepData, type StepState } from './steps';

export type SavedRun = {
  position: number;
  query: string;
  status: string;
  qa_status: string | null;
  has_answer: boolean;
  chart_count: number;
  timings: Record<string, number> | null;
  detail: unknown;
  adm_run_issues: {
    occurrences: number;
    sample_path: string | null;
    adm_issue_groups: Pick<AdminIssue, 'module' | 'point' | 'kind' | 'severity' | 'message'> & { path_pattern: string };
  }[];
};

type Dict = Record<string, unknown>;
type StoredStep = Pick<StepData, 'key' | 'state' | 'time' | 'summary' | 'input' | 'output'>;

const asDict = (value: unknown): Dict | null => (typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Dict : null);
const asList = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

// 예전 결과에는 이 단계들의 상세가 저장되어 있지 않습니다.
const NOT_STORED_BEFORE: ModuleKey[] = ['search', 'm2', 'm3'];

function toIssues(run: SavedRun): AdminIssue[] {
  return run.adm_run_issues.map(({ occurrences, sample_path: samplePath, adm_issue_groups: group }) => ({
    module: group.module,
    point: group.point,
    kind: group.kind,
    severity: group.severity,
    path: samplePath ?? group.path_pattern,
    message: group.message,
    count: occurrences,
    source: group.point === 'chart_errors' || group.point === 'drawn' ? 'module' : 'qa',
  }));
}

function stateWith(base: StepState, issues: ReturnType<typeof summarizeIssues>): StepState {
  if (base === 'error' || issues.some((issue) => issue.severity === 'error')) return 'error';
  if (issues.length > 0) return 'warn';
  return base === 'skipped' || base === 'unknown' ? base : 'ok';
}

function fallbackView(issues: AdminIssue[]): ResponseView {
  const summaries = summarizeIssues(issues);
  return {
    label: '응답 1',
    answer: '',
    caveats: [],
    qaMessage: '',
    notice: '이 실행의 상세 내용은 용량 관리로 정리되어 상태와 오류 목록만 볼 수 있습니다.',
    steps: MODULES.map(({ key, label }) => {
      const stepIssues = summaries.filter((issue) => issue.module === key);
      return { key, label, state: stateWith('unknown', stepIssues), time: '', summary: [], input: '', output: '', raw: '', issues: stepIssues };
    }),
  };
}

function toViews(run: SavedRun, issues: AdminIssue[]): ResponseView[] {
  const detail = asDict(run.detail);
  // 압축 저장본은 상세 화면에서 풀어서 보여줍니다.
  if (typeof detail?.gz === 'string') return [];
  const responses = asList(detail?.responses).map(asDict).filter((item): item is Dict => Boolean(item));
  if (responses.length === 0) return run.status === 'error' ? [] : [fallbackView(issues)];

  const rounds = asList(detail?.rounds) as RunRound[];
  const finalRounds = rounds.filter((round) => !round.status.startsWith('needs_'));
  const labels = asList(detail?.labels);
  const storedViews = asList(detail?.step_views);
  const summaries = summarizeIssues(issues);

  return responses.map((saved, index) => {
    const answer = asDict(saved.answer);
    const hasModuleAnswer = Boolean(answer && ('method' in answer || 'insufficient' in answer));
    const response = {
      question: run.query,
      status: saved.status,
      analysis: saved.analysis ?? null,
      records: [],
      notes: [],
      timings: finalRounds[index]?.timings ?? {},
      result: { answer: answer?.answer, caveats: asList(answer?.caveats) },
      modules: saved.qa || asList(saved.charts).length > 0 || hasModuleAnswer ? {
        drawn: saved.charts,
        answer: hasModuleAnswer ? answer : null,
        qa: saved.qa,
        chart_errors: saved.chart_errors,
      } : null,
    } as unknown as ChatResponse;
    const label = typeof labels[index] === 'string' ? labels[index] as string : `응답 ${index + 1}`;
    const base = viewOf(response, label, rounds);
    const stored = asList(storedViews[index]) as StoredStep[];

    const steps = base.steps.map((step): StepData => {
      const stepIssues = summaries.filter((issue) => issue.module === step.key);
      const savedStep = stored.find((item) => item.key === step.key);
      if (savedStep) {
        return { ...step, ...savedStep, raw: savedStep.output, state: stateWith(savedStep.state, stepIssues), issues: stepIssues };
      }
      const missing = saved.status === 'ok' && NOT_STORED_BEFORE.includes(step.key);
      // 저장되지 않은 값을 0건처럼 보여주지 않도록 비웁니다.
      if (missing) return { ...step, state: stateWith('unknown', stepIssues), time: '', summary: [], input: '', output: '', raw: '', issues: stepIssues };
      const noInput = step.key === 'm5' || step.key === 'm6';
      return { ...step, input: noInput ? '' : step.input, state: stateWith(step.state, stepIssues), issues: stepIssues };
    });
    return { ...base, steps };
  });
}

export function restoreItem(run: SavedRun): RunItem {
  const detail = asDict(run.detail);
  const issues = toIssues(run);
  const status: ItemResult['status'] = run.status === 'error' || run.status === 'out_of_scope' ? run.status : 'ok';
  const rounds = asList(detail?.rounds) as RunRound[];
  return {
    position: run.position,
    question: run.query,
    state: 'saved',
    live: 'pending',
    clarified: rounds.some((round) => round.status?.startsWith('needs_')),
    startedAt: 0,
    saveError: '',
    result: {
      status,
      message: typeof detail?.message === 'string' ? detail.message : undefined,
      activeMs: typeof detail?.active_ms === 'number' ? detail.active_ms : 0,
      summary: { status, qaStatus: run.qa_status, chartCount: run.chart_count, hasAnswer: run.has_answer, timings: run.timings } as ItemResult['summary'],
      detail: run.detail,
      gz: typeof detail?.gz === 'string' ? detail.gz : undefined,
      labels: asList(detail?.labels).filter((label): label is string => typeof label === 'string'),
      issues,
      views: toViews(run, issues),
    },
  };
}
