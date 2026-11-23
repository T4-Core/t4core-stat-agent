// 왼쪽 모듈 목록과 오른쪽 문제 목록. 같은 종류의 문제는 한 줄로 묶어 한 번에 해결 체크합니다.
import { useState } from 'react';
import { formatWhen, type ModuleStat, type ReportGroup } from '../adapters/report';
import type { ModuleKey } from '../adapters/issues';
import { moduleStyle } from '../adapters/moduleColors';

type View = 'all' | 'open' | 'resolved';
const VIEWS: [View, string][] = [['all', '전체'], ['open', '미해결'], ['resolved', '해결']];

function IssueRowItem({ group, saving, onToggle }: { group: ReportGroup; saving: boolean; onToggle: (group: ReportGroup) => void }) {
  const [open, setOpen] = useState(false);
  const latest = group.queries[0];
  const { owners } = group;
  const others = group.queries.length - 1;

  return (
    <li className={group.isResolved ? 'is-resolved' : ''}>
      <div className="adm-issue-row">
        <label className="adm-check">
          <input type="checkbox" checked={group.isResolved} disabled={saving} aria-label={`${group.message} 해결 체크`} onChange={() => onToggle(group)} />
          <span aria-hidden="true" />
        </label>
        <span className={`adm-badge is-${group.severity === 'error' ? 'error' : 'warn'}`}>{group.severity === 'error' ? '오류' : '경고'}</span>
        <button type="button" className="adm-issue-main" aria-expanded={open} onClick={() => setOpen(!open)}>
          <span className="adm-issue-message">
            {group.message}
            {group.reoccurred && <em>재발생</em>}
            <small>{group.count.toLocaleString()}건</small>
          </span>
          <span className="adm-issue-query">“ {latest.query} ”{others > 0 ? ` 외 ${others}개 쿼리` : ''}</span>
        </button>
        <span className="adm-issue-cell" title={owners.join(', ')}>{owners[0]}{owners.length > 1 ? ` 외 ${owners.length - 1}` : ''}</span>
        <span className="adm-issue-cell is-time">{formatWhen(latest.createdAt)}</span>
        <span className="adm-issue-cell is-resolver">{group.isResolved ? group.resolved_by_login ?? '-' : '-'}</span>
      </div>
      {open && (
        <div className="adm-issue-more">
          <dl>
            <div><dt>검사 지점</dt><dd>{group.point || '-'}{group.kind ? ` · ${group.kind}` : ''}</dd></div>
            {group.path_pattern && <div><dt>위치</dt><dd>{group.path_pattern}</dd></div>}
            {group.reoccurred && <div><dt>재발생</dt><dd>{group.resolved_by_login ?? '팀원'}님이 해결 체크한 뒤 실행 {group.runs_after_resolved}회에서 다시 나왔습니다.</dd></div>}
          </dl>
          <ul>
            {group.queries.slice(0, 30).map((item) => (
              <li key={item.runId}>
                <span>“ {item.query} ”</span>
                <small>{item.owner} · {formatWhen(item.createdAt)} · {item.occurrences}건{item.runCount > 1 ? ` · ${item.runCount}회 실행` : ''}</small>
              </li>
            ))}
          </ul>
          {group.queries.length > 30 && <p>최근 30개 쿼리만 표시합니다.</p>}
        </div>
      )}
    </li>
  );
}

type Props = {
  modules: ModuleStat[];
  groups: ReportGroup[];
  selected: ModuleKey | null;
  saving: Set<string>;
  onSelect: (key: ModuleKey) => void;
  onToggle: (group: ReportGroup) => void;
};

export function IssueBrowser({ modules, groups, selected, saving, onSelect, onToggle }: Props) {
  const [view, setView] = useState<View>('all');
  const current = modules.find((item) => item.key === selected) ?? modules[0];
  const list = groups
    .filter((group) => group.module === current?.key)
    .filter((group) => (view === 'all' ? true : view === 'open' ? !group.isResolved : group.isResolved));

  return (
    <div className="adm-browser">
      <nav className="adm-module-list" aria-label="모듈 선택">
        <header><h2>모듈</h2><span>미해결</span></header>
        {modules.map((item) => (
          <button key={item.key} type="button" className={item.key === current?.key ? 'is-on' : ''} aria-current={item.key === current?.key ? 'true' : undefined} onClick={() => onSelect(item.key)}>
            <span><b className="adm-mod" style={moduleStyle(item.key)}>{item.label}</b><small>전체 {item.total.toLocaleString()} · 해결 {item.resolved.toLocaleString()}</small></span>
            <i>{item.open.toLocaleString()}</i>
          </button>
        ))}
      </nav>
      <section className="adm-issue-panel" aria-label={`${current?.label ?? ''} 문제 목록`}>
        <header>
          <h2 className={current ? 'adm-mod' : undefined} style={current ? moduleStyle(current.key) : undefined}>{current?.label}</h2>
          <span>전체 {(current?.total ?? 0).toLocaleString()} · 미해결 {(current?.open ?? 0).toLocaleString()} · 해결 {(current?.resolved ?? 0).toLocaleString()} · {current?.types ?? 0}개 유형</span>
          <span className="adm-grow" />
          <div className="adm-tabs" role="group" aria-label="해결 상태">
            {VIEWS.map(([key, label]) => <button key={key} type="button" className={view === key ? 'is-on' : ''} aria-pressed={view === key} onClick={() => setView(key)}>{label}</button>)}
          </div>
        </header>
        <div className="adm-issue-scroll">
          <div className="adm-issue-columns"><span>해결</span><span>심각도</span><span>문제</span><span>실행자</span><span>시간</span><span>해결자</span></div>
          {list.length > 0
            ? <ul className="adm-issue-list">{list.map((group) => <IssueRowItem key={group.id} group={group} saving={saving.has(group.id)} onToggle={onToggle} />)}</ul>
            : <p className="adm-issue-empty">{view === 'resolved' ? '해결 체크한 문제가 없습니다.' : view === 'open' ? '남은 문제가 없습니다.' : '이 모듈에서 발견된 문제가 없습니다.'}</p>}
        </div>
      </section>
    </div>
  );
}
