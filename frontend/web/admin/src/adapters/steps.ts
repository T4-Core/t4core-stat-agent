// 백엔드 응답을 상세 화면의 단계별 요약·입력·출력으로 나눕니다.
// 큰 응답을 계속 들고 있지 않도록 표시할 글자 수를 제한해 문자열로 보관합니다.
import type { ChatResponse } from '../../../src/api/types';
import type { RunOutcome, RunRound } from '../runner/protocol';
import { MODULES, summarizeIssues, toIssues, type IssueSummary, type ModuleKey } from './issues';

export type StepState = 'ok' | 'warn' | 'error' | 'skipped' | 'unknown';

export type StepData = {
  key: ModuleKey;
  label: string;
  state: StepState;
  time: string;
  summary: [string, string][];
  input: string;
  output: string;
  raw: string;
  issues: IssueSummary[];
};

export type ResponseView = {
  label: string;
  steps: StepData[];
  answer: string;
  caveats: string[];
  qaMessage: string;
  notice?: string;
};

type Dict = Record<string, unknown>;

const PREVIEW_LIMIT = 12_000;
const RAW_LIMIT = 30_000;

const asDict = (value: unknown): Dict | null => (typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Dict : null);
const asList = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown) => (typeof value === 'string' ? value : typeof value === 'number' ? String(value) : '');

function toJson(value: unknown, limit = PREVIEW_LIMIT) {
  if (value === undefined || value === null) return '';
  const json = JSON.stringify(value, null, 2) ?? '';
  return json.length > limit ? `${json.slice(0, limit)}\n… (표시 한도를 넘어 생략했습니다)` : json;
}

function shortValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.map(shortValue).filter(Boolean).join(', ');
  if (typeof value === 'object') {
    const range = value as { from?: unknown; to?: unknown };
    if (range.from !== undefined || range.to !== undefined) return `${shortValue(range.from)}~${shortValue(range.to)}`;
    return JSON.stringify(value).slice(0, 80);
  }
  return String(value);
}

const rows = (items: [string, unknown][]): [string, string][] => items
  .map(([key, value]) => [key, shortValue(value)] as [string, string])
  .filter(([, value]) => value !== '');

function timeOf(rounds: RunRound[], response: ChatResponse, keys: string[]) {
  const sources = [...rounds.filter((round) => round.status.startsWith('needs_')).map((round) => round.timings), response.timings ?? {}];
  const values = sources.flatMap((timings) => keys.flatMap((key) => (key in timings ? [timings[key]] : [])));
  return values.length > 0 ? `${values.reduce((total, value) => total + value, 0).toFixed(1)}초` : '';
}

function stripFigure(item: unknown) {
  const drawn = asDict(item);
  if (!drawn) return item;
  const { figure, ...rest } = drawn;
  return { ...rest, has_figure: Boolean(figure) };
}

export function viewOf(response: ChatResponse, label: string, rounds: RunRound[]): ResponseView {
  const analysis = asDict(response.analysis);
  const bundle = asDict(analysis?.bundle);
  const slots = asDict(analysis?.slots);
  const views = asDict(response.views);
  const modules = asDict(response.modules);
  const plan = asDict(modules?.chart_plan);
  const m3 = asDict(modules?.module3);
  const drawn = asList(modules?.drawn);
  const answer = asDict(modules?.answer);
  const qa = asDict(modules?.qa);
  const units = asList(views?.units).map(asDict);
  const charts = asList(plan?.charts).map(asDict);
  const calc = asList(m3?.calc_results).map(asDict);
  const contents = asList(m3?.chart_contents);
  const counts = asDict(qa?.counts);
  const summaries = summarizeIssues(toIssues([response]));

  const base: Record<ModuleKey, Omit<StepData, 'key' | 'label' | 'state' | 'issues'> & { present: boolean }> = {
    analysis: {
      present: Boolean(analysis),
      time: timeOf(rounds, response, ['analyze']),
      summary: rows([['상태', analysis?.status], ['다시 쓴 질문', bundle?.rewritten], ['의도', bundle?.intent], ['시점', slots?.['시점']], ['지역', slots?.['지역']], ['대상', slots?.['대상']], ['지표', slots?.['지표']], ['검색어', analysis?.search_text]]),
      input: toJson({ question: response.question }),
      output: toJson({ status: analysis?.status, bundle, slots, clarifications: analysis?.clarifications, search_text: analysis?.search_text, decompose_reason: analysis?.decompose_reason, notes: analysis?.notes }),
      raw: toJson(analysis, RAW_LIMIT),
    },
    search: {
      present: Boolean(views),
      time: timeOf(rounds, response, ['views', 'select']),
      summary: rows([['상태', views?.status], ['검색 단위', units.length], ['후보 통계표', units.reduce((total, unit) => total + asList(unit?.candidates).length, 0)], ['만든 View', units.reduce((total, unit) => total + asList(unit?.views).length, 0)], ['근거 자료', asList(views?.records).length], ['선택 대기', asList(views?.pending).length || '']]),
      input: toJson(analysis?.view_bundle),
      output: toJson({ status: views?.status, units: units.map((unit) => ({ unit_id: unit?.unit_id, query: unit?.query, search_query: unit?.search_query, filters: unit?.filters, candidates: asList(unit?.candidates).length, views: asList(unit?.views).length, selected: unit?.selected, notes: unit?.notes })), pending: asList(views?.pending).length, notes: views?.notes }),
      raw: toJson(views, RAW_LIMIT),
    },
    m2: {
      present: Boolean(plan),
      time: '',
      summary: rows([['차트 계획', charts.length], ['차트 유형', charts.map((chart) => chart?.chart_type)], ['측정값', charts.map((chart) => text(asDict(chart?.measure)?.name) || text(chart?.measure))], ['판단 이유', charts[0]?.reason], ['계획 경고', asList(modules?.chart_errors).length || '']]),
      input: toJson({ view_ids: charts.flatMap((chart) => asList(chart?.view_ids)) }),
      output: toJson(plan),
      raw: toJson({ chart_plan: plan, charts: modules?.charts, chart_errors: modules?.chart_errors }, RAW_LIMIT),
    },
    m3: {
      present: Boolean(m3),
      time: '',
      summary: rows([['계산 단계', calc.length], ['계산 종류', [...new Set(calc.map((item) => text(item?.op)))]], ['차트 데이터', contents.length], ['메모', calc.map((item) => text(item?.note)).filter(Boolean).slice(0, 2)]]),
      input: toJson(asDict(m3?.chart_plan)),
      output: toJson({ calc_results: m3?.calc_results, validation: m3?.validation }),
      raw: toJson(m3, RAW_LIMIT),
    },
    m5: {
      present: drawn.length > 0,
      time: '',
      summary: rows([['그린 차트', drawn.filter((item) => asDict(item)?.status === 'drawn').length], ['건너뜀', drawn.filter((item) => asDict(item)?.status === 'skipped').length || ''], ['차트 유형', drawn.map((item) => asDict(item)?.chart_type)], ['제목', drawn.map((item) => asDict(item)?.title)], ['사유', drawn.map((item) => asDict(item)?.reason).filter(Boolean)]]),
      input: toJson(contents.map((item) => { const content = asDict(item); return { chart_id: content?.chart_id, chart_type: content?.chart_type, title: content?.title, columns: content?.columns, rows: asList(content?.rows).slice(0, 10) }; })),
      output: toJson(drawn.map(stripFigure)),
      raw: toJson(drawn.map(stripFigure), RAW_LIMIT),
    },
    m6: {
      present: Boolean(answer),
      time: '',
      summary: rows([['답변 방식', answer?.method], ['답변 길이', answer ? `${text(answer.answer).length}자` : ''], ['근거 표', asList(answer?.tables).length], ['주의사항', asList(answer?.caveats).length || ''], ['자료 부족', answer?.insufficient === true ? '예' : '']]),
      input: toJson({ calc_results: m3?.calc_results, displays: m3?.displays }),
      output: toJson({ answer: answer?.answer, caveats: answer?.caveats, insufficient: answer?.insufficient, method: answer?.method, used_step_ids: answer?.used_step_ids }),
      raw: toJson(answer, RAW_LIMIT),
    },
    qa: {
      present: Boolean(qa),
      time: '',
      summary: rows([['상태', qa?.status], ['중단 단계', qa?.stopped_stage], ['검사 지점', asList(qa?.checked).length], ['경고', counts?.warning], ['오류', counts?.error], ['참고(info)', counts?.info], ['재시도', asList(qa?.retries).length || ''], ['제외', asList(qa?.dropped).length || '']]),
      input: toJson({ checked: qa?.checked, skipped: qa?.skipped }),
      output: toJson({ status: qa?.status, stopped_at: qa?.stopped_at, stopped_stage: qa?.stopped_stage, message: qa?.message, counts, retries: qa?.retries, dropped: qa?.dropped }),
      raw: toJson({ ...qa, issues: asList(qa?.issues).filter((item) => asDict(item)?.severity !== 'info') }, RAW_LIMIT),
    },
  };

  const steps = MODULES.map(({ key, label }): StepData => {
    const { present, ...step } = base[key];
    const issues = summaries.filter((item) => item.module === key);
    const hasError = issues.some((item) => item.severity === 'error') || (key === 'qa' && qa?.status === 'stopped');
    const state: StepState = !present ? 'skipped' : hasError ? 'error' : issues.length > 0 ? 'warn' : 'ok';
    return { key, label, state, issues, ...step };
  });

  return {
    label,
    steps,
    answer: text(answer?.answer) || text(response.result?.answer),
    caveats: asList(response.result?.caveats ?? answer?.caveats).map(text).filter(Boolean),
    qaMessage: text(qa?.message),
  };
}

export function toResponseViews(outcome: RunOutcome): ResponseView[] {
  return outcome.responses.map((response, index) => viewOf(response, outcome.labels?.[index] ?? `응답 ${index + 1}`, outcome.rounds));
}
