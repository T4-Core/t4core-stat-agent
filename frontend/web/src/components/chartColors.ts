// 차트 색과 범례 규칙을 한 곳에서 정합니다.
// - 차트가 2개 이상이면 번호마다 고정 색을 씁니다. (1번 청록, 2번 파랑, …)
// - 여러 차트를 합친 콤보 차트는 재료 차트의 색을 그대로 이어받습니다.
// - 레이더처럼 합쳤어도 항목(지역 등)이 재료 차트와 대응하지 않으면, 재료 차트 색과 겹치지 않는 색을 씁니다.
// - 한 차트에 항목이 여러 개면 항목마다 다른 색을 쓰고, 범례로 이름을 보여줍니다.
import type { CSSProperties } from 'react';
import type { PlotlyFigure } from '../api/types';
import type { ChartSpec } from '../data/types';

// 이름부터 다른 8가지 색입니다: 파랑, 주황, 초록, 빨강, 보라, 노랑, 하늘, 분홍.
// 일반 시력에서 가장 비슷한 두 색도 뚜렷하게 구분되도록 골랐습니다. (색 거리 계산 + 막대·선으로 그려서 확인)
// 8가지를 넘기면 그 뒤는 같은 색의 연한 톤 + 범례로 구분합니다.
export const CHART_COLORS = ['#1f5fbf', '#f5781f', '#24a148', '#c8102e', '#8a3ffc', '#e3b100', '#1fb3d4', '#f572b0'];
// 차트가 한 개이고 항목도 한 개일 때는 기존 디자인 색을 씁니다.
export const SINGLE_COLOR = '#7ba39d';

export type ChartPaint = {
  /** 차트 번호 색 (차트가 2개 이상일 때만) */
  color?: string;
  /** 합친 차트의 재료 차트 색 (merged_from 순서). 번호 표시를 나눠 칠할 때 씁니다. */
  sourceColors?: string[];
  /** 합친 그림의 항목이 재료 차트와 하나씩 대응할 때(콤보) 항목별 색. 대응하지 않으면(레이더) 비어 있습니다. */
  traceColors?: string[];
};

export type LegendItem = { name: string; color: string; shape: 'box' | 'line' | 'dot' };

type Trace = Record<string, unknown> & { type?: string; name?: unknown; mode?: unknown; labels?: unknown[] };

// 조각마다 색을 칠하는 차트 (파이·트리맵 등)
const SLICE_TYPES = new Set(['pie', 'treemap', 'sunburst', 'funnelarea']);
// 선이나 막대처럼 항목마다 한 색을 칠하는 차트
const SERIES_TYPES = new Set(['bar', 'scatter', 'scattergl', 'scatterpolar', 'scatterpolargl', 'histogram', 'box', 'funnel', 'waterfall']);

/** 흰색을 섞어 연한 톤을 만듭니다. amount 0 = 원래 색, 1 = 흰색 */
export function tint(hex: string, amount: number) {
  const value = Number.parseInt(hex.slice(1), 16);
  const mix = (shift: number) => Math.round(((value >> shift) & 255) + (255 - ((value >> shift) & 255)) * amount);
  return `#${[16, 8, 0].map((shift) => mix(shift).toString(16).padStart(2, '0')).join('')}`;
}

/** n번째 색. 8개를 넘으면 같은 색의 연한 톤으로 이어갑니다. */
export function colorAt(index: number) {
  const base = CHART_COLORS[index % CHART_COLORS.length];
  const round = Math.floor(index / CHART_COLORS.length);
  return round === 0 ? base : tint(base, Math.min(0.25 + round * 0.2, 0.7));
}

/** 항목 색: 첫 항목은 차트 색, 나머지는 겹치지 않는 색을 차례로 씁니다. */
export function seriesColors(count: number, first = CHART_COLORS[0]) {
  const order = [first, ...CHART_COLORS.filter((color) => color !== first)];
  return Array.from({ length: count }, (_, index) => {
    const base = order[index % order.length];
    const round = Math.floor(index / order.length);
    return round === 0 ? base : tint(base, Math.min(0.25 + round * 0.2, 0.7));
  });
}

/**
 * 재료 차트 색과 겹치지 않는 항목 색 (레이더처럼 항목이 재료 차트와 대응하지 않는 합친 차트용)
 * 차트 자기 번호 색 → 재료 차트가 안 쓴 색 → 그 색들의 연한 톤 순서로 씁니다.
 */
export function freeColors(count: number, avoid: string[], first?: string) {
  const free = CHART_COLORS.filter((color) => !avoid.includes(color));
  const order = first && !avoid.includes(first) ? [first, ...free.filter((color) => color !== first)] : free;
  // 재료 차트가 8색을 모두 쓴 경우에만 회색 계열로 대신합니다.
  const base = order.length > 0 ? order : ['#5f6b73', '#9aa3a8'];
  return Array.from({ length: count }, (_, index) => {
    const color = base[index % base.length];
    const round = Math.floor(index / base.length);
    return round === 0 ? color : tint(color, Math.min(0.25 + round * 0.2, 0.7));
  });
}

type PaintItem = { id: string; mergedFrom?: string[]; figure?: PlotlyFigure | null };

/**
 * 색을 칠할 항목(trace)의 위치. 백엔드가 범례에서 숨긴 보조 선(덤벨의 두 점을 잇는 회색 선 등)은 빼고,
 * 항목이 모두 숨김이면 모두 칠합니다.
 */
export function seriesIndices(figure: PlotlyFigure | null | undefined) {
  const series = ((figure?.data ?? []) as Trace[])
    .map((trace, index) => ({ trace, index }))
    .filter(({ trace }) => SERIES_TYPES.has(traceKind(trace)));
  const shown = series.filter(({ trace }) => trace.showlegend !== false);
  return (shown.length > 0 ? shown : series).map(({ index }) => index);
}

/** 선·막대 항목(trace) 이름. 색을 칠하는 항목과 같은 순서입니다. */
function seriesNames(figure: PlotlyFigure | null | undefined) {
  const traces = (figure?.data ?? []) as Trace[];
  return seriesIndices(figure).map((index) => (typeof traces[index].name === 'string' ? (traces[index].name as string) : ''));
}

const isPolar = (figure: PlotlyFigure | null | undefined) => ((figure?.data ?? []) as Trace[]).some((trace) => traceKind(trace).includes('polar'));

/**
 * 합친 그림의 항목마다 재료 차트 색을 찾습니다.
 * - 항목 이름이 재료 차트의 항목 이름과 같으면 그 재료 차트 색 (콤보: 막대=출생아수 차트, 선=합계출산율 차트)
 * - 이름이 안 맞아도 레이더가 아니고 항목 수가 재료 수와 같으면 순서대로
 * - 그 밖(레이더: 항목이 지역)은 대응하지 않음 → undefined
 */
function matchTraces(item: PaintItem, sources: { color: string; figure?: PlotlyFigure | null }[]) {
  const own = seriesNames(item.figure);
  if (own.length === 0) return undefined;
  const sourceNames = sources.map((source) => seriesNames(source.figure));
  const byName = own.map((name) => sources[sourceNames.findIndex((names) => name !== '' && names.includes(name))]?.color);
  if (byName.every(Boolean)) return byName as string[];
  if (!isPolar(item.figure) && own.length === sources.length) return sources.map((source) => source.color);
  return undefined;
}

/**
 * 차트마다 번호 색과 재료 차트 색을 정합니다.
 * items 는 화면에 그리는 순서이며, mergedFrom 은 합친 차트가 쓴 재료 차트의 id 입니다.
 */
export function paintCharts(items: PaintItem[]) {
  const paints = new Map<string, ChartPaint>();
  if (items.length < 2) return paints;
  items.forEach((item, index) => paints.set(item.id, { color: colorAt(index) }));
  const byId = new Map(items.map((item) => [item.id, item]));
  for (const item of items) {
    const sources = (item.mergedFrom ?? []).map((id) => ({ color: paints.get(id)?.color, figure: byId.get(id)?.figure }));
    if (sources.length < 2 || !sources.every((source) => source.color)) continue;
    const found = sources as { color: string; figure?: PlotlyFigure | null }[];
    paints.set(item.id, { ...paints.get(item.id), sourceColors: found.map((source) => source.color), traceColors: matchTraces(item, found) });
  }
  return paints;
}

/** 화면용 차트 목록에 번호 색과 재료 차트 색을 채웁니다. */
export function applyChartPaint(charts: ChartSpec[]) {
  const paints = paintCharts(charts);
  for (const chart of charts) Object.assign(chart, paints.get(chart.id) ?? {});
  return charts;
}

/** 흰 글씨가 잘 읽히는 색인지 (흰색과의 대비 3:1 이상) */
function whiteReadable(hex: string) {
  const channel = (shift: number) => {
    const value = ((Number.parseInt(hex.slice(1), 16) >> shift) & 255) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  const luminance = 0.2126 * channel(16) + 0.7152 * channel(8) + 0.0722 * channel(0);
  return 1.05 / (luminance + 0.05) >= 3;
}

const DARK_TEXT = '#1e2928';

/** 번호 표시 색. 콤보 차트는 재료 차트 색을 나눠 칠합니다. 노랑·하늘·분홍처럼 밝은 색에는 진한 글씨를 씁니다. */
export function badgeStyle(paint: ChartPaint | undefined): CSSProperties | undefined {
  if (!paint?.color) return undefined;
  const sources = paint.sourceColors ?? [];
  if (sources.length < 2) return { background: paint.color, borderColor: paint.color, color: whiteReadable(paint.color) ? '#fff' : DARK_TEXT };
  const step = 100 / sources.length;
  const stops = sources.map((color, index) => `${color} ${index * step}% ${(index + 1) * step}%`).join(', ');
  return { background: `linear-gradient(90deg, ${stops})`, borderColor: 'transparent', color: sources.every(whiteReadable) ? '#fff' : DARK_TEXT };
}

const traceKind = (trace: Trace) => String(trace.type ?? 'scatter');

/**
 * 그림의 항목마다 칠할 색과 범례를 만듭니다.
 * - colors: 선·막대 차트는 항목(trace)마다 한 색, 파이·트리맵은 조각마다 한 색
 * - legend: 항목이 2개 이상일 때만 (하나면 제목이 곧 설명)
 */
export function paintFigure(figure: PlotlyFigure, paint: ChartPaint = {}) {
  const traces = (figure.data ?? []) as Trace[];
  const slice = traces.length === 1 && SLICE_TYPES.has(traceKind(traces[0]));
  if (slice) {
    const labels = (traces[0].labels ?? []).map(String);
    const colors = seriesColors(labels.length, paint.color ?? CHART_COLORS[0]);
    const legend: LegendItem[] = labels.map((name, index) => ({ name, color: colors[index], shape: 'box' }));
    return { colors, slice: true, legend: legend.length >= 2 ? legend : [], indices: [0] };
  }
  const indices = seriesIndices(figure);
  const painted = indices.map((index) => traces[index]);
  let colors: string[];
  // 콤보: 항목마다 재료 차트 색
  if (paint.traceColors && paint.traceColors.length === painted.length) colors = paint.traceColors;
  else if (painted.length === 1) colors = [paint.color ?? SINGLE_COLOR];
  // 레이더처럼 항목이 재료 차트와 대응하지 않는 합친 차트: 재료 차트 색과 겹치지 않는 색
  else if (paint.sourceColors?.length) colors = freeColors(painted.length, paint.sourceColors, paint.color);
  else colors = seriesColors(painted.length, paint.color ?? CHART_COLORS[0]);
  const legend: LegendItem[] = painted.map((trace, index) => ({
    name: typeof trace.name === 'string' && trace.name ? trace.name : `항목 ${index + 1}`,
    color: colors[index],
    shape: legendShape(trace),
  }));
  return { colors, slice: false, legend: legend.length >= 2 ? legend : [], indices };
}

/** 범례 모양: 막대는 네모, 점만 찍는 차트(덤벨·산점도)는 동그라미, 선은 짧은 선 */
function legendShape(trace: Trace): LegendItem['shape'] {
  const kind = traceKind(trace);
  if (kind === 'bar' || kind === 'histogram' || kind === 'funnel' || kind === 'waterfall' || kind === 'box') return 'box';
  if (typeof trace.mode === 'string' && !trace.mode.includes('lines')) return 'dot';
  return 'line';
}
