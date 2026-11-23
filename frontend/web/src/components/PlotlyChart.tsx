// 백엔드가 준 Plotly JSON 에 Figma 색상과 글꼴을 입혀 그립니다. 용량이 커서 필요할 때만 불러옵니다.
import { useEffect, useRef, useState } from 'react';
import type { PlotlyFigure } from '../api/types';

const PALETTE = ['#7ba39d', '#3f6661', '#b9ccc8', '#5f8b85', '#dce9e6', '#8a9794'];
const FONT = 'Pretendard Variable, Pretendard, sans-serif';

type Trace = Record<string, unknown> & { type?: string; x?: unknown[]; y?: unknown[]; marker?: Record<string, unknown>; line?: Record<string, unknown> };
type Props = { figure: PlotlyFigure; width: number; height: number; scale?: number; chartType?: string };

function themeTraces(data: Trace[], fontSize: number) {
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

function themeLayout(layout: Record<string, unknown>, width: number, height: number, fontSize: number) {
  const { title: _title, width: _width, height: _height, annotations, xaxis, yaxis, ...rest } = layout;
  const axis = (value: unknown) => ({
    ...(value as object),
    title: undefined,
    gridcolor: '#edf1f0',
    linecolor: '#edf1f0',
    zerolinecolor: '#edf1f0',
    tickfont: { family: FONT, size: fontSize, color: '#55625f' },
    automargin: true,
  });
  const notes = Array.isArray(annotations)
    ? annotations.filter((item) => !String((item as { text?: unknown }).text ?? '').includes('출처'))
    : undefined;
  return {
    ...rest,
    annotations: notes,
    width,
    height,
    autosize: false,
    margin: { l: 8, r: 8, t: 22, b: 8, pad: 2 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: FONT, size: fontSize, color: '#55625f' },
    barcornerradius: 3,
    legend: { orientation: 'h', x: 0, y: 1.12, font: { family: FONT, size: fontSize } },
    xaxis: axis(xaxis),
    yaxis: axis(yaxis),
  };
}

export function PlotlyChart({ figure, width, height, scale = 1, chartType }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

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
        const { data = [], layout = {} } = structuredClone(figure);
        const fontSize = Math.max(8, Math.round(11 * scale));
        await Plotly.newPlot(element, themeTraces(data as Trace[], fontSize), themeLayout(layout, width, height, fontSize), { displayModeBar: false, responsive: false });
      })
      .catch(() => { if (!cancelled) setFailed(true); });

    return () => {
      cancelled = true;
      purge?.();
    };
  }, [figure, height, scale, width]);

  if (failed) return <p className="chart-failed" style={{ width, height }}>차트를 표시하지 못했어요.</p>;
  return <div className="plotly-chart" ref={ref} data-chart-type={chartType} style={{ width, height }} role="img" aria-label="통계 차트" />;
}

export async function downloadPlotAsPng(element: HTMLElement, filename: string) {
  const { default: Plotly } = await import('plotly.js-dist-min');
  await Plotly.downloadImage(element, { format: 'png', filename, scale: 2 });
}
