// 4. Result: 차트 한 개씩 / 한번에 보기, 답변, 크게 보기
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import answerIcon from '../assets/figma/answer-icon.svg';
import bulb from '../assets/figma/bulb.svg';
import bubbleTailless from '../assets/figma/chevron-right.svg';
import copyButton from '../assets/figma/copy-button.svg';
import expandButton from '../assets/figma/expand-button.svg';
import moreButton from '../assets/figma/more-button.svg';
import next from '../assets/figma/next-button.svg';
import prev from '../assets/figma/prev-button.svg';
import send from '../assets/figma/send-button-round.svg';
import tableIcon from '../assets/figma/table.svg';
import vizIcon from '../assets/figma/viz-icon.svg';
import { Character } from '../character';
import { Frame, QueryPill } from '../components/Layout';
import { EvidenceTable } from '../components/EvidenceTable';
import { ResultDetailModal } from '../components/ResultDetailModal';
import { StatChart } from '../components/StatChart';
import { chartCountForSuggestion } from '../data/examples';
import type { ChartSpec, ResultView } from '../data/types';
import { useRunView } from '../store/agent';
import { createRun, routeForRun, useRun } from '../store/history';

const SUGGESTIONS = ['시도별로 나눠서 보여줘', '연령대별로는 어때?', '전체 가구 중 비율은?'];

function AnswerBody({ view }: { view: ResultView }) {
  return (
    <div className={view.live ? 'answer-scroll' : 'answer-plain'}>
      <div className="answer-paragraphs">
        {view.paragraphs.map((paragraph, paragraphIndex) => (
          <p key={paragraphIndex}>
            {paragraph.parts.map((part, index) => <span key={index} className={part.tone ?? undefined}>{part.text}</span>)}
            {paragraph.marker !== undefined && <i className="answer-marker">{paragraph.marker}</i>}
          </p>
        ))}
      </div>
      {view.summary.length > 0 && (
        <section className="key-summary">
          <h3><img src={bulb} alt="" width={18} height={18} />핵심 요약</h3>
          {view.summary.map((row, index) => <div key={`${row.label}-${index}`}><span>{row.label}</span><b>{row.value}</b></div>)}
        </section>
      )}
      {((view.caveats?.length ?? 0) > 0 || (view.notices?.length ?? 0) > 0) && (
        <section className="answer-caveats">
          <h3>주의사항</h3>
          <ul>{[...(view.notices ?? []), ...(view.caveats ?? [])].map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
      )}
    </div>
  );
}

function unitLine(chart: ChartSpec) {
  const period = chart.figure ? chart.period : chart.period ?? '2015~2020년';
  return [chart.unit ? `단위: ${chart.unit}` : '', period ? `${period}${period.endsWith('년') ? '' : '년'}` : ''].filter(Boolean).join(' · ');
}

function NoChartPanel({ view }: { view: ResultView }) {
  const table = view.tables?.find((item) => item.kind === 'view') ?? view.tables?.[0];
  return (
    <div className="no-chart">
      <p>이 답변은 차트 없이 표로 정리했어요.</p>
      {table && <EvidenceTable table={table} />}
    </div>
  );
}

type MiniProps = { chart: ChartSpec; width: number; height: number; compact: boolean };

function MiniChartCard({ chart, width, height, compact }: MiniProps) {
  const isCombo = chart.kind === 'combo' && !chart.figure;
  return (
    <article className={compact ? 'mini-chart-card compact' : 'mini-chart-card'}>
      <h3><span className="no-badge">{chart.no}</span>{chart.title}</h3>
      <p>{isCombo ? '단위: 만 가구 · % · 2015~2020년' : unitLine(chart)}</p>
      {isCombo && (
        <div className="combo-legend">
          <span><i className="bar" />1인 가구 수 (만 가구, 왼쪽)</span>
          <span><i className="line" />1인 가구 비율 (%, 오른쪽)</span>
        </div>
      )}
      <StatChart chart={chart} width={width} height={height} scale={compact ? 0.72 : 1} />
      <footer>
        <span>{isCombo ? `${chart.summary} · 27.2% → 31.7%` : chart.summary}</span>
        <em>{isCombo ? `${chart.delta} · +4.5%p` : chart.delta}</em>
      </footer>
    </article>
  );
}

function ViewToggle({ mode, onChange }: { mode: 'one' | 'all'; onChange: (mode: 'one' | 'all') => void }) {
  return (
    <div className="segment result-segment" role="group" aria-label="차트 보기 방식">
      <button type="button" className={mode === 'one' ? 'on' : ''} aria-pressed={mode === 'one'} onClick={() => onChange('one')}>한 개씩</button>
      <button type="button" className={mode === 'all' ? 'on' : ''} aria-pressed={mode === 'all'} onClick={() => onChange('all')}>한번에</button>
    </div>
  );
}

export function ResultPage() {
  const { id } = useParams();
  const run = useRun(id);
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [mode, setMode] = useState<'one' | 'all'>('one');
  const [chartIndex, setChartIndex] = useState(0);
  const [detail, setDetail] = useState(false);
  const [copied, setCopied] = useState(false);
  const [followUp, setFollowUp] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const { view, loading } = useRunView(run);

  useEffect(() => {
    if (params.get('focus') === '1') inputRef.current?.focus();
  }, [params]);

  if (!run) return <Navigate to="/" replace />;
  if (run.status !== 'done') return <Navigate to={routeForRun(run)} replace />;
  if (loading) return <Frame variant="result"><span /></Frame>;
  if (!view) return <Navigate to="/history" replace />;

  const ask = (question: string, chartCount = 2) => {
    const text = question.trim();
    if (!text) return;
    const next = createRun({ question: text, requestQuestion: `${run.requestQuestion ?? run.question} ${text}`, tags: run.tags, chartCount, needsSelection: false });
    navigate(`/generating/${next.id}`);
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    ask(followUp);
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(view.plainAnswer);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  const chart = view.charts[Math.min(chartIndex, view.charts.length - 1)];
  const total = view.charts.length;
  const pillTags = run.tags.slice(0, 3);
  // 시안처럼 왼쪽 열에 1·2, 오른쪽 열에 3·4 차트가 오도록 배치합니다.
  const gridCharts = total >= 4 ? [view.charts[0], view.charts[2], view.charts[1], view.charts[3], ...view.charts.slice(4)] : view.charts;
  const copyLabel = copied ? '복사됨' : '답변 복사';

  return (
    <Frame variant={mode === 'one' ? 'result' : 'wide'}>
      <QueryPill className={mode === 'one' ? 'result-pill' : 'wide-pill'} question={run.question} tags={pillTags} />

      {mode === 'one' ? (
        <>
          <section className="result-card viz-card">
            <header className="card-head">
              <img src={vizIcon} alt="" width={34} height={34} />
              <h2>시각화</h2>
              {total > 0 && <span className="count-chip">{total}개</span>}
              <span className="grow" />
              {total > 1 && <ViewToggle mode={mode} onChange={setMode} />}
              {total > 0 && <button type="button" className="icon-button" aria-label="차트 크게 보기" onClick={() => setDetail(true)}><img src={expandButton} alt="" width={32} height={32} /></button>}
            </header>
            {total > 0 ? <>
            <div className="chart-tabs" role="tablist">
              {view.charts.slice(0, 2).map((item, index) => (
                <button type="button" role="tab" key={item.id} aria-selected={chartIndex === index} className={chartIndex === index ? 'chart-tab on' : 'chart-tab'} onClick={() => setChartIndex(index)}>
                  <span>{item.no}</span>{item.title}
                </button>
              ))}
            </div>
            <h3 className="chart-heading">{chart.heading}</h3>
            <p className="chart-unit">{unitLine(chart)}</p>
            <StatChart chart={chart} width={424} height={275} />
            <div className="pager result-pager">
              <button type="button" aria-label="이전 차트" disabled={chartIndex === 0} onClick={() => setChartIndex(chartIndex - 1)}><img src={prev} alt="" width={30} height={30} /></button>
              <span className="pager-dots" aria-hidden="true">{view.charts.map((item, index) => <i key={item.id} className={index === chartIndex ? 'on' : ''} />)}</span>
              <span className="pager-text">{chartIndex + 1} / {total}</span>
              <button type="button" aria-label="다음 차트" disabled={chartIndex >= total - 1} onClick={() => setChartIndex(chartIndex + 1)}><img src={next} alt="" width={30} height={30} /></button>
            </div>
            </> : <NoChartPanel view={view} />}
            <footer className="card-foot"><span>{view.source}</span><a href={view.sourceUrl ?? 'https://kosis.kr'} target="_blank" rel="noreferrer">KOSIS에서 보기 ›</a></footer>
          </section>

          <Character className="result-sloth" size="L" motion="success" />

          <section className="result-card answer-card">
            <header className="card-head">
              <img src={answerIcon} alt="" width={34} height={34} />
              <h2>답변</h2>
              <span className="grow" />
              <button type="button" className="icon-button" aria-label={copyLabel} title={copyLabel} onClick={copy}><img src={copyButton} alt="" width={32} height={32} /></button>
            </header>
            <AnswerBody view={view} />
            {(!view.live || (view.details?.length ?? 0) > 0) && (
              <Link className="table-link" to={`/result/${run.id}/tables/1`}>
                <img src={tableIcon} alt="" width={16} height={16} />
                <span>사용한 통계표 자세히 보기</span>
                <img src={bubbleTailless} alt="" width={16} height={16} />
              </Link>
            )}
          </section>
        </>
      ) : (
        <>
          <section className="result-card wide-card">
            <header className="card-head">
              <img src={vizIcon} alt="" width={34} height={34} />
              <h2>시각화</h2>
              {total > 0 && <span className="count-chip">{total}개</span>}
              <span className="grow" />
              {total > 1 && <ViewToggle mode={mode} onChange={setMode} />}
            </header>
            <div className={`wide-grid count-${Math.min(total, 5)}`}>
              {gridCharts.map((item) => {
                const tall = total === 3 && item.no === 3;
                const large = total === 2;
                return (
                  <div className={tall ? 'grid-tall' : ''} key={item.id}>
                    <MiniChartCard chart={item} compact={!large && !tall} width={large || tall ? 360 : total > 4 ? 346 : 358} height={large ? 310 : tall ? 310 : 143} />
                  </div>
                );
              })}
            </div>
            <footer className="card-foot"><span>{view.source}</span><a href={view.sourceUrl ?? 'https://kosis.kr'} target="_blank" rel="noreferrer">KOSIS에서 보기 ›</a></footer>
          </section>

          <Character className="wide-sloth" size="S" motion="success" />
          <div className="wide-bubble">
            <p>차트 {total}개를 나란히 놓았어요.</p>
            <p>오른쪽 위 버튼을 누르면 원래 크기로 돌아가요.</p>
          </div>

          <section className="result-card wide-answer">
            <header className="card-head">
              <img src={answerIcon} alt="" width={34} height={34} />
              <h2>답변</h2>
              <span className="grow" />
              <button type="button" className="icon-button" aria-label={copyLabel} title={copyLabel} onClick={copy}><img src={copyButton} alt="" width={32} height={32} /></button>
              <button type="button" className="icon-button" aria-label="차트 크게 보기" onClick={() => setDetail(true)}><img src={moreButton} alt="" width={32} height={32} /></button>
            </header>
            <AnswerBody view={view} />
          </section>
        </>
      )}

      <div className="suggestions">
        {SUGGESTIONS.map((label) => <button type="button" key={label} onClick={() => ask(label, chartCountForSuggestion(label))}>{label}</button>)}
      </div>
      <form className="followup" onSubmit={submit}>
        <input ref={inputRef} value={followUp} placeholder="이어서 물어보세요…" aria-label="이어서 질문" onChange={(event) => setFollowUp(event.target.value)} />
        <button type="submit" aria-label="질문 보내기"><img src={send} alt="" width={44} height={44} /></button>
      </form>

      {detail && <ResultDetailModal runId={run.id} view={view} title={run.question} onClose={() => setDetail(false)} />}
    </Frame>
  );
}
