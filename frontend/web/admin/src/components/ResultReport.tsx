// 실행 결과: 상단 통계, 모듈별 문제, 쿼리 목록, 하단 상세 (Figma 05, 05-1)
import { useMemo, useState } from 'react';
import { MODULES, type ModuleKey } from '../adapters/issues';
import { moduleStyle } from '../adapters/moduleColors';
import { downloadCsv } from '../runner/csv';
import { downloadHtmlReport } from '../runner/htmlReport';
import type { RunItem } from '../runner/useQueryRunner';
import { QueryDetail } from './QueryDetail';
import { QueryTable } from './QueryTable';
import { badgeOf, countsOf, formatDuration, mergeByQuery, numberOf } from './runView';

const SHORT: Record<ModuleKey, string> = { analysis: '질의 분석', search: '검색·View', m2: '모듈 2', m3: '모듈 3', m5: '모듈 5', m6: '모듈 6', qa: 'QA 최종' };

function moduleCounts(items: RunItem[]) {
  const map = new Map<ModuleKey, { warnings: number; errors: number }>(MODULES.map(({ key }) => [key, { warnings: 0, errors: 0 }]));
  for (const item of items) {
    for (const issue of item.result?.issues ?? []) {
      const entry = map.get(issue.module);
      if (!entry) continue;
      if (issue.severity === 'error') entry.errors += issue.count;
      else entry.warnings += issue.count;
    }
  }
  return map;
}

function chipText({ warnings, errors }: { warnings: number; errors: number }) {
  if (errors > 0 && warnings > 0) return `오류 ${errors} · 경고 ${warnings}`;
  if (errors > 0) return `오류 ${errors}`;
  return warnings > 0 ? `경고 ${warnings}` : '정상';
}

function Tile({ label, value, note, tone = '' }: { label: string; value: number; note: string; tone?: string }) {
  return <div className="adm-tile"><span>{label}</span><strong className={tone}>{value.toLocaleString()}</strong><small>{note}</small></div>;
}

type Props = {
  items: RunItem[];
  startedAt: number;
  owner: string;
  extraSkipped?: number;
  primaryLabel: string;
  onPrimary: () => void;
  secondaryLabel?: string;
  onSecondary?: () => void;
  rerunMode?: 'run' | 'draft';
  onRerun: (question: string) => void;
};

function formatStarted(date: Date) {
  const pad = (number: number) => String(number).padStart(2, '0');
  const clock = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  if (date.toDateString() === new Date().toDateString()) return `오늘 ${clock}`;
  return `${date.getFullYear()}.${pad(date.getMonth() + 1)}.${pad(date.getDate())} ${clock}`;
}

export function ResultReport({ items, startedAt: startedTime, owner, extraSkipped = 0, primaryLabel, onPrimary, secondaryLabel, onSecondary, rerunMode = 'run', onRerun }: Props) {
  const [filter, setFilter] = useState<ModuleKey | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);

  const stats = useMemo(() => {
    // 같은 질문을 여러 번 넣어도 통계에서는 한 쿼리로 셉니다.
    const unique = mergeByQuery(items);
    const finished = unique.filter((item) => item.result);
    const executed = items.filter((item) => item.result);
    const answered = finished.filter((item) => item.result?.summary.hasAnswer).length;
    const charted = finished.filter((item) => (item.result?.summary.chartCount ?? 0) > 0);
    const counts = finished.map(countsOf);
    return {
      unique: unique.length,
      finished: finished.length,
      executed: executed.length,
      skipped: unique.filter((item) => item.state === 'skipped').length + extraSkipped,
      unsaved: items.filter((item) => item.state === 'save_failed').length,
      answered,
      charts: charted.reduce((total, item) => total + (item.result?.summary.chartCount ?? 0), 0),
      chartedQueries: charted.length,
      clarified: finished.filter((item) => item.clarified).length,
      warnings: counts.reduce((total, item) => total + item.warnings, 0),
      warningQueries: counts.filter((item) => item.warnings > 0).length,
      errors: counts.reduce((total, item) => total + item.errors, 0),
      errorQueries: counts.filter((item) => item.errors > 0).length,
      backendFailures: finished.filter((item) => item.result?.status === 'error').length,
      activeMs: executed.reduce((total, item) => total + (item.result?.activeMs ?? 0), 0),
    };
  }, [extraSkipped, items]);

  const modules = useMemo(() => moduleCounts(mergeByQuery(items)), [items]);
  const visible = filter ? items.filter((item) => item.result?.issues.some((issue) => issue.module === filter)) : items;
  const detail = selected === null ? null : items.find((item) => item.position === selected) ?? null;
  const startedAt = new Date(startedTime);
  const percent = stats.finished > 0 ? Math.round((stats.answered / stats.finished) * 100) : 0;

  const exportCsv = () => {
    const rows: (string | number)[][] = [['번호', '질문', '상태', '답변 생성', '차트', 'QA 경고', '오류', '시간(초)', '메시지']];
    for (const item of items) {
      const { warnings, errors } = countsOf(item);
      rows.push([numberOf(item.position), item.question, badgeOf(item).label, item.result?.summary.hasAnswer ? '예' : '아니오', item.result?.summary.chartCount ?? 0, warnings, errors, item.result ? Number((item.result.activeMs / 1000).toFixed(1)) : '', item.result?.message ?? '']);
    }
    downloadCsv(`query-test-${startedAt.toISOString().slice(0, 16).replace(/[-:T]/g, '')}.csv`, rows);
  };

  // 질문과 최종 결과(차트 · 답변 · 출처)만 모은 HTML. 필터와 상관없이 실행한 모든 쿼리를 담습니다.
  const exportHtml = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      await downloadHtmlReport(`query-test-${startedAt.toISOString().slice(0, 16).replace(/[-:T]/g, '')}.html`, items, `${formatStarted(startedAt)} · ${owner} · 쿼리 ${items.length}개`);
    } catch {
      window.alert('HTML 파일을 만들지 못했습니다.');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="adm-report">
      <header className="adm-report-head">
        <div>
          <h1>실행 결과</h1>
          <p>{formatStarted(startedAt)} · {owner} · 쿼리 {stats.unique}개{items.length > stats.unique ? ` (실행 ${items.length}회)` : ''} · 총 {formatDuration(stats.activeMs)} · 예상 HCX {stats.executed * 3}~{stats.executed * 5}회</p>
        </div>
        <span className="adm-grow" />
        <button type="button" className="adm-button is-outline" onClick={exportCsv}>CSV 내려받기</button>
        <button type="button" className="adm-button is-outline" onClick={() => void exportHtml()} disabled={exporting}>{exporting ? 'HTML 만드는 중…' : 'HTML 내려받기'}</button>
        {secondaryLabel && <button type="button" className="adm-button is-outline" onClick={onSecondary}>{secondaryLabel}</button>}
        <button type="button" className="adm-button is-compact" onClick={onPrimary}>{primaryLabel}</button>
      </header>

      {stats.unsaved > 0 && <p className="adm-error" role="alert">{stats.unsaved}개 쿼리는 팀 리포트에 저장되지 않았습니다. 필요하면 CSV로 내려받아 주세요.</p>}

      <div className="adm-tiles">
        <Tile label="전체 쿼리" value={stats.unique} note={stats.skipped > 0 ? `${stats.finished}개 완료 · ${stats.skipped}개 건너뜀` : '실행 완료'} />
        <Tile label="답변 생성" value={stats.answered} note={`${stats.finished}개 중 ${percent}%`} tone="is-primary" />
        <Tile label="그린 차트" value={stats.charts} note={`${stats.chartedQueries}개 쿼리`} />
        <Tile label="되묻기" value={stats.clarified} note="직접 선택 완료" />
        <Tile label="QA 경고" value={stats.warnings} note={`${stats.warningQueries}개 쿼리`} tone="is-warn" />
        <Tile label="오류" value={stats.errors} note={`${stats.errorQueries}개 쿼리`} tone="is-error" />
      </div>

      <section className="adm-findings" aria-label="모듈별 발견 문제">
        <header>
          <h2>모듈별 발견 문제</h2>
          <span>{stats.backendFailures > 0 ? `모듈을 알 수 없는 백엔드 실패 ${stats.backendFailures}건 별도 · ` : ''}모듈을 누르면 해당 쿼리만 표시</span>
        </header>
        <div>
          {MODULES.map(({ key }) => {
            const count = modules.get(key) ?? { warnings: 0, errors: 0 };
            const tone = count.errors > 0 ? 'is-error' : count.warnings > 0 ? 'is-warn' : '';
            const on = filter === key;
            return (
              <button key={key} type="button" className={`${tone}${on ? ' is-on' : ''}`} aria-pressed={on} disabled={count.errors + count.warnings === 0} onClick={() => { setFilter(on ? null : key); setSelected(null); }}>
                <span className="adm-mod" style={moduleStyle(key)}>{SHORT[key]}</span><b>{chipText(count)}</b>
              </button>
            );
          })}
        </div>
      </section>

      <QueryTable items={visible} selected={selected} onSelect={(position) => setSelected(selected === position ? null : position)} />

      {detail && <QueryDetail key={detail.position} item={detail} onClose={() => setSelected(null)} rerunMode={rerunMode} onRerun={onRerun} />}
    </div>
  );
}
