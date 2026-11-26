// 시안과 같은 모양의 차트를 SVG 로 그립니다. 백엔드 그림(Plotly)이 있으면 그 그림에 범례를 붙여 그립니다.
import { useId, useMemo } from 'react';
import type { PlotlyFigure } from '../api/types';
import type { ChartSpec } from '../data/types';
import { paintFigure, SINGLE_COLOR, tint, type ChartPaint } from './chartColors';
import { PlotlyChart } from './PlotlyChart';
import './chartLegend.css';

type Props = { chart: ChartSpec; width: number; height: number; scale?: number };

const COLOR = { main: SINGLE_COLOR, soft: '#dce9e6', grid: '#edf1f0', text: '#1e2928', sub: '#8a9794', axis: '#55625f', dark: '#3f6661' };

type FigureProps = { figure: PlotlyFigure; width: number; height: number; scale?: number; chartType?: string; paint?: ChartPaint };

const LEGEND_FONT = '"Pretendard Variable", Pretendard, sans-serif';
let measureContext: CanvasRenderingContext2D | null | undefined;

/**
 * 범례 칸 너비 = 가장 긴 항목 이름에 딱 맞게. (예전처럼 너비를 크게 고정하면 오른쪽이 비어 차트가 왼쪽으로 쏠려 보입니다)
 * 너무 긴 이름은 차트 너비의 32%(최대 170px)에서 말줄임합니다.
 */
function legendWidthFor(names: string[], fontSize: number, width: number, height: number) {
  measureContext ??= document.createElement('canvas').getContext('2d');
  let text = Math.max(...names.map((name) => name.length)) * fontSize;
  if (measureContext) {
    measureContext.font = `500 ${fontSize}px ${LEGEND_FONT}`;
    text = Math.max(...names.map((name) => measureContext!.measureText(name).width));
  }
  const swatch = 14 + 6;
  // 항목이 많아 범례가 스크롤되면 스크롤 막대 자리도 둡니다.
  const scrollbar = names.length * (fontSize * 1.3 + 6) > height ? 10 : 0;
  return Math.ceil(Math.min(Math.max(text + swatch + scrollbar + 4, 48), Math.min(170, width * 0.32)));
}

/** 항목이 여러 개인 그림은 오른쪽에 범례(색 + 항목 이름)를 붙입니다. 항목이 많으면 범례만 스크롤됩니다. */
export function FigureChart({ figure, width, height, scale = 1, chartType, paint }: FigureProps) {
  const legend = useMemo(() => paintFigure(figure, paint).legend, [figure, paint]);
  const fontSize = Math.max(9, Math.round(11.5 * scale));
  const legendWidth = useMemo(() => (legend.length === 0 ? 0 : legendWidthFor(legend.map((item) => item.name), fontSize, width, height)), [fontSize, height, legend, width]);
  if (legend.length === 0) return <PlotlyChart figure={figure} width={width} height={height} scale={scale} chartType={chartType} paint={paint} plotlyLegend={false} />;
  const gap = 12;
  return (
    <div className="figure-chart" style={{ width, height }}>
      <PlotlyChart figure={figure} width={width - legendWidth - gap} height={height} scale={scale} chartType={chartType} paint={paint} plotlyLegend={false} />
      <ul className="chart-legend" aria-label="범례" style={{ width: legendWidth, maxHeight: height, fontSize }}>
        {legend.map((item, index) => (
          <li key={`${item.name}-${index}`} title={item.name}>
            <i className={`legend-swatch ${item.shape}`} style={{ background: item.color }} aria-hidden="true" />
            <span>{item.name}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// 값 글씨는 모두 같은 모양입니다. (처음·마지막 값만 진하게 하던 강조는 뺐습니다)
function Label({ x, y, value }: { x: number; y: number; value: number }) {
  return (
    <text x={x} y={y} textAnchor="middle" fontSize={11} fontWeight={500} fill={COLOR.axis}>
      {value}
    </text>
  );
}

function Donut({ chart, width: outerWidth, height: outerHeight, scale = 1 }: Props) {
  const main = chart.color ?? COLOR.main;
  const soft = chart.color ? tint(chart.color, 0.75) : COLOR.soft;
  const width = outerWidth / scale;
  const height = outerHeight / scale;
  const value = chart.values.at(-1) ?? 0;
  const radius = Math.min(height * 0.32, 52);
  const circumference = 2 * Math.PI * radius;
  const cx = width * 0.29;
  const cy = height / 2;
  const legendX = width * 0.55;
  return (
    <svg className="stat-chart" width={outerWidth} height={outerHeight} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${chart.title} ${value}%`}>
      <circle cx={cx} cy={cy} r={radius} fill="none" stroke={soft} strokeWidth={radius * 0.46} />
      <circle cx={cx} cy={cy} r={radius} fill="none" stroke={main} strokeWidth={radius * 0.46} strokeDasharray={`${(circumference * value) / 100} ${circumference}`} transform={`rotate(-90 ${cx} ${cy})`} />
      <text x={cx} y={cy + 3} textAnchor="middle" fontSize={15} fontWeight={700} fill={COLOR.text}>{value}%</text>
      <text x={cx} y={cy + 17} textAnchor="middle" fontSize={9} fill={COLOR.sub}>2020년</text>
      <rect x={legendX} y={cy - 34} width={7} height={7} rx={1.5} fill={main} />
      <text x={legendX + 14} y={cy - 27} fontSize={10} fill={COLOR.axis}>1인 가구</text>
      <text x={width - 8} y={cy - 27} textAnchor="end" fontSize={10.5} fontWeight={600} fill={COLOR.text}>{value}%</text>
      <rect x={legendX} y={cy - 12} width={7} height={7} rx={1.5} fill={soft} />
      <text x={legendX + 14} y={cy - 5} fontSize={10} fill={COLOR.axis}>2인 이상 가구</text>
      <text x={width - 8} y={cy - 5} textAnchor="end" fontSize={10.5} fontWeight={600} fill={COLOR.text}>{(100 - value).toFixed(1)}%</text>
      <line x1={legendX} x2={width - 8} y1={cy + 8} y2={cy + 8} stroke={COLOR.grid} />
      <text x={legendX} y={cy + 24} fontSize={9.5} fill={COLOR.sub}>2015년 대비</text>
      <text x={legendX} y={cy + 39} fontSize={10.5} fill={COLOR.axis}>27.2% → 31.7%</text>
      <text x={width - 8} y={cy + 39} textAnchor="end" fontSize={10.5} fontWeight={600} fill={COLOR.dark}>+4.5%p</text>
    </svg>
  );
}

export function StatChart({ chart, width: outerWidth, height: outerHeight, scale = 1 }: Props) {
  const gradientId = useId();
  if (chart.figure) {
    return <FigureChart figure={chart.figure} width={outerWidth} height={outerHeight} scale={scale} chartType={chart.chartType} paint={{ color: chart.color, sourceColors: chart.sourceColors, traceColors: chart.traceColors }} />;
  }
  if (chart.kind === 'donut') return <Donut chart={chart} width={outerWidth} height={outerHeight} scale={scale} />;
  const width = outerWidth / scale;
  const height = outerHeight / scale;

  const left = Math.max(36, width * 0.104);
  const right = chart.kind === 'combo' ? 34 : Math.max(4, width * 0.0094);
  const top = Math.max(18, height * 0.096);
  const bottom = Math.max(26, height * 0.103);
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const min = chart.ticks[0];
  const max = chart.ticks.at(-1) ?? 1;
  const y = (value: number) => top + plotHeight * (1 - (value - min) / (max - min));
  const band = plotWidth / chart.years.length;
  const x = (index: number) => left + band * (index + 0.5);
  const barWidth = band * 0.55;
  const lastIndex = chart.values.length - 1;
  // 차트 색: 여러 차트면 번호 색을 쓰고, 콤보 차트는 막대·선이 각자 재료 차트 색을 씁니다.
  const main = chart.color ?? COLOR.main;
  const barColor = chart.sourceColors?.[0] ?? main;
  const lineColor = chart.sourceColors?.[1] ?? COLOR.dark;
  const linePoints = (values: number[], map: (value: number) => number) => values.map((value, index) => `${x(index)},${map(value)}`).join(' ');
  const min2 = chart.ticks2?.[0] ?? 0;
  const max2 = chart.ticks2?.at(-1) ?? 1;
  const y2 = (value: number) => top + plotHeight * (1 - (value - min2) / (max2 - min2));

  return (
    <svg className="stat-chart" width={outerWidth} height={outerHeight} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${chart.title}: ${chart.summary}`}>
      {chart.ticks.map((tick) => (
        <g key={tick}>
          <line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} stroke={COLOR.grid} />
          <text x={left - 8} y={y(tick) + 4} textAnchor="end" fontSize={11} fontWeight={500} fill={COLOR.sub}>{tick.toLocaleString('ko-KR')}</text>
        </g>
      ))}
      {chart.ticks2?.map((tick) => (
        <text key={tick} x={width - right + 8} y={y2(tick) + 4} fontSize={11} fontWeight={500} fill={COLOR.sub}>{tick}</text>
      ))}

      {(chart.kind === 'bar' || chart.kind === 'combo') && chart.values.map((value, index) => (
        <g key={chart.years[index]}>
          <rect x={x(index) - barWidth / 2} y={y(value)} width={barWidth} height={y(min) - y(value)} rx={3} fill={chart.kind === 'combo' ? barColor : main} />
          {chart.kind === 'bar' && <Label x={x(index)} y={y(value) - 7} value={value} />}
          {chart.kind === 'combo' && <text x={x(index)} y={y(value) + 14} textAnchor="middle" fontSize={9} fill="#fff">{value}</text>}
        </g>
      ))}

      {chart.kind === 'area' && (
        <>
          <defs>
            <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor={main} stopOpacity="0.55" />
              <stop offset="1" stopColor={main} stopOpacity="0.05" />
            </linearGradient>
          </defs>
          <polygon points={`${x(0)},${y(min)} ${linePoints(chart.values, y)} ${x(lastIndex)},${y(min)}`} fill={`url(#${gradientId})`} />
        </>
      )}

      {(chart.kind === 'line' || chart.kind === 'area') && (
        <>
          <polyline points={linePoints(chart.values, y)} fill="none" stroke={main} strokeWidth={2} />
          {chart.values.map((value, index) => (
            <g key={chart.years[index]}>
              <circle cx={x(index)} cy={y(value)} r={3.2} fill="#fff" stroke={main} strokeWidth={1.6} />
              <Label x={x(index)} y={y(value) - 10} value={value} />
            </g>
          ))}
        </>
      )}

      {chart.kind === 'combo' && chart.values2 && (
        <>
          <polyline points={linePoints(chart.values2, y2)} fill="none" stroke={lineColor} strokeWidth={2} />
          {chart.values2.map((value, index) => (
            <g key={chart.years[index]}>
              <circle cx={x(index)} cy={y2(value)} r={3} fill={lineColor} />
              <text x={x(index)} y={y2(value) - 8} textAnchor="middle" fontSize={11} fontWeight={600} fill={lineColor}>{value}%</text>
            </g>
          ))}
        </>
      )}

      {chart.years.map((year, index) => (
        <text key={year} x={x(index)} y={height - 8} textAnchor="middle" fontSize={11.5} fontWeight={500} fill={COLOR.axis}>{year}</text>
      ))}
    </svg>
  );
}
