// 모듈별 에러 통계 화면 (Figma 07). 팀원 전체의 실행 결과를 함께 봅니다.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { MODULES, type ModuleKey } from '../adapters/issues';
import { buildReport, type ReportFilters, type ReportGroup } from '../adapters/report';
import { IssueBrowser } from '../components/IssueBrowser';
import { ModuleBars } from '../components/ModuleBars';
import { useAuth } from '../supabase/auth';
import { fetchReport, setIssueResolved, type ReportData } from '../supabase/report';

const PERIODS = [
  { value: '1', label: '오늘' },
  { value: '7', label: '최근 7일' },
  { value: '30', label: '최근 30일' },
  { value: 'all', label: '전체 기간' },
];

function sinceOf(period: string) {
  if (period === 'all') return null;
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - (Number(period) - 1));
  return date.toISOString();
}

export function ErrorReportPage() {
  const { displayName } = useAuth();
  const [period, setPeriod] = useState('7');
  const [filters, setFilters] = useState<ReportFilters>({ owner: 'all', severity: 'all', module: 'all' });
  const [data, setData] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [picked, setPicked] = useState<ModuleKey | null>(null);
  const [saving, setSaving] = useState<Set<string>>(new Set());
  const request = useRef(0);

  const load = useCallback(async () => {
    const id = request.current + 1;
    request.current = id;
    setLoading(true);
    setError('');
    try {
      const next = await fetchReport(sinceOf(period));
      if (request.current === id) setData(next);
    } catch (cause) {
      if (request.current === id) setError(cause instanceof Error ? cause.message : '팀 리포트를 불러오지 못했습니다.');
    } finally {
      if (request.current === id) setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    void load();
    return () => { request.current += 1; };
  }, [load]);

  const report = useMemo(() => (data ? buildReport(data, filters) : null), [data, filters]);
  const firstProblem = report?.modules.find((item) => item.open > 0) ?? report?.modules.find((item) => item.total > 0) ?? report?.modules[0];
  const selected = report?.modules.some((item) => item.key === picked) ? picked : firstProblem?.key ?? null;
  const periodLabel = PERIODS.find((item) => item.value === period)?.label ?? '';

  const toggle = async (group: ReportGroup) => {
    if (saving.has(group.id)) return;
    // 재발생한 문제는 다시 체크하면 지금 시점으로 해결 처리합니다.
    const next = !group.isResolved;
    const before = data?.groups.find((item) => item.id === group.id);
    const patch = (value: Partial<ReportGroup>) => setData((current) => current && {
      ...current,
      groups: current.groups.map((item) => (item.id === group.id ? { ...item, ...value } : item)),
    });
    setSaving((current) => new Set(current).add(group.id));
    setError('');
    patch({ resolved: next, resolved_by_login: next ? displayName : null, resolved_at: next ? new Date().toISOString() : null, runs_after_resolved: 0 });
    try {
      await setIssueResolved(group.id, next);
    } catch (cause) {
      if (before) patch(before);
      setError(cause instanceof Error ? cause.message : '해결 상태를 저장하지 못했습니다.');
    } finally {
      setSaving((current) => {
        const copy = new Set(current);
        copy.delete(group.id);
        return copy;
      });
    }
  };

  return (
    <section className="adm-report-page">
      <header className="adm-report-head">
        <div>
          <h1>모듈별 에러 통계</h1>
          <p>팀원 전체가 실행한 쿼리의 문제를 모듈별로 확인하고 해결 여부를 체크합니다.</p>
        </div>
        <span className="adm-grow" />
        <div className="adm-filters">
          <select aria-label="기간" value={period} onChange={(event) => setPeriod(event.target.value)}>
            {PERIODS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <select aria-label="팀원" value={filters.owner} onChange={(event) => setFilters({ ...filters, owner: event.target.value })}>
            <option value="all">팀원 전체</option>
            {data?.members.map((member) => <option key={member} value={member}>{member}</option>)}
          </select>
          <select aria-label="심각도" value={filters.severity} onChange={(event) => setFilters({ ...filters, severity: event.target.value as ReportFilters['severity'] })}>
            <option value="all">심각도 전체</option>
            <option value="error">오류</option>
            <option value="warning">경고</option>
          </select>
          <select aria-label="모듈" value={filters.module} onChange={(event) => { setFilters({ ...filters, module: event.target.value as ReportFilters['module'] }); setPicked(null); }}>
            <option value="all">모듈 전체</option>
            {MODULES.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
          </select>
          <button type="button" className="adm-button is-outline" disabled={loading} onClick={() => void load()}>{loading ? '불러오는 중...' : '새로고침'}</button>
        </div>
      </header>

      {error && <p className="adm-error" role="alert">{error}</p>}
      {data?.truncated && <p className="adm-error" role="status">자료가 많아 일부만 집계했습니다. 기간을 줄여 주세요.</p>}

      {!report ? (
        <div className="adm-report-loading" role="status">{loading ? '팀 리포트를 불러오는 중입니다.' : '표시할 자료가 없습니다.'}</div>
      ) : (
        <>
          <div className="adm-report-summary">
            <div className="adm-big-tiles">
              <div className="adm-tile"><span>총 실행 쿼리</span><strong>{report.runs.toLocaleString()}</strong><small>팀원 {report.people}명 · {periodLabel}{report.executions > report.runs ? ` · 실행 ${report.executions.toLocaleString()}회` : ''}</small></div>
              <div className="adm-tile"><span>오류 개수</span><strong className="is-error">{report.total.toLocaleString()}</strong><small>오류 {report.errors.toLocaleString()} · QA 경고 {report.warnings.toLocaleString()}</small></div>
              <div className="adm-tile"><span>해결된 오류</span><strong className="is-primary">{report.resolved.toLocaleString()}</strong><small>해결률 {report.rate}% · 남은 {report.open.toLocaleString()}</small></div>
            </div>
            <ModuleBars modules={report.modules} selected={selected} backendFailures={report.backendFailures} onSelect={setPicked} />
          </div>
          <IssueBrowser modules={report.modules} groups={report.groups} selected={selected} saving={saving} onSelect={setPicked} onToggle={(group) => void toggle(group)} />
        </>
      )}
    </section>
  );
}
