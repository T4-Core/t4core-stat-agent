// 실행 중과 결과 화면에서 함께 쓰는 쿼리 목록
// 결과 화면에서는 쿼리를 누르면 그 줄 바로 아래에 상세가 펼쳐집니다. (같은 줄을 다시 누르거나 접기를 누르면 닫힘)
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react';
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

type RowProps = { item: RunItem; selected: boolean; current: boolean; onSelect?: (position: number) => void; detail?: ReactNode };

function Row({ item, selected, current, onSelect, detail }: RowProps) {
  const ref = useRef<HTMLDivElement>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  const badge = badgeOf(item);
  const { warnings, errors } = countsOf(item);
  const finished = Boolean(item.result);
  const outOfScope = item.result?.status === 'out_of_scope';
  const open = selected && Boolean(detail);

  useEffect(() => {
    if (!current || !ref.current) return;
    // 목록 안에서만 현재 쿼리가 보이도록 움직입니다.
    const list = ref.current.parentElement;
    if (list) list.scrollTop = Math.max(0, ref.current.offsetTop - list.offsetTop - 96);
  }, [current]);

  useEffect(() => {
    // 펼친 쿼리 줄이 화면 맨 위에 오도록 페이지를 움직입니다.
    const row = ref.current;
    const box = detailRef.current;
    if (!open || !row || !box) return;
    const align = () => row.scrollIntoView({ behavior: 'smooth', block: 'start' });
    // 상세 내용(압축 풀기·차트)은 조금 늦게 그려져서, 처음에는 페이지가 짧아 끝까지 못 올라갈 수 있습니다.
    // 내용이 커지는 동안(최대 2.5초) 다시 맞추고, 사용자가 직접 스크롤하면 바로 멈춥니다.
    const observer = new ResizeObserver(align);
    const events = ['wheel', 'touchstart', 'keydown', 'pointerdown'] as const;
    const stop = () => {
      observer.disconnect();
      for (const name of events) window.removeEventListener(name, stop, true);
    };
    align();
    observer.observe(box);
    for (const name of events) window.addEventListener(name, stop, true);
    const timer = window.setTimeout(stop, 2500);
    return () => {
      window.clearTimeout(timer);
      stop();
    };
  }, [open]);

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
    return (
      <Fragment>
        <div ref={ref} className="adm-queue-item" role="row"><button type="button" className={`${className} is-button`} aria-expanded={selected} onClick={() => onSelect(item.position)}>{cells}</button></div>
        {open && <div ref={detailRef} className="adm-queue-detail">{detail}</div>}
      </Fragment>
    );
  }
  return <div ref={ref} className={className} role="row">{cells}</div>;
}

type Props = {
  items: RunItem[];
  current?: number;
  selected?: number | null;
  onSelect?: (position: number) => void;
  /** 고른 쿼리 줄 바로 아래에 펼칠 상세 */
  renderDetail?: (item: RunItem) => ReactNode;
  scroll?: boolean;
};

export function QueryTable({ items, current = -1, selected = null, onSelect, renderDetail, scroll = false }: Props) {
  return (
    <section className="adm-queue" aria-label="쿼리 목록">
      <div className="adm-queue-row is-head"><span>#</span><span>질문</span><span>상태</span><span>차트</span><span>QA</span><span>에러</span><span>시간</span></div>
      <div className={scroll ? 'adm-queue-list is-scroll' : 'adm-queue-list'}>
        {items.map((item) => {
          const isSelected = item.position === selected;
          return <Row key={item.position} item={item} current={item.position === current} selected={isSelected} onSelect={onSelect} detail={isSelected ? renderDetail?.(item) : undefined} />;
        })}
        {items.length === 0 && <p className="adm-queue-empty">이 모듈에서 문제가 발견된 쿼리가 없습니다.</p>}
      </div>
    </section>
  );
}
