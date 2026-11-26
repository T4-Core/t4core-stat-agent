// 백엔드가 준 Plotly JSON 에 화면 색상과 글꼴을 입혀 그립니다. 용량이 커서 필요할 때만 불러옵니다.
// 사용자 화면은 담백하게 그립니다: 모듈 5가 넣은 화살표·출처 주석은 빼고, 항목 색은 chartColors 규칙을 따릅니다.
import { useEffect, useMemo, useRef, useState } from 'react';
import type { PlotlyFigure } from '../api/types';
import { paintFigure, type ChartPaint } from './chartColors';

const PALETTE = ['#7ba39d', '#3f6661', '#b9ccc8', '#5f8b85', '#dce9e6', '#8a9794'];
const FONT = 'Pretendard Variable, Pretendard, sans-serif';
// 덤벨의 두 점을 잇는 선처럼 색으로 구분할 필요가 없는 보조 선
const HELPER_COLOR = '#d3dbd9';

type Trace = Record<string, unknown> & { type?: string; x?: unknown[]; y?: unknown[]; marker?: Record<string, unknown>; line?: Record<string, unknown>; fill?: unknown };
type Props = {
  figure: PlotlyFigure;
  width: number;
  height: number;
  scale?: number;
  chartType?: string;
  /** 차트 번호 색과 재료 차트 색 */
  paint?: ChartPaint;
  /** 항목이 여러 개일 때 Plotly 범례를 그림 안에 넣을지 (화면에서 범례를 따로 그리면 false) */
  plotlyLegend?: boolean;
  /** true 면 모듈 5가 만든 모양 그대로 (화살표 주석 포함). 관리자 콘솔의 모듈 5 점검용 */
  original?: boolean;
};

function rgba(hex: string, alpha: number) {
  const value = Number.parseInt(hex.slice(1), 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

/** 모듈 5가 만든 모양에 가까운 예전 색 입히기 (관리자 점검용) */
function originalTraces(data: Trace[], fontSize: number) {
  const singleBar = data.length === 1 && data[0].type === 'bar';
  return data.map((trace, index) => {
    const color = PALETTE[index % PALETTE.length];
    const next: Trace = { ...trace, textfont: { family: FONT, size: fontSize, color: '#1e2928' } };
    if (trace.type === 'bar') {
      const count = (trace.x ?? trace.y ?? []).length;
      const colors = Array.from({ length: count }, (_, point) => (point === 0 || point === count - 1 ? PALETTE[0] : PALETTE[4]));
      next.marker = { ...trace.marker, color: singleBar ? colors : color, line: { width: 0 } };
    } else if (trace.type === 'scatter' || trace.type === 'scattergl') {
      next.line = { ...trace.line, color, width: 2 };
      next.marker = { ...trace.marker, color, line: { width: 0 } };
    } else if (trace.type === 'pie' || trace.type === 'treemap') {
      next.marker = { ...trace.marker, colors: PALETTE };
    }
    return next;
  });
}

/** 담백한 색 입히기: 항목마다 한 색, 강조 없음. 범례에서 숨긴 보조 선(덤벨의 잇는 선 등)은 연한 회색 그대로 둡니다. */
function plainTraces(figure: PlotlyFigure, paint: ChartPaint | undefined, fontSize: number) {
  const data = (figure.data ?? []) as Trace[];
  const { colors, slice, indices } = paintFigure(figure, paint);
  return data.map((trace, traceIndex) => {
    const themed: Trace = { ...trace, textfont: { family: FONT, size: fontSize, color: '#1e2928' } };
    if (slice) {
      themed.marker = { ...trace.marker, colors, line: { color: '#fff', width: 1 } };
      return themed;
    }
    const type = String(trace.type ?? 'scatter');
    const at = indices.indexOf(traceIndex);
    if (at < 0) {
      if (trace.line) themed.line = { ...trace.line, color: HELPER_COLOR };
      return themed;
    }
    const color = colors[at] ?? colors[0];
    if (type === 'bar' || type === 'histogram' || type === 'funnel' || type === 'waterfall') {
      themed.marker = { ...trace.marker, color, line: { width: 0 } };
    } else {
      themed.line = { ...trace.line, color, width: 2 };
      themed.marker = { ...trace.marker, color, line: { width: 0 } };
      if (trace.fill && trace.fill !== 'none') themed.fillcolor = rgba(color, 0.15);
    }
    return themed;
  });
}

function axis(value: unknown, fontSize: number) {
  return {
    ...(value as object),
    title: undefined,
    gridcolor: '#edf1f0',
    linecolor: '#edf1f0',
    zerolinecolor: '#edf1f0',
    tickfont: { family: FONT, size: fontSize, color: '#55625f' },
    automargin: true,
  };
}

function themeLayout(layout: Record<string, unknown>, width: number, height: number, fontSize: number, original: boolean, legend: boolean, polar: boolean) {
  const { title: _title, width: _width, height: _height, annotations, xaxis, yaxis, showlegend: _showlegend, legend: _legend, ...rest } = layout;
  // 출처 글씨는 화면 아래에 따로 있으니 뺍니다.
  // 담백하게: 모듈 5의 화살표 주석(최대·최소·증감 표시)도 뺍니다. 화살표 없는 글씨(도넛 가운데 합계 등)는 남깁니다.
  const notes = (Array.isArray(annotations) ? annotations : []).filter((item) => {
    const note = item as { text?: unknown; showarrow?: unknown };
    if (String(note.text ?? '').includes('출처')) return false;
    return original || note.showarrow === false;
  });
  return {
    ...rest,
    annotations: notes,
    width,
    height,
    autosize: false,
    // 방사형(레이더) 차트는 바깥 항목 이름이 잘리지 않도록 여백을 더 둡니다.
    margin: polar ? { l: 44, r: 44, t: 30, b: 26, pad: 2 } : { l: 8, r: 8, t: 22, b: 8, pad: 2 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: FONT, size: fontSize, color: '#55625f' },
    barcornerradius: 3,
    showlegend: legend,
    legend: original
      ? { orientation: 'h', x: 0, y: 1.12, font: { family: FONT, size: fontSize } }
      : { orientation: 'v', x: 1.02, xanchor: 'left', y: 1, yanchor: 'top', font: { family: FONT, size: fontSize } },
    xaxis: axis(xaxis, fontSize),
    yaxis: axis(yaxis, fontSize),
  };
}

export function PlotlyChart({ figure, width, height, scale = 1, chartType, paint, plotlyLegend = true, original = false }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const paintKey = useMemo(() => JSON.stringify(paint ?? {}), [paint]);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    let cancelled = false;
    let purge: (() => void) | undefined;
    setFailed(false);

    import('plotly.js-dist-min')
      .then(async ({ default: Plotly }) => {
        if (cancelled) return;
        purge = () => Plotly.purge(element);
        const copy = structuredClone(figure);
        const { layout = {} } = copy;
        const fontSize = Math.max(8, Math.round(11 * scale));
        const legendItems = paintFigure(copy, paint).legend.length;
        const showLegend = original ? (layout.showlegend as boolean | undefined) ?? legendItems > 0 : plotlyLegend && legendItems > 0;
        const traces = original ? originalTraces((copy.data ?? []) as Trace[], fontSize) : plainTraces(copy, paint, fontSize);
        const polar = ((copy.data ?? []) as Trace[]).some((trace) => String(trace.type ?? '').includes('polar'));
        await Plotly.newPlot(element, traces, themeLayout(layout, width, height, fontSize, original, showLegend, polar), { displayModeBar: false, responsive: false });
      })
      .catch(() => { if (!cancelled) setFailed(true); });

    return () => {
      cancelled = true;
      purge?.();
    };
    // paint 는 내용(paintKey)이 바뀔 때만 다시 그립니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [figure, height, scale, width, paintKey, plotlyLegend, original]);

  if (failed) return <p className="chart-failed" style={{ width, height }}>차트를 표시하지 못했어요.</p>;
  return <div className="plotly-chart" ref={ref} data-chart-type={chartType} style={{ width, height }} role="img" aria-label="통계 차트" />;
}

export async function downloadPlotAsPng(element: HTMLElement, filename: string) {
  const { default: Plotly } = await import('plotly.js-dist-min');
  await Plotly.downloadImage(element, { format: 'png', filename, scale: 2 });
}
