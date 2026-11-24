// 예시 데이터입니다. 백엔드를 연결하면 이 파일 대신 API 응답을 사용합니다.
import { USE_MOCK } from '../api/client';
import type { ChartSpec, Filters, ResultView, RunRecord, StatTable, TableChoice } from './types';

export const SIDO = ['전국', '서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주'];
export const YEARS = Array.from({ length: 16 }, (_, index) => 2010 + index); // 2010 ~ 2025
export const TARGET_GROUPS = [
  { label: '가구', items: ['전체 가구', '1인 가구', '다문화 가구', '한부모 가구', '고령자 가구'] },
  { label: '인구', items: ['전체 인구', '남성', '여성', '청년', '고령', '외국인'] },
  { label: '출생 · 혼인', items: ['출생아', '산모', '혼인', '이혼'] },
];

export const EMPTY_FILTERS: Filters = { regions: [], district: '전체', timeMode: 'year', years: [], target: '' };

export const STAT_TABLES: StatTable[] = [
  { id: 'A', badge: 'A · 실제 조사값', name: '인구총조사 · 가구원수별 가구', org: '통계청 · 일반가구 기준', basis: '실제로 세어 본 값', period: '2015 ~ 2023년', region: '전국 · 시도 · 시군구', value: '664.3', hint: '과거에 실제로 얼마였는지 알고 싶을 때 좋아요.' },
  { id: 'B', badge: 'B · 추계값', name: '장래가구추계 · 가구원수별 추계가구', org: '통계청 · 추계 기준', basis: '미래까지 계산해 본 값', period: '2000 ~ 2052년', region: '전국 · 시도', value: '647.7', hint: '앞으로 어떻게 변할지 전망까지 보고 싶을 때 좋아요.' },
];

const CHART_YEARS = ['2015', '2016', '2017', '2018', '2019', '2020'];
const COUNT_A = [520.3, 539.8, 561.9, 584.9, 614.8, 664.3];
const COUNT_B = [512.5, 531.2, 552.0, 574.3, 606.1, 647.7];
const RATE = [27.2, 27.9, 28.6, 29.3, 30.2, 31.7];
const COUNT_TICKS = [0, 200, 400, 600, 800];
const RATE_TICKS = [20, 25, 30, 35];

export const VIEW_ROWS = [
  ['2015', '5,203,440'], ['2016', '5,397,615'], ['2017', '5,618,677'],
  ['2018', '5,848,594'], ['2019', '6,147,516'], ['2020', '6,643,354'],
];
export const RATIO_ROWS = [
  ['2015', '19,111,030', '5,203,440', '27.2%'], ['2016', '19,367,696', '5,397,615', '27.9%'],
  ['2017', '19,673,875', '5,618,677', '28.6%'], ['2018', '19,979,188', '5,848,594', '29.3%'],
  ['2019', '20,343,188', '6,147,516', '30.2%'], ['2020', '20,926,710', '6,643,354', '31.7%'],
];

function chart(no: number, kind: ChartSpec['kind'], values: number[], title = '1인 가구 수', heading = '전국 1인 가구 수 변화'): ChartSpec {
  const isRate = kind === 'line' || kind === 'donut';
  const last = values.at(-1) ?? 0;
  const first = values[0] ?? 0;
  return {
    id: `chart-${no}`,
    no,
    kind,
    title,
    heading,
    unit: isRate ? '%' : '만 가구',
    years: CHART_YEARS,
    values,
    values2: kind === 'combo' ? RATE : undefined,
    ticks: kind === 'combo' ? [0, 250, 500, 750, 1000] : isRate ? RATE_TICKS : COUNT_TICKS,
    ticks2: kind === 'combo' ? [15, 20, 25, 30, 35] : undefined,
    summary: isRate ? `${first}% → ${last}%` : `${first}만 → ${last}만`,
    delta: isRate ? '+4.5%p' : `+${(((last - first) / first) * 100).toFixed(1)}%`,
  };
}

export function getResultView(run: Pick<RunRecord, 'chartCount' | 'table'>): ResultView {
  const main = run.table === 'B' ? COUNT_B : COUNT_A;
  const name = run.table === 'B' ? '장래가구추계' : '인구총조사';
  const rate = chart(2, 'line', RATE, '1인 가구 비율', '전국 1인 가구 비율 변화');
  const base = run.table === 'both'
    ? [chart(1, 'bar', COUNT_A, '인구총조사', '인구총조사 1인 가구 수'), chart(2, 'bar', COUNT_B, '장래가구추계', '장래가구추계 1인 가구 수')]
    : [chart(1, 'bar', main), rate];
  const extras = run.chartCount === 3
    ? [chart(3, 'combo', main, '1인 가구 수 · 비율', '1인 가구 수 · 비율')]
    : [chart(3, 'area', main), chart(4, 'donut', RATE, '1인 가구 비율', '1인 가구 비율'), chart(5, 'bar', main, '1인 가구 수', '1인 가구 수 추가 차트')];
  const count = Math.max(2, run.chartCount);
  const charts = [...base, ...(count > 2 ? extras : [])].slice(0, count);

  if (run.table === 'both') {
    return {
      charts,
      paragraphs: [
        { marker: 1, parts: [{ text: '2020년 1인 가구는 인구총조사 ' }, { text: '664.3만 가구', tone: 'strong' }, { text: ', 장래가구추계 ' }, { text: '647.7만 가구', tone: 'strong' }, { text: '입니다' }] },
        { marker: 2, parts: [{ text: '두 통계표의 차이는 ' }, { text: '16.6만 가구', tone: 'accent' }, { text: '로, 조사 방식이 달라 생긴 차이입니다' }] },
      ],
      summary: [
        { label: '인구총조사', value: '520.3만 → 664.3만' },
        { label: '장래가구추계', value: '512.5만 → 647.7만' },
        { label: '2020년 차이', value: '16.6만' },
        { label: '기준', value: '실제값 · 추계값' },
      ],
      source: '출처 · 통계청 「인구총조사」, 「장래가구추계」',
      plainAnswer: '2020년 1인 가구는 인구총조사 664.3만 가구, 장래가구추계 647.7만 가구입니다. 두 통계표의 차이는 16.6만 가구입니다.',
      previewAnswer: [{ text: '2020년 1인 가구는 인구총조사 664.3만 가구, 장래가구추계 647.7만 가구로 ' }, { text: '16.6만 가구 차이', tone: 'accent' }, { text: '가 납니다.' }],
    };
  }

  const first = main[0];
  const last = main.at(-1) ?? 0;
  const growth = (((last - first) / first) * 100).toFixed(1);
  return {
    charts,
    paragraphs: [
      { marker: 1, parts: [{ text: '전국 1인 가구는 2015년 ' }, { text: `${first}만 가구`, tone: 'strong' }, { text: '에서 2020년 ' }, { text: `${last}만 가구`, tone: 'strong' }, { text: '로 ' }, { text: `${growth}% 늘었습니다`, tone: 'accent' }] },
      { marker: 2, parts: [{ text: '전체 가구에서 차지하는 비율도 27.2%에서 31.7%로 ' }, { text: '4.5%p 높아졌습니다', tone: 'accent' }] },
    ],
    summary: [
      { label: '1인 가구 수', value: `${first}만 → ${last}만` },
      { label: '증가율', value: `+${growth}%` },
      { label: '1인 가구 비율', value: '27.2% → 31.7%' },
      { label: '비율 변화', value: '+4.5%p' },
    ],
    source: `출처 · 통계청 「${name}」 가구원수별 가구`,
    plainAnswer: `전국 1인 가구는 2015년 ${first}만 가구에서 2020년 ${last}만 가구로 ${growth}% 늘었습니다. 전체 가구에서 차지하는 비율도 27.2%에서 31.7%로 4.5%p 높아졌습니다.`,
    previewAnswer: [{ text: `전국 1인 가구는 2015년 ${first}만 가구에서 2020년 ${last}만 가구로 늘어 ` }, { text: `약 ${growth}% 증가`, tone: 'accent' }, { text: '했습니다.' }],
  };
}

export function formatRegion(filters: Filters) {
  const [first, ...rest] = filters.regions;
  if (!first) return '';
  if (rest.length > 0) return `${first} 외 ${rest.length}`;
  // 시군구까지 골랐으면 붙여서 보여줍니다. 예) '부산 해운대구', '경기 수원시 장안구'
  return filters.district !== '전체' ? `${first} ${filters.district}` : first;
}

export function formatTime(filters: Filters) {
  const years = [...filters.years].sort((a, b) => a - b);
  if (years.length === 0) return '';
  if (years.length === 1) return `${years[0]}년`;
  return `${years[0]}~${years.at(-1)}년`;
}

export function composeQuestion(filters: Filters, title?: string) {
  const words = [formatRegion(filters), formatTime(filters), title || filters.target].filter(Boolean);
  return words.length > 0 ? `${words.join(' ')} 통계 보여줘` : '';
}

export function tagsFromFilters(filters: Filters) {
  const tags = [formatRegion(filters), formatTime(filters).replace('년', ''), filters.target].filter(Boolean);
  return tags.length > 0 || !USE_MOCK ? tags : ['전국', '2015~2020', '1인 가구'];
}

/** 입력 문장에 없는 지역·시점·대상 조건을 앞에 붙여 백엔드로 보낼 질문을 만듭니다. */
export function mergeConditions(text: string, filters: Filters) {
  const question = text.trim();
  if (!question) return composeQuestion(filters);
  const flat = question.replace(/\s+/g, '');
  const years = [...filters.years].sort((a, b) => a - b);
  const parts: string[] = [];
  if (years.length > 0 && !/(?:19|20)\d{2}|최근|최신|요즘|작년|올해/.test(question)) {
    parts.push(years.length === 1 ? `${years[0]}년` : `${years[0]}년부터 ${years.at(-1)}년까지`);
  }
  const regions = filters.regions.length === 1 && filters.district !== '전체' ? [`${filters.regions[0]} ${filters.district}`] : filters.regions;
  parts.push(...regions.filter((region) => !flat.includes(region.replace(/\s+/g, ''))));
  if (filters.target && !flat.includes(filters.target.replace(/\s+/g, ''))) parts.push(filters.target);
  return [...parts, question].join(' ');
}

export function chartCountForSuggestion(label: string) {
  if (label.includes('시도별')) return 3;
  if (label.includes('연령대')) return 4;
  if (label.includes('비율')) return 5;
  return 2;
}

type Seed = [string, string[], 'bars' | 'line', RunRecord['seedGroup'], string, boolean?];
const SEEDS: Seed[] = [
  ['2015년과 2020년 전국 1인 가구 수를 비교해줘', ['전국', '2015·2020', '1인 가구'], 'bars', '오늘', '14:32', true],
  ['최근 5년 서울 출생아 수 추이 보여줘', ['서울', '2020~2024', '출생아'], 'line', '오늘', '11:05'],
  ['시도별 65세 이상 인구 비율 알려줘', ['시도별', '2024', '고령'], 'bars', '어제', '17:48'],
  ['부산 청년 인구는 얼마나 줄었어?', ['부산', '2015~2024', '청년'], 'line', '어제', '09:21'],
  ['2023년 혼인 건수와 이혼 건수 비교', ['전국', '2023', '혼인·이혼'], 'bars', '지난 7일', '11.07'],
  ['경기도 다문화 가구 수 변화', ['경기', '2015~2023', '다문화 가구'], 'line', '지난 7일', '11.06'],
  ['전국 합계출산율 10년 추이', ['전국', '2014~2023', '출생아'], 'line', '지난 7일', '11.05'],
  ['대구 고령자 가구 비율 알려줘', ['대구', '2023', '고령자 가구'], 'bars', '지난 7일', '11.05'],
  ['인천 외국인 인구 변화', ['인천', '2015~2023', '외국인'], 'line', '지난 7일', '11.04'],
  ['광주 한부모 가구 수 보여줘', ['광주', '2022', '한부모 가구'], 'bars', '지난 7일', '11.04'],
  ['대전 청년 인구 추이', ['대전', '2015~2023', '청년'], 'line', '지난 7일', '11.03'],
  ['울산 전체 가구 수 변화', ['울산', '2015~2023', '전체 가구'], 'line', '지난 7일', '11.03'],
  ['세종 인구 증가율 알려줘', ['세종', '2015~2023', '전체 인구'], 'bars', '지난 7일', '11.03'],
  ['강원 고령 인구 비율', ['강원', '2023', '고령'], 'bars', '지난 7일', '11.02'],
  ['충북 출생아 수 추이', ['충북', '2014~2023', '출생아'], 'line', '지난 7일', '11.02'],
  ['충남 다문화 가구 비교', ['충남', '2020·2023', '다문화 가구'], 'bars', '지난 7일', '11.02'],
  ['전북 1인 가구 수 변화', ['전북', '2015~2023', '1인 가구'], 'line', '지난 7일', '11.01'],
  ['전남 고령자 가구 현황', ['전남', '2023', '고령자 가구'], 'bars', '지난 7일', '11.01'],
  ['경북 혼인 건수 추이', ['경북', '2014~2023', '혼인'], 'line', '지난 7일', '11.01'],
  ['경남 남녀 인구 비교', ['경남', '2023', '전체 인구'], 'bars', '지난 7일', '10.31'],
  ['제주 외국인 인구 현황', ['제주', '2023', '외국인'], 'bars', '지난 7일', '10.31'],
  ['서울 이혼 건수 변화', ['서울', '2015~2023', '이혼'], 'line', '지난 7일', '10.30'],
  ['부산 1인 가구 비율', ['부산', '2015~2023', '1인 가구'], 'line', '지난 7일', '10.30'],
  ['전국 산모 평균 연령 추이', ['전국', '2014~2023', '산모'], 'line', '지난 7일', '10.29'],
];

export function createSeedRuns(): RunRecord[] {
  return SEEDS.map(([question, tags, thumb, seedGroup, seedTime, favorite], index) => ({
    id: `seed-${index + 1}`,
    question,
    tags,
    thumb,
    seedGroup,
    seedTime,
    favorite: favorite === true,
    status: 'done',
    chartCount: 2,
    table: 'A' as TableChoice,
    needsSelection: false,
  }));
}

export function toCsv(view: ResultView) {
  if (view.tables?.length) {
    const escape = (cell: string) => `"${cell.replace(/"/g, '""')}"`;
    const blocks = view.tables.filter((table) => table.kind === 'view').map((table) => [table.title, table.columns.map(escape).join(','), ...table.rows.map((row) => row.map(escape).join(','))].join('\n'));
    return `\uFEFF${blocks.join('\n\n')}`;
  }
  const header = ['차트', '시점', '값', '단위'];
  const rows = view.charts.flatMap((item) => item.years.map((year, index) => [item.title, year, String(item.values[index]), item.unit]));
  return `﻿${[header, ...rows].map((row) => row.join(',')).join('\n')}`;
}
