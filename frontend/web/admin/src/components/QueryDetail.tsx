// 쿼리를 누르면 목록 아래에 펼쳐지는 상세 (Figma 05-1)
import { useEffect, useRef, useState } from 'react';
import type { ModuleKey } from '../adapters/issues';
import { moduleStyle } from '../adapters/moduleColors';
import type { StepData, StepState } from '../adapters/steps';
import type { RunItem } from '../runner/useQueryRunner';
import { PipelineDashboard } from './PipelineDashboard';
import { badgeOf, formatSeconds, numberOf } from './runView';

const TABS = [['summary', '요약'], ['input', '입력'], ['output', '출력'], ['raw', '원본 JSON']] as const;
type Tab = (typeof TABS)[number][0];

const STATE_BADGE: Record<StepState, { label: string; tone: string }> = {
  ok: { label: '성공', tone: 'ok' },
  warn: { label: '경고', tone: 'warn' },
  error: { label: '오류', tone: 'error' },
  skipped: { label: '건너뜀', tone: 'muted' },
  unknown: { label: '확인 불가', tone: 'muted' },
};

function firstProblem(steps: StepData[]): ModuleKey {
  return (steps.find((step) => step.state === 'error') ?? steps.find((step) => step.state === 'warn') ?? steps[0]).key;
}

function StepPanel({ step }: { step: StepData }) {
  const [tab, setTab] = useState<Tab>('summary');
  const badge = STATE_BADGE[step.state];
  const json = tab === 'input' ? step.input : tab === 'raw' ? step.raw : step.output;

  return (
    <div className="adm-step-detail">
      <header>
        <h3 className="adm-mod" style={moduleStyle(step.key)}>{step.label}</h3>
        <span className={`adm-badge is-${badge.tone}`}>{badge.label}</span>
        <span className="adm-grow" />
        <div className="adm-tabs" role="tablist" aria-label="단계 내용">
          {TABS.map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? 'is-on' : ''} onClick={() => setTab(key)}>{label}</button>)}
        </div>
      </header>
      {tab === 'summary' ? (
        <div className="adm-step-scroll">
          {step.issues.map((issue) => (
            <div key={[issue.point, issue.kind, issue.pattern, issue.message].join('|')} className={`adm-message is-${issue.severity}`}>
              <span className="adm-message-label">{issue.source === 'qa' ? 'QA 메시지' : '모듈 메시지'}</span>
              <b>{issue.point}{issue.kind ? ` · ${issue.kind}` : ''} · {issue.count}건</b>
              <p>{issue.message}</p>
              {issue.pattern && <code>{issue.pattern}</code>}
            </div>
          ))}
          {step.summary.length > 0 ? (
            <dl className="adm-step-summary">
              {step.summary.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
            </dl>
          ) : <p className="adm-muted">{step.state === 'skipped' ? '이 단계는 실행되지 않았습니다.' : '이 실행에는 이 단계의 상세 내용이 저장되어 있지 않습니다.'}</p>}
          {step.output && <>
            <h4>출력 미리보기</h4>
            <pre className="adm-json is-short" tabIndex={0}>{step.output}</pre>
          </>}
        </div>
      ) : (
        <pre className="adm-json" tabIndex={0}>{json || '표시할 내용이 없습니다.'}</pre>
      )}
    </div>
  );
}

type Props = { item: RunItem; onClose: () => void; rerunMode?: 'run' | 'draft'; onRerun: (question: string) => void };

export function QueryDetail({ item, onClose, rerunMode = 'run', onRerun }: Props) {
  const ref = useRef<HTMLElement>(null);
  const result = item.result;
  const [viewIndex, setViewIndex] = useState(0);
  const view = result?.views[viewIndex];
  const [picked, setPicked] = useState<ModuleKey | null>(null);
  const stepKey = picked ?? (view ? firstProblem(view.steps) : null);
  const step = view?.steps.find((entry) => entry.key === stepKey);
  const badge = badgeOf(item);

  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [item.position]);

  const rerun = () => {
    // 저장된 결과에서는 입력칸에 넣기만 합니다.
    if (rerunMode === 'draft') onRerun(item.question);
    else if (window.confirm(`이 쿼리를 다시 실행할까요?\n예상 HCX 호출은 3~5회이고, 현재 결과 화면은 닫힙니다. 지금 결과는 팀 리포트에 남아 있습니다.`)) onRerun(item.question);
  };

  return (
    <section ref={ref} className="adm-detail" aria-label={`${numberOf(item.position)}번 쿼리 상세`}>
      <header className="adm-detail-head">
        <button type="button" className="adm-button is-outline" onClick={onClose}>접기 ⌃</button>
        <span className="adm-detail-no">{numberOf(item.position)}</span>
        <h2 title={item.question}>{item.question}</h2>
        <span className={`adm-badge is-${badge.tone}`}>{badge.label}</span>
        <span className="adm-grow" />
        {result && <span className="adm-detail-time">{formatSeconds(result.activeMs)}</span>}
        <button type="button" className="adm-button is-outline" onClick={rerun}>{rerunMode === 'draft' ? '다시 테스트' : '다시 실행'}</button>
      </header>

      {result && !result.gz && result.views.length > 1 && (
        <div className="adm-tabs is-views" role="tablist" aria-label="비교한 통계표">
          {result.views.map((entry, index) => <button key={entry.label} type="button" role="tab" aria-selected={viewIndex === index} className={viewIndex === index ? 'is-on' : ''} onClick={() => { setViewIndex(index); setPicked(null); }}>{entry.label}</button>)}
        </div>
      )}

      {!result?.gz && view?.notice && <p className="adm-notice" role="status">{view.notice}</p>}

      {result?.gz ? <PipelineDashboard encoded={result.gz} labels={result.labels} /> : !view ? (
        <div className="adm-message is-error">
          <span className="adm-message-label">백엔드 오류</span>
          <p>{result?.message ?? (item.state === 'skipped' ? '실행하지 않은 쿼리입니다.' : '결과가 없습니다.')}</p>
          {result && <small>백엔드가 실패한 모듈을 알려주지 않아 모듈별 통계에는 포함되지 않습니다.</small>}
        </div>
      ) : (
        <>
        {/* 이전 형식 기록도 결론을 먼저 보여줍니다. */}
        <section className="adm-final" aria-label="최종 결과">
          <h3>최종 결과</h3>
          <div className="adm-final-screen">
            <b>답변</b>
            <p>{view.answer || '답변이 없습니다.'}</p>
            {view.caveats.length > 0 && (
              <div className="adm-final-caveat">
                <b>주의사항</b>
                <ul>{view.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}</ul>
              </div>
            )}
          </div>
          {view.qaMessage && (
            <div className="adm-message is-warning">
              <span className="adm-message-label">QA 메시지</span>
              <p>{view.qaMessage}</p>
            </div>
          )}
        </section>
        <div className="adm-detail-body">
          <nav className="adm-timeline" aria-label="중간 단계">
            <h3>중간 단계</h3>
            {view.steps.map((entry) => {
              const stateBadge = STATE_BADGE[entry.state];
              return (
                <button key={entry.key} type="button" className={entry.key === stepKey ? 'is-on' : ''} aria-current={entry.key === stepKey ? 'step' : undefined} onClick={() => setPicked(entry.key)}>
                  <span className="adm-mod" style={moduleStyle(entry.key)}>{entry.label}</span>
                  <small><i className={`adm-badge is-${stateBadge.tone}`}>{stateBadge.label}</i><em>{entry.time || (entry.state === 'skipped' ? '건너뜀' : '')}</em></small>
                </button>
              );
            })}
            <p className="adm-muted">모듈 2~QA의 시간은 백엔드가 합쳐서만 제공합니다.</p>
          </nav>
          {step && <StepPanel key={`${viewIndex}-${step.key}`} step={step} />}
        </div>
        </>
      )}
    </section>
  );
}
