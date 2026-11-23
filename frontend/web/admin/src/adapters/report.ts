// 팀 리포트 숫자를 선택한 필터에 맞게 계산합니다. 같은 쿼리를 여러 번 돌려도 한 번으로 셉니다.
import type { GroupRow, IssueRow, ReportData, RunRow } from '../supabase/report';
import { MODULES, type ModuleKey } from './issues';
import { queryKey } from './queryKey';

export type ReportFilters = { owner: string; severity: 'all' | 'error' | 'warning'; module: 'all' | ModuleKey };

export type ReportQuery = IssueRow & { runCount: number };

export type ReportGroup = GroupRow & {
  count: number;
  isResolved: boolean;
  reoccurred: boolean;
  owners: string[];
  queries: ReportQuery[];
};

export type ModuleStat = { key: ModuleKey; label: string; total: number; resolved: number; open: number; errors: number; warnings: number; types: number };

export type Report = {
  groups: ReportGroup[];
  modules: ModuleStat[];
  runs: number;
  executions: number;
  people: number;
  total: number;
  errors: number;
  warnings: number;
  resolved: number;
  open: number;
  rate: number;
  backendFailures: number;
};

/** 같은 쿼리에서 나온 같은 문제는 가장 최근 실행의 건수만 남깁니다. */
function latestByQuery(rows: IssueRow[]): ReportQuery[] {
  const latest = new Map<string, ReportQuery>();
  for (const row of rows) {
    const key = queryKey(row.query);
    const current = latest.get(key);
    if (!current) latest.set(key, { ...row, runCount: 1 });
    else if (row.createdAt > current.createdAt) latest.set(key, { ...row, runCount: current.runCount + 1 });
    else current.runCount += 1;
  }
  return [...latest.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

/** 쿼리별 최신 실행만 남깁니다. 백엔드 실패 뒤 다시 성공하면 실패로 세지 않습니다. */
function latestRuns(runs: RunRow[]) {
  const latest = new Map<string, RunRow>();
  for (const run of runs) {
    const key = queryKey(run.query);
    const current = latest.get(key);
    if (!current || run.createdAt > current.createdAt) latest.set(key, run);
  }
  return [...latest.values()];
}

export function buildReport(data: ReportData, filters: ReportFilters): Report {
  const issues = filters.owner === 'all' ? data.issues : data.issues.filter((issue) => issue.owner === filters.owner);
  const runs = filters.owner === 'all' ? data.runs : data.runs.filter((run) => run.owner === filters.owner);
  const uniqueRuns = latestRuns(runs);
  const byGroup = new Map<string, IssueRow[]>();
  for (const issue of issues) {
    const list = byGroup.get(issue.groupId);
    if (list) list.push(issue);
    else byGroup.set(issue.groupId, [issue]);
  }

  const groups = data.groups.flatMap((group): ReportGroup[] => {
    const rows = byGroup.get(group.id);
    if (!rows) return [];
    if (filters.severity !== 'all' && group.severity !== filters.severity) return [];
    if (filters.module !== 'all' && group.module !== filters.module) return [];
    const queries = latestByQuery(rows);
    // 해결 체크 뒤에 같은 문제가 다시 나오면 미해결로 되돌려 보여줍니다.
    const reoccurred = group.resolved && group.runs_after_resolved > 0;
    return [{
      ...group,
      count: queries.reduce((total, item) => total + item.occurrences, 0),
      isResolved: group.resolved && !reoccurred,
      reoccurred,
      owners: [...new Set([...rows].sort((a, b) => b.createdAt.localeCompare(a.createdAt)).map((item) => item.owner))],
      queries,
    }];
  }).sort((a, b) => Number(a.isResolved) - Number(b.isResolved)
    || Number(b.severity === 'error') - Number(a.severity === 'error')
    || b.count - a.count
    || a.message.localeCompare(b.message));

  const modules = MODULES
    .filter(({ key }) => filters.module === 'all' || key === filters.module)
    .map(({ key, label }): ModuleStat => {
      const items = groups.filter((group) => group.module === key);
      const sum = (pick: (group: ReportGroup) => boolean) => items.filter(pick).reduce((total, group) => total + group.count, 0);
      const total = sum(() => true);
      const resolved = sum((group) => group.isResolved);
      return { key, label, total, resolved, open: total - resolved, errors: sum((group) => group.severity === 'error'), warnings: sum((group) => group.severity === 'warning'), types: items.length };
    });

  const total = modules.reduce((value, item) => value + item.total, 0);
  const resolved = modules.reduce((value, item) => value + item.resolved, 0);
  return {
    groups,
    modules,
    runs: uniqueRuns.length,
    executions: runs.length,
    people: new Set(runs.map((run) => run.owner)).size,
    total,
    errors: modules.reduce((value, item) => value + item.errors, 0),
    warnings: modules.reduce((value, item) => value + item.warnings, 0),
    resolved,
    open: total - resolved,
    rate: total > 0 ? Math.round((resolved / total) * 100) : 0,
    backendFailures: uniqueRuns.filter((run) => run.status === 'error').length,
  };
}

export function formatWhen(value: string) {
  const date = new Date(value);
  const today = new Date();
  const days = Math.round((new Date(today.toDateString()).getTime() - new Date(date.toDateString()).getTime()) / 86_400_000);
  if (days <= 0) return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
  if (days === 1) return '어제';
  return `${date.getMonth() + 1}.${String(date.getDate()).padStart(2, '0')}`;
}
