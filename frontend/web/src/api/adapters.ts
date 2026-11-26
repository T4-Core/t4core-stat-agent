// 백엔드 응답을 화면에서 쓰는 모양으로 바꿉니다. 응답 구조가 바뀌면 이 파일만 고치면 됩니다.
import type { ChartKind, ChartSpec, ChoiceCard, ClarificationGroup, ConditionRow, DetailView, EvidenceTableData, Paragraph, ResultView, SummaryRow, TextPart } from '../data/types';
import type { ChatResponse, JudgeResult, PlotlyFigure } from './types';

type RawRecord = {
  id: string;
  table?: { columns?: string[]; rows?: unknown[][] };
  metadata?: { survey_nm?: string; view_type?: string; prd_se?: string; prd_from?: string; prd_to?: string; unit?: string };
  source?: { tbl_id?: string; kosis_url?: string };
};
type RawOption = {
  option_id: string;
  tbl_nm?: string;
  survey_nm?: string | null;
  description?: string;
  kosis_url?: string | null;
  basis?: Record<string, unknown>;
  value_preview?: { key?: Record<string, unknown>; value?: unknown }[];
};
type RawPending = { unit_id: string; selection_token: string; options?: RawOption[] };
type RawUnit = { candidates?: { tbl_id: string; tbl_nm?: string; survey_nm?: string }[] };
type RawFilters = { 지역?: string[]; 시점?: (string | number)[]; 대상?: string[]; 지표?: string[] };
type RawBundle = { filters?: RawFilters };
type RawTable = {
  table_id: string;
  kind: string;
  title?: string;
  columns?: string[];
  rows?: (string | null)[][];
  record_ids?: string[];
  highlight_rows?: number[];
  truncated?: boolean;
  total_rows?: number;
};
type RawDrawn = { chart_id: string; chart_type?: string | null; status?: string; title?: string | null; reason?: string | null; figure?: PlotlyFigure | null };
type RawCaveat = string | { text?: string; message?: string };
type RawChat = {
  question?: string;
  status?: string;
  notes?: RawCaveat[];
  analysis?: {
    view_bundle?: RawBundle | null;
    slots?: Record<string, { raw?: string; value?: unknown }[]>;
    clarifications?: { slot: string; reason?: string; multi?: boolean; options?: { option_id: string; value: string; label?: string }[] }[];
  } | null;
  views?: { view_bundle?: RawBundle | null; units?: RawUnit[]; pending?: RawPending[] } | null;
  records?: RawRecord[];
  result?: { answer?: string; caveats?: RawCaveat[]; sources?: string[]; insufficient?: boolean; unverified_numbers?: string[] } | null;
  modules?: {
    records?: RawRecord[];
    charts?: { chart_id: string; view_ids?: string[] }[];
    drawn?: RawDrawn[];
    answer?: { tables?: RawTable[]; caveats?: RawCaveat[]; insufficient?: boolean } | null;
    chart_notices?: RawCaveat[];
    request_outcomes?: { outcome?: string }[];
  } | null;
};

const CYCLE: Record<string, string> = { Y: '연간', M: '월간', Q: '분기', H: '반기' };
const VIEW_TYPE: Record<string, string> = { trend: '추세', value: '값', compare: '비교', rank: '순위', share: '구성비' };
const KINDS = new Set<ChartKind>(['bar', 'line', 'area', 'donut', 'combo']);
const SLOT_ORDER = ['시점', '지역', '대상', '지표', '성별', '연령'];
const NUMBER = /[+-]?\d[\d,]*(?:\.\d+)?(?:\s?(?:%p|%|만\s?가구|천\s?가구|가구|만\s?명|천\s?명|명|건|조\s?원|억\s?원|만\s?원|원|배))?/g;

const raw = (response: ChatResponse) => response as unknown as RawChat;
const textOf = (item: RawCaveat) => (typeof item === 'string' ? item : item?.text || item?.message || '');
const unique = <T,>(items: T[]) => [...new Set(items)];

function filtersOf(response: RawChat) {
  return response.analysis?.view_bundle?.filters ?? response.views?.view_bundle?.filters ?? {};
}

function yearsText(values: (string | number)[] | undefined) {
  const years = unique((values ?? []).map(Number).filter((year) => Number.isInteger(year) && year > 0)).sort((a, b) => a - b);
  if (years.length === 0) return '';
  if (years.length === 1) return String(years[0]);
  const continuous = years.at(-1)! - years[0] === years.length - 1;
  if (continuous) return `${years[0]}~${years.at(-1)}`;
  return years.length <= 3 ? years.join('·') : `${years[0]}~${years.at(-1)}`;
}

export function toTags(response: ChatResponse) {
  const filters = filtersOf(raw(response));
  const tags = [...(filters.지역 ?? []).slice(0, 1)];
  if (tags.length === 0) tags.push('전국');
  const time = yearsText(filters.시점);
  if (time) tags.push(time);
  const target = filters.대상?.[0] ?? filters.지표?.[0];
  if (target) tags.push(target);
  return tags;
}

/** 답변 문장: 숫자만 굵게 표시하고 ※ 메모 줄은 주의사항으로 분리합니다. */
function toAnswer(answer: string) {
  const lines = answer.split('\n').map((line) => line.trim()).filter(Boolean);
  const body = lines.filter((line) => !line.startsWith('※'));
  const notes = lines.filter((line) => line.startsWith('※')).map((line) => line.replace(/^※\s*/, ''));
  const paragraphs: Paragraph[] = body.map((line) => ({ parts: highlight(line) }));
  return { paragraphs, notes };
}

function highlight(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let cursor = 0;
  for (const match of text.matchAll(NUMBER)) {
    const start = match.index;
    const end = start + match[0].length;
    if (/^\s*(년|월|분기|반기|세|대|인)/.test(text.slice(end))) continue;
    if (start > cursor) parts.push({ text: text.slice(cursor, start) });
    parts.push({ text: match[0], tone: 'strong' });
    cursor = end;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor) });
  return parts;
}

function recordsOf(response: RawChat) {
  const byId = new Map<string, RawRecord>();
  for (const record of [...(response.records ?? []), ...(response.modules?.records ?? [])]) byId.set(record.id, record);
  return byId;
}

function tableNames(response: RawChat) {
  const names = new Map<string, { table: string; survey: string }>();
  for (const unit of response.views?.units ?? []) {
    for (const item of unit.candidates ?? []) names.set(item.tbl_id, { table: item.tbl_nm ?? '', survey: item.survey_nm ?? '' });
  }
  return names;
}

function periodText(record?: RawRecord) {
  const from = record?.metadata?.prd_from;
  const to = record?.metadata?.prd_to;
  if (!from) return '';
  return !to || from === to ? `${from}` : `${from}~${to}`;
}

function titleOf(drawn: RawDrawn) {
  const layoutTitle = drawn.figure?.layout?.title;
  const text = typeof layoutTitle === 'string' ? layoutTitle : (layoutTitle as { text?: string } | undefined)?.text;
  return (drawn.title || text || `차트 ${drawn.chart_id}`).replace(/<[^>]+>/g, '');
}

function toChart(drawn: RawDrawn, no: number, response: RawChat, records: Map<string, RawRecord>, prefix = ''): ChartSpec {
  const viewIds = response.modules?.charts?.find((item) => item.chart_id === drawn.chart_id)?.view_ids ?? [];
  const record = viewIds.map((id) => records.get(id)).find(Boolean);
  const traces = (drawn.figure?.data ?? []) as { x?: unknown[]; y?: unknown[]; customdata?: unknown[] }[];
  const first = traces.length === 1 ? traces[0] : undefined;
  const hasSeries = Boolean(first?.x && first.y && first.x.length === first.y.length && first.y.every((value) => typeof value === 'number'));
  const years = hasSeries ? first!.x!.map(String) : [];
  const values = hasSeries ? (first!.y as number[]) : [];
  const display = first?.customdata?.every((item) => typeof item === 'string') ? (first.customdata as string[]) : null;
  const unit = record?.metadata?.unit ?? '';
  const summary = values.length >= 2
    ? `${display?.[0] ?? `${values[0].toLocaleString('ko-KR')}${unit}`} → ${display?.at(-1) ?? `${values.at(-1)!.toLocaleString('ko-KR')}${unit}`}`
    : '';
  const title = `${prefix}${titleOf(drawn)}`;
  const type = drawn.chart_type as ChartKind;
  return {
    id: `${prefix}${drawn.chart_id}`,
    no,
    kind: KINDS.has(type) ? type : 'bar',
    title,
    heading: title,
    unit,
    period: periodText(record),
    years,
    values,
    ticks: [],
    summary,
    delta: '',
    figure: drawn.figure ?? undefined,
    chartType: drawn.chart_type ?? undefined,
  };
}

function toEvidence(table: RawTable): EvidenceTableData {
  return {
    id: table.table_id,
    kind: table.kind,
    title: table.title ?? '',
    columns: table.columns ?? [],
    rows: (table.rows ?? []).map((row) => row.map((cell) => cell ?? '-')),
    highlight: table.highlight_rows ?? [],
    truncated: Boolean(table.truncated),
    totalRows: table.total_rows ?? table.rows?.length ?? 0,
    recordIds: table.record_ids ?? [],
  };
}

function toSummary(tables: RawTable[]): SummaryRow[] {
  const rows: SummaryRow[] = [];
  for (const table of tables.filter((item) => item.kind === 'calc_summary')) {
    const columns = table.columns ?? [];
    for (const row of table.rows ?? []) {
      const cell = (name: string) => row[columns.indexOf(name)] ?? '';
      const base = cell('기준');
      rows.push({ label: `${cell('계산')}${base ? ` (${base})` : ''}`, value: cell('결과') });
    }
  }
  return rows;
}

function toDetail(table: RawTable, no: number, response: RawChat, records: Map<string, RawRecord>, responseIndex: number): DetailView {
  const record = (table.record_ids ?? []).map((id) => records.get(id)).find(Boolean);
  const tblId = record?.source?.tbl_id ?? '';
  const name = tableNames(response).get(tblId);
  const survey = name?.survey || record?.metadata?.survey_nm || table.title || '';
  const tableName = name?.table || table.title || '';
  const cycle = CYCLE[record?.metadata?.prd_se ?? ''] ?? record?.metadata?.prd_se ?? '';
  const period = periodText(record);
  const viewType = VIEW_TYPE[record?.metadata?.view_type ?? ''] ?? record?.metadata?.view_type ?? '';
  const unit = record?.metadata?.unit ?? '';
  const rows = (table.rows ?? []).length;
  return {
    no,
    responseIndex,
    recordId: record?.id ?? '',
    tblId,
    title: tableName && tableName !== survey ? `${survey} · ${tableName}` : survey || `통계표 ${no}`,
    shortTitle: tableName || survey || `통계표 ${no}`,
    subtitle: [viewType, cycle].filter(Boolean).join(' · '),
    chips: [viewType, cycle, period, unit ? `단위: ${unit}` : '', `${table.total_rows ?? rows}행`].filter(Boolean),
    table: toEvidence(table),
    meta: [['조사명', survey], ['표 이름', tableName], ['표 ID', tblId], ['주기', cycle], ['표시 기간', period], ['단위', unit]].filter((item) => item[1]) as [string, string][],
    url: record?.source?.kosis_url ?? '',
  };
}

export function toResultView(responses: ChatResponse[], labels: string[] = []): ResultView {
  const charts: ChartSpec[] = [];
  const paragraphs: Paragraph[] = [];
  const summary: SummaryRow[] = [];
  const caveats: string[] = [];
  const notices: string[] = [];
  const tables: EvidenceTableData[] = [];
  const details: DetailView[] = [];
  const urls: string[] = [];
  const sources: string[] = [];
  const plain: string[] = [];

  responses.forEach((response, index) => {
    const data = raw(response);
    const label = responses.length > 1 ? labels[index] || `통계표 ${index + 1}` : '';
    const prefix = label ? `${label} · ` : '';
    const records = recordsOf(data);
    const answerTables = data.modules?.answer?.tables ?? [];
    for (const drawn of data.modules?.drawn ?? []) {
      if (drawn.status === 'drawn' && drawn.figure) charts.push(toChart(drawn, charts.length + 1, data, records, prefix));
      else if (drawn.reason) notices.push(`차트를 그리지 못했어요: ${drawn.reason}`);
    }
    const answer = toAnswer(data.result?.answer ?? '');
    if (label && answer.paragraphs.length > 0) paragraphs.push({ parts: [{ text: label, tone: 'accent' }] });
    paragraphs.push(...answer.paragraphs);
    plain.push(`${label ? `[${label}] ` : ''}${answer.paragraphs.map((item) => item.parts.map((part) => part.text).join('')).join(' ')}`);
    summary.push(...toSummary(answerTables).map((row) => ({ ...row, label: `${prefix}${row.label}` })));
    caveats.push(...answer.notes, ...(data.result?.caveats ?? []).map(textOf), ...(data.modules?.answer?.caveats ?? []).map(textOf));
    if (data.result?.unverified_numbers?.length) caveats.push(`자료에서 확인되지 않은 숫자: ${data.result.unverified_numbers.join(', ')}`);
    notices.push(...(data.modules?.chart_notices ?? []).map(textOf));
    tables.push(...answerTables.map(toEvidence));
    for (const table of answerTables.filter((item) => item.kind === 'view')) details.push(toDetail(table, details.length + 1, data, records, index));
    for (const source of data.result?.sources ?? []) {
      const url = source.match(/https?:\/\/\S+/)?.[0];
      if (url) urls.push(url);
    }
    for (const detail of details) if (detail.url) urls.push(detail.url);
  });

  const firstDetail = details[0];
  const sourceName = firstDetail ? firstDetail.title : '';
  if (sourceName) sources.push(sourceName);
  const previewParts = paragraphs.find((item) => item.parts.length > 0 && item.parts[0].tone !== 'accent')?.parts ?? [];

  return {
    live: true,
    charts,
    paragraphs,
    summary,
    source: sources.length > 0 ? `출처 · ${sources[0]}${details.length > 1 ? ` 외 ${details.length - 1}개` : ''}` : '출처 정보 없음',
    sourceUrl: unique(urls)[0] ?? 'https://kosis.kr',
    plainAnswer: plain.join('\n'),
    previewAnswer: previewParts,
    caveats: unique(caveats.filter(Boolean)),
    notices: unique(notices.filter(Boolean)),
    tables,
    details,
  };
}

function formatValue(value: unknown) {
  if (typeof value === 'number') return value.toLocaleString('ko-KR');
  return value === null || value === undefined ? '–' : String(value);
}

export function toChoices(response: ChatResponse): ChoiceCard[][] {
  return (raw(response).views?.pending ?? []).map((pending) => (pending.options ?? []).map((option, index) => {
    const basis = option.basis ?? {};
    const preview = option.value_preview?.[0];
    const key = preview?.key ?? {};
    const keyLabel = ['시점', '지역', '성별'].map((name) => key[name]).filter(Boolean).join(' · ');
    const cycle = String(basis['주기'] ?? '');
    const rows: [string, string][] = [
      ['조사', String(basis['조사'] ?? option.survey_nm ?? '')],
      ['수록기간', String(basis['기간'] ?? '')],
      ['주기', CYCLE[cycle] ?? cycle],
      ['단위', String(basis['단위'] ?? '')],
    ];
    const description = (option.description ?? '').split('\n').filter(Boolean);
    return {
      token: pending.selection_token,
      optionId: option.option_id,
      badge: `${String.fromCharCode(65 + index)} · 검색 ${String(basis['검색 순위'] ?? index + 1)}위`,
      name: option.tbl_nm || option.survey_nm || option.option_id,
      org: option.survey_nm ?? '',
      rows: rows.filter((row) => row[1]),
      value: formatValue(preview?.value),
      valueLabel: keyLabel ? `${keyLabel} 값` : '값 미리보기',
      unit: String(basis['단위'] ?? ''),
      hint: description.slice(1, 2).join(' '),
      url: option.kosis_url ?? '',
    };
  }));
}

export function toClarifications(response: ChatResponse): ClarificationGroup[] {
  return (raw(response).analysis?.clarifications ?? []).map((item) => ({
    slot: item.slot,
    reason: item.reason ?? '',
    multi: item.multi !== false,
    options: (item.options ?? []).map((option) => ({ id: option.option_id, value: option.value, label: option.label || option.value })),
  }));
}

/** 되묻기 화면의 '이미 확인한 조건' (질문에서 읽은 지역·시점·대상). 시점은 '2015~2020' 처럼 연도만 */
export function toKnownSlots(response: ChatResponse): Partial<Record<'지역' | '시점' | '대상', string>> {
  const slots = raw(response).analysis?.slots ?? {};
  const words = (name: string) => unique((slots[name] ?? []).map((item) => item.raw || slotText(item.value)).filter(Boolean));
  const region = words('지역');
  const target = [...words('대상'), ...words('지표')];
  const time = yearsText((slots.시점 ?? []).map((item) => (typeof item.value === 'number' ? item.value : Number(item.value))));
  return {
    ...(region.length > 0 && { 지역: region.length > 1 ? `${region[0]} 외 ${region.length - 1}` : region[0] }),
    ...(time && { 시점: time }),
    ...(target.length > 0 && { 대상: target[0] }),
  };
}

function slotText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.map(slotText).filter(Boolean).join(', ');
  if (typeof value === 'object') {
    const range = value as { from?: unknown; to?: unknown };
    if (range.from !== undefined || range.to !== undefined) return `${range.from ?? ''}~${range.to ?? ''}`;
    return JSON.stringify(value);
  }
  return String(value);
}

export function toConditions(judge: JudgeResult, recordId: string): ConditionRow[] {
  const record = judge.units?.flatMap((unit) => unit.records ?? []).find((item) => item.record_id === recordId);
  if (!record) return [];
  const entries = Object.entries(record.slots ?? {}).filter(([, slot]) => slot.status !== 'not_requested');
  const rank = (name: string) => (SLOT_ORDER.indexOf(name) === -1 ? SLOT_ORDER.length : SLOT_ORDER.indexOf(name));
  return entries.sort((a, b) => rank(a[0]) - rank(b[0])).map(([name, slot]) => ({
    key: name,
    asked: slotText(slot.requested) || '지정 없음',
    used: slotText(slot.found) || slot.evidence || '찾지 못함',
    ok: slot.status === 'match',
    note: slot.status === 'match' ? '' : slot.evidence ?? '',
  }));
}

export function thumbOf(response: ChatResponse): 'bars' | 'line' {
  const drawn = raw(response).modules?.drawn?.find((item) => item.status === 'drawn');
  return drawn?.chart_type === 'line' || drawn?.chart_type === 'area' ? 'line' : 'bars';
}
