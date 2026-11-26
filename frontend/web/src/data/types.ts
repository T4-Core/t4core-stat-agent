// 화면에서 쓰는 데이터 모양입니다.
import type { PlotlyFigure } from '../api/types';

export type TimeMode = 'year' | 'range';

export type Filters = {
  regions: string[];
  district: string;
  timeMode: TimeMode;
  years: number[];
  target: string;
};

export type TableChoice = 'A' | 'B' | 'both';

export type RunStatus = 'pending' | 'needs_selection' | 'needs_clarification' | 'done' | 'out_of_scope' | 'error';

export type RunRecord = {
  id: string;
  question: string;
  tags: string[];
  chartCount: number;
  table: TableChoice;
  status: RunStatus;
  requestQuestion?: string;
  sentAt?: number;
  message?: string;
  favorite: boolean;
  needsSelection: boolean;
  thumb: 'bars' | 'line';
  createdAt?: number;
  seedGroup?: '오늘' | '어제' | '지난 7일';
  seedTime?: string;
};

export type ChartKind = 'bar' | 'line' | 'area' | 'donut' | 'combo';

export type ChartSpec = {
  id: string;
  no: number;
  kind: ChartKind;
  title: string;
  heading: string;
  unit: string;
  years: string[];
  values: number[];
  values2?: number[];
  ticks: number[];
  ticks2?: number[];
  summary: string;
  delta: string;
  period?: string;
  figure?: PlotlyFigure;
  chartType?: string;
  /** 차트 번호 색 (차트가 2개 이상일 때) */
  color?: string;
  /** 콤보 차트가 합친 재료 차트의 색 */
  sourceColors?: string[];
  /** 합친 그림의 항목별 재료 차트 색 (콤보처럼 항목이 재료 차트와 대응할 때만) */
  traceColors?: string[];
  /** 콤보 차트가 합친 재료 차트의 id */
  mergedFrom?: string[];
};

export type TextPart = { text: string; tone?: 'strong' | 'accent' };
export type Paragraph = { parts: TextPart[]; marker?: number };
export type SummaryRow = { label: string; value: string };

export type ResultView = {
  charts: ChartSpec[];
  paragraphs: Paragraph[];
  summary: SummaryRow[];
  source: string;
  plainAnswer: string;
  previewAnswer: TextPart[];
  live?: boolean;
  sourceUrl?: string;
  caveats?: string[];
  notices?: string[];
  tables?: EvidenceTableData[];
  details?: DetailView[];
};

export type EvidenceTableData = {
  id: string;
  kind: string;
  title: string;
  columns: string[];
  rows: string[][];
  highlight: number[];
  truncated: boolean;
  totalRows: number;
  recordIds: string[];
};

export type DetailView = {
  no: number;
  responseIndex: number;
  recordId: string;
  tblId: string;
  title: string;
  shortTitle: string;
  subtitle: string;
  chips: string[];
  table: EvidenceTableData;
  meta: [string, string][];
  url: string;
};

export type ConditionRow = { key: string; asked: string; used: string; ok: boolean; note: string };

export type ChoiceCard = {
  token: string;
  optionId: string;
  badge: string;
  name: string;
  org: string;
  rows: [string, string][];
  value: string;
  valueLabel: string;
  unit: string;
  hint: string;
  url: string;
};

export type ClarificationGroup = {
  slot: string;
  reason: string;
  multi: boolean;
  options: { id: string; value: string; label: string }[];
};

export type StatTable = {
  id: 'A' | 'B';
  badge: string;
  name: string;
  org: string;
  basis: string;
  period: string;
  region: string;
  value: string;
  hint: string;
};
