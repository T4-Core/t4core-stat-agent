// 시안과 같은 모양의 차트를 SVG 로 그립니다.
import { useId } from 'react';
import type { ChartSpec } from '../data/types';
import { PlotlyChart } from './PlotlyChart';

type Props = { chart: ChartSpec; width: number; height: number; scale?: number };

const COLOR = { main: '#7ba39d', soft: '#dce9e6', grid: '#edf1f0', text: '#1e2928', sub: '#8a9794', axis: '#55625f', dark: '#3f6661' };

function Label({ x, y, value, strong }: { x: number; y: number; value: number; strong: boolean }) {
  return (
    <text x={x} y={y} textAnchor="middle" fontSize={strong ? 12.5 : 11} fontWeight={strong ? 600 : 500} fill={strong ? COLOR.text : COLOR.sub}>
      {value}
    </text>
  );
}

function Donut({ chart, width: outerWidth, height: outerHeight, scale = 1 }: Props) {
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
      <circle cx={cx} cy={cy} r={radius} fill="none" stroke={COLOR.soft} strokeWidth={radius * 0.46} />
      <circle cx={cx} cy={cy} r={radius} fill="none" stroke={COLOR.main} strokeWidth={radius * 0.46} strokeDasharray={`${(circumference * value) / 100} ${circumference}`} transform={`rotate(-90 ${cx} ${cy})`} />
      <text x={cx} y={cy + 3} textAnchor="middle" fontSize={15} fontWeight={700} fill={COLOR.text}>{value}%</text>
      <text x={cx} y={cy + 17} textAnchor="middle" fontSize={9} fill={COLOR.sub}>2020년</text>
      <rect x={legendX} y={cy - 34} width={7} height={7} rx={1.5} fill={COLOR.main} />
      <text x={legendX + 14} y={cy - 27} fontSize={10} fill={COLOR.axis}>1인 가구</text>
      <text x={width - 8} y={cy - 27} textAnchor="end" fontSize={10.5} fontWeight={600} fill={COLOR.text}>{value}%</text>
      <rect x={legendX} y={cy - 12} width={7} height={7} rx={1.5} fill={COLOR.soft} />
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
  if (chart.figure) return <PlotlyChart figure={chart.figure} width={outerWidth} height={outerHeight} scale={scale} chartType={chart.chartType} />;
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
  const isEdge = (index: number) => index === 0 || index === lastIndex;
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

      {(chart.kind === 'bar' || chart.kind === 'combo') && chart.values.map((value, index) => {
        const highlighted = chart.kind === 'combo' ? index === lastIndex : isEdge(index);
        return (
          <g key={chart.years[index]}>
            <rect x={x(index) - barWidth / 2} y={y(value)} width={barWidth} height={y(min) - y(value)} rx={3} fill={highlighted ? COLOR.main : COLOR.soft} />
            {chart.kind === 'bar' && <Label x={x(index)} y={y(value) - 7} value={value} strong={isEdge(index)} />}
            {chart.kind === 'combo' && <text x={x(index)} y={y(value) + 14} textAnchor="middle" fontSize={9} fill={highlighted ? '#fff' : COLOR.axis}>{value}</text>}
          </g>
        );
      })}

      {chart.kind === 'area' && (
        <>
          <defs>
            <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor={COLOR.main} stopOpacity="0.55" />
              <stop offset="1" stopColor={COLOR.main} stopOpacity="0.05" />
            </linearGradient>
          </defs>
          <polygon points={`${x(0)},${y(min)} ${linePoints(chart.values, y)} ${x(lastIndex)},${y(min)}`} fill={`url(#${gradientId})`} />
        </>
      )}

      {(chart.kind === 'line' || chart.kind === 'area') && (
        <>
          <polyline points={linePoints(chart.values, y)} fill="none" stroke={COLOR.main} strokeWidth={2} />
          {chart.values.map((value, index) => (
            <g key={chart.years[index]}>
              <circle cx={x(index)} cy={y(value)} r={isEdge(index) ? 5 : 3.2} fill={isEdge(index) ? COLOR.main : '#fff'} stroke={COLOR.main} strokeWidth={1.6} />
              <Label x={x(index)} y={y(value) - 10} value={value} strong={isEdge(index)} />
            </g>
          ))}
        </>
      )}

      {chart.kind === 'combo' && chart.values2 && (
        <>
          <polyline points={linePoints(chart.values2, y2)} fill="none" stroke={COLOR.dark} strokeWidth={2} />
          {chart.values2.map((value, index) => (
            <g key={chart.years[index]}>
              <circle cx={x(index)} cy={y2(value)} r={isEdge(index) ? 4.5 : 3} fill={COLOR.dark} />
              <text x={x(index)} y={y2(value) - 8} textAnchor="middle" fontSize={11} fontWeight={600} fill={COLOR.dark}>{value}%</text>
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
