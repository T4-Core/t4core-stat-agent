// 4-3. 크게 보기: 나란히 / 한 개씩 / 겹쳐서
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import chevronRight from '../assets/figma/chevron-right.svg';
import closeButton from '../assets/figma/close-button.svg';
import downloadIcon from '../assets/figma/download.svg';
import next from '../assets/figma/next-button.svg';
import prev from '../assets/figma/prev-button.svg';
import { toCsv } from '../data/examples';
import type { ChartSpec, ResultView } from '../data/types';
import { downloadSvgAsPng, downloadText } from './download';
import { EvidenceTable } from './EvidenceTable';
import { downloadPlotAsPng } from './PlotlyChart';
import { StatChart } from './StatChart';

type Mode = 'both' | 'each' | 'overlay';
type Props = { runId: string; view: ResultView; title?: string; onClose: () => void };

const MODES: { id: Mode; label: string }[] = [
  { id: 'both', label: '나란히' },
  { id: 'each', label: '한 개씩' },
  { id: 'overlay', label: '겹쳐서' },
];

function Pager({ page, total, onChange }: { page: number; total: number; onChange: (page: number) => void }) {
  return (
    <div className="pager">
      <button type="button" aria-label="이전 차트" disabled={page === 0} onClick={() => onChange(page - 1)}><img src={prev} alt="" width={30} height={30} /></button>
      <span className="pager-dots" aria-hidden="true">{Array.from({ length: total }, (_, index) => <i key={index} className={index === page ? 'on' : ''} />)}</span>
      <span className="pager-text">{page + 1} / {total}</span>
      <button type="button" aria-label="다음 차트" disabled={page >= total - 1} onClick={() => onChange(page + 1)}><img src={next} alt="" width={30} height={30} /></button>
    </div>
  );
}

function diff(values: number[], index: number) {
  if (index === 0) return '–';
  const value = values[index] - values[index - 1];
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}`;
}

function overlaySpec(charts: ChartSpec[]): ChartSpec {
  const base = charts[0];
  return { ...base, id: 'overlay', kind: 'combo', values2: charts[1]?.unit === '%' ? charts[1].values : [27.2, 27.9, 28.6, 29.3, 30.2, 31.7], ticks: [0, 250, 500, 750, 1000], ticks2: [15, 20, 25, 30, 35] };
}

export function ResultDetailModal({ runId, view, title, onClose }: Props) {
  const [mode, setMode] = useState<Mode>('both');
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState(0);
  const body = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const charts = view.charts;
  const pageCount = charts.length;
  const visible = charts.length > 1 ? [charts[page], charts[(page + 1) % charts.length]] : charts;
  const modes = view.live ? MODES.filter((item) => item.id !== 'overlay') : MODES;
  const firstDetail = view.details?.[0];
  const current = charts[selected] ?? charts[0];

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const savePng = () => {
    const plot = body.current?.querySelector('.js-plotly-plot');
    if (plot instanceof HTMLElement) {
      void downloadPlotAsPng(plot, 'kosis-chart');
      return;
    }
    const svg = body.current?.querySelector('svg.stat-chart');
    if (svg instanceof SVGSVGElement) downloadSvgAsPng(svg, 'kosis-chart.png');
  };

  return (
    <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="detail-modal" role="dialog" aria-modal="true" aria-label="차트 크게 보기">
        <header className="modal-head">
          <div>
            <h2>{view.live ? title : '전국 1인 가구 수와 비율 변화'}</h2>
            <p>{view.live ? view.source : '통계청 「인구총조사」 가구원수별 가구(일반가구) · 수록기간 2015~2020'} · 차트 {charts.length}개</p>
          </div>
          <div className="modal-tools">
            <div className="segment" role="group" aria-label="보기 방식">
              {modes.map((item) => <button type="button" key={item.id} className={mode === item.id ? 'on' : ''} aria-pressed={mode === item.id} onClick={() => setMode(item.id)}>{item.label}</button>)}
            </div>
            <button type="button" className="tool-button" onClick={savePng}><img src={downloadIcon} alt="" width={14} height={14} />PNG</button>
            <button type="button" className="tool-button" onClick={() => downloadText('kosis-data.csv', toCsv(view))}><img src={downloadIcon} alt="" width={14} height={14} />CSV</button>
            <button type="button" className="close-button" ref={closeRef} aria-label="닫기" onClick={onClose}><img src={closeButton} alt="" width={38} height={38} /></button>
          </div>
        </header>

        <div ref={body} className="modal-body">
          {mode === 'both' && (
            <>
              <div className="modal-charts">
                {visible.map((chart) => (
                  <div className="modal-chart-column" key={chart.id}>
                    <article className="modal-chart">
                      <h3><span className="no-badge">{chart.no}</span>{chart.title}<small>단위: {chart.unit}</small></h3>
                      <StatChart chart={chart} width={visible.length === 1 ? 940 : 444} height={314} />
                    </article>
                    <Pager page={page} total={pageCount} onChange={setPage} />
                  </div>
                ))}
              </div>
              {view.live ? (firstDetail && <EvidenceTable table={firstDetail.table} className="modal-evidence" />) : <table className="modal-table">
                <thead><tr><th scope="col">시점</th>{charts[0].years.map((year) => <th scope="col" key={year}>{year}년</th>)}<th scope="col">변화</th></tr></thead>
                <tbody>
                  {visible.map((chart) => (
                    <tr key={chart.id}>
                      <th scope="row"><span className="no-badge small">{chart.no}</span>{chart.title}({chart.unit})</th>
                      {chart.values.map((value, index) => <td key={chart.years[index]}>{value}</td>)}
                      <td className="accent">{chart.delta}</td>
                    </tr>
                  ))}
                </tbody>
              </table>}
              <footer className="modal-foot">
                <span>{view.live ? '아래 표는 답변에 사용한 통계표예요.' : '두 차트의 가로축(연도)을 맞춰 놓았어요. 한 점에 마우스를 올리면 양쪽에 같은 연도가 표시돼요.'}</span>
                <Link to={`/result/${runId}/tables/1`}>KOSIS 원본 통계표 열기<img src={chevronRight} alt="" width={14} height={14} /></Link>
              </footer>
            </>
          )}

          {mode === 'each' && (
            <div className="modal-each">
              <aside>
                <h3>차트 목록</h3>
                {charts.map((chart, index) => (
                  <button type="button" key={chart.id} className={selected === index ? 'thumb-card on' : 'thumb-card'} aria-pressed={selected === index} onClick={() => setSelected(index)}>
                    <span><i className="no-badge small">{chart.no}</i>{chart.title}</span>
                    <span className={`mini-${chart.kind === 'bar' ? 'bars' : 'line'}`} aria-hidden="true">
                      {chart.kind === 'bar' ? chart.values.map((value, i) => <i key={i} style={{ height: `${(value / (view.live ? Math.max(...chart.values, 1) : 800)) * 100}%` }} className={i === 0 || i === chart.values.length - 1 ? 'dark' : ''} />) : (
                        <svg width="150" height="52"><polyline points="4,44 34,39 64,33 94,27 122,20 146,7" fill="none" stroke="#7ba39d" strokeWidth="2" /></svg>
                      )}
                    </span>
                  </button>
                ))}
              </aside>
              <article className="modal-chart large">
                <h3><span className="no-badge">{current.no}</span>{current.title}<small>단위: {current.unit}</small></h3>
                <StatChart chart={current} width={480} height={454} />
                <Pager page={selected} total={charts.length} onChange={setSelected} />
              </article>
              <div className="modal-side">
                {view.live ? (
                  <dl className="side-info">
                    <p>통계표 정보</p>
                    {firstDetail?.meta.map(([key, value]) => <div key={key}><dt>{key}</dt><dd title={value}>{value}</dd></div>)}
                  </dl>
                ) : <>
                <table>
                  <thead><tr><th scope="col">시점</th><th scope="col">{current.unit === '%' ? '비율(%)' : '가구(만)'}</th><th scope="col">전년 대비</th></tr></thead>
                  <tbody>
                    {current.years.map((year, index) => (
                      <tr key={year} className={index === 0 || index === current.years.length - 1 ? 'strong' : ''}>
                        <th scope="row">{year}년</th><td>{current.values[index]}</td><td className="accent">{diff(current.values, index)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <dl className="side-info">
                  <p>통계표 정보</p>
                  <div><dt>작성기관</dt><dd>통계청</dd></div>
                  <div><dt>조사명</dt><dd>인구총조사</dd></div>
                  <div><dt>주기</dt><dd>연간</dd></div>
                </dl>
                </>}
              </div>
            </div>
          )}

          {mode === 'overlay' && (
            <article className="modal-chart overlay">
              <h3>1인 가구 수 · 비율<small>막대: 만 가구 (왼쪽) · 선: % (오른쪽)</small></h3>
              <StatChart chart={overlaySpec(charts)} width={930} height={520} />
            </article>
          )}
        </div>
      </section>
    </div>
  );
}
