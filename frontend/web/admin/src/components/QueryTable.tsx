// 실행 중과 결과 화면에서 함께 쓰는 쿼리 목록
import { useEffect, useRef, useState } from 'react';
import type { RunItem } from '../runner/useQueryRunner';
import { badgeOf, countsOf, formatSeconds, numberOf } from './runView';

function LiveTime({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, []);
  return <>{formatSeconds(Math.max(0, now - since))}</>;
}

function Row({ item, selected, current, onSelect }: { item: RunItem; selected: boolean; current: boolean; onSelect?: (position: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const badge = badgeOf(item);
  const { warnings, errors } = countsOf(item);
  const finished = Boolean(item.result);
  const outOfScope = item.result?.status === 'out_of_scope';

  useEffect(() => {
    if (!current || !ref.current) return;
    // 목록 안에서만 현재 쿼리가 보이도록 움직입니다.
    const list = ref.current.parentElement;
    if (list) list.scrollTop = Math.max(0, ref.current.offsetTop - list.offsetTop - 96);
  }, [current]);

  const cells = (
    <>
      <span>{numberOf(item.position)}</span>
      <span className="adm-queue-question" title={item.question}>{item.question}</span>
      <span><i className={`adm-badge is-${badge.tone}`}>{badge.label}</i></span>
      <span>{finished && !outOfScope ? item.result?.summary.chartCount : '-'}</span>
      <span>{finished && !outOfScope ? warnings : '-'}</span>
      <span>{finished && !outOfScope ? errors : '-'}</span>
      <span>{item.result ? formatSeconds(item.result.activeMs) : item.state === 'running' ? <LiveTime since={item.startedAt} /> : '-'}</span>
    </>
  );
  const className = `adm-queue-row${selected || current ? ' is-current' : ''}`;

  if (onSelect) {
    return <div ref={ref} role="row"><button type="button" className={`${className} is-button`} aria-expanded={selected} onClick={() => onSelect(item.position)}>{cells}</button></div>;
  }
  return <div ref={ref} className={className} role="row">{cells}</div>;
}

type Props = {
  items: RunItem[];
  current?: number;
  selected?: number | null;
  onSelect?: (position: number) => void;
  scroll?: boolean;
};

export function QueryTable({ items, current = -1, selected = null, onSelect, scroll = false }: Props) {
  return (
    <section className="adm-queue" aria-label="쿼리 목록">
      <div className="adm-queue-row is-head"><span>#</span><span>질문</span><span>상태</span><span>차트</span><span>QA</span><span>에러</span><span>시간</span></div>
      <div className={scroll ? 'adm-queue-list is-scroll' : 'adm-queue-list'}>
        {items.map((item) => <Row key={item.position} item={item} current={item.position === current} selected={item.position === selected} onSelect={onSelect} />)}
        {items.length === 0 && <p className="adm-queue-empty">이 모듈에서 문제가 발견된 쿼리가 없습니다.</p>}
      </div>
    </section>
  );
}
