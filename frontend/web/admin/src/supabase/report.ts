// 팀 전체 에러 리포트를 읽고 해결 체크를 저장합니다.
import type { ModuleKey } from '../adapters/issues';
import { supabase } from './client';

// Supabase는 한 번에 1000줄까지 주므로 나눠서 읽습니다.
const PAGE_SIZE = 1000;
const MAX_ROWS = 50_000;

export type GroupRow = {
  id: string;
  module: ModuleKey;
  point: string;
  kind: string;
  severity: 'warning' | 'error';
  path_pattern: string;
  message: string;
  resolved: boolean;
  resolved_by_login: string | null;
  resolved_at: string | null;
  runs_after_resolved: number;
};

export type IssueRow = { groupId: string; occurrences: number; runId: string; query: string; createdAt: string; owner: string };
export type RunRow = { id: string; query: string; status: string; createdAt: string; owner: string };
export type ReportData = { groups: GroupRow[]; issues: IssueRow[]; runs: RunRow[]; members: string[]; truncated: boolean };

type RawIssue = {
  group_id: string;
  occurrences: number;
  adm_test_runs: { id: string; query: string; created_at: string; adm_test_batches: { owner_login: string } };
};
type RawRun = { id: string; query: string; status: string; created_at: string; adm_test_batches: { owner_login: string } };
type Page<T> = PromiseLike<{ data: unknown; error: { message?: string } | null }> & { __row?: T };

function db() {
  if (!supabase) throw new Error('Supabase 설정이 필요합니다.');
  return supabase;
}

async function readAll<T>(page: (from: number, to: number) => Page<T>) {
  const rows: T[] = [];
  while (rows.length < MAX_ROWS) {
    const { data, error } = await page(rows.length, rows.length + PAGE_SIZE - 1);
    if (error) throw new Error('팀 리포트를 불러오지 못했습니다. 인터넷 연결과 로그인 상태를 확인해 주세요.');
    const batch = (data ?? []) as T[];
    rows.push(...batch);
    if (batch.length < PAGE_SIZE) return { rows, truncated: false };
  }
  return { rows, truncated: true };
}

export async function fetchReport(since: string | null): Promise<ReportData> {
  const client = db();
  const [groups, issues, runs, members] = await Promise.all([
    readAll<GroupRow>((from, to) => client.from('adm_issue_group_stats')
      .select('id,module,point,kind,severity,path_pattern,message,resolved,resolved_by_login,resolved_at,runs_after_resolved')
      .order('id').range(from, to)),
    readAll<RawIssue>((from, to) => {
      const query = client.from('adm_run_issues')
        .select('group_id,occurrences,adm_test_runs!inner(id,query,created_at,adm_test_batches!inner(owner_login))');
      return (since ? query.gte('adm_test_runs.created_at', since) : query).order('run_id').order('group_id').range(from, to);
    }),
    readAll<RawRun>((from, to) => {
      const query = client.from('adm_test_runs').select('id,query,status,created_at,adm_test_batches!inner(owner_login)');
      return (since ? query.gte('created_at', since) : query).order('id').range(from, to);
    }),
    readAll<{ login_id: string }>((from, to) => client.from('adm_profiles').select('login_id').order('login_id').range(from, to)),
  ]);
  return {
    groups: groups.rows,
    issues: issues.rows.map((row) => ({
      groupId: row.group_id,
      occurrences: row.occurrences,
      runId: row.adm_test_runs.id,
      query: row.adm_test_runs.query,
      createdAt: row.adm_test_runs.created_at,
      owner: row.adm_test_runs.adm_test_batches.owner_login,
    })),
    runs: runs.rows.map((row) => ({ id: row.id, query: row.query, status: row.status, createdAt: row.created_at, owner: row.adm_test_batches.owner_login })),
    members: [...new Set(members.rows.map((row) => row.login_id))],
    truncated: groups.truncated || issues.truncated || runs.truncated,
  };
}

export async function setIssueResolved(groupId: string, resolved: boolean) {
  const { error } = await db().rpc('adm_set_issue_resolved', { p_group_id: groupId, p_resolved: resolved });
  if (error) throw new Error('해결 상태를 저장하지 못했습니다. 다시 시도해 주세요.');
}
