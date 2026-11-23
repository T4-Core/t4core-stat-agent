// 실행 1회(묶음) 단위의 기록을 읽습니다. 저장된 쿼리가 없는 묶음은 제외됩니다.
import { restoreItem, type SavedRun } from '../adapters/restore';
import { supabase } from './client';

const PAGE_SIZE = 30;
// 저장된 상세가 커서 결과는 조금씩 나눠 읽습니다.
const RESULT_PAGE_SIZE = 25;

export type HistoryEntry = {
  id: string;
  owner: string;
  createdAt: string;
  totalCount: number;
  queries: string[];
};

type RawBatch = {
  id: string;
  owner_login: string;
  total_count: number;
  created_at: string;
  adm_test_runs: { query: string; position: number }[];
};

/** 실행 1회의 저장 결과를 불러옵니다. */
export async function fetchBatchResult(batchId: string) {
  if (!supabase) throw new Error('Supabase 설정이 필요합니다.');
  const failed = '저장된 결과를 불러오지 못했습니다. 인터넷 연결과 로그인 상태를 확인해 주세요.';
  const meta = await supabase.from('adm_test_batches').select('id,owner_login,total_count,created_at').eq('id', batchId).limit(1);
  if (meta.error) throw new Error(failed);
  const batch = meta.data?.[0];
  if (!batch) throw new Error('이 실행 기록을 찾을 수 없습니다. 삭제되었을 수 있습니다.');

  const runs: SavedRun[] = [];
  for (;;) {
    const { data, error } = await supabase.from('adm_test_runs')
      .select('position,query,status,qa_status,has_answer,chart_count,timings,detail,adm_run_issues(occurrences,sample_path,adm_issue_groups!inner(module,point,kind,severity,path_pattern,message))')
      .eq('batch_id', batchId)
      .order('position')
      .range(runs.length, runs.length + RESULT_PAGE_SIZE - 1);
    if (error) throw new Error(failed);
    const page = (data ?? []) as unknown as SavedRun[];
    runs.push(...page);
    if (page.length < RESULT_PAGE_SIZE) break;
  }
  return {
    owner: batch.owner_login as string,
    totalCount: batch.total_count as number,
    createdAt: batch.created_at as string,
    items: runs.map(restoreItem),
  };
}

export async function fetchHistory(offset: number, owner: string | null) {
  if (!supabase) throw new Error('Supabase 설정이 필요합니다.');
  const base = supabase.from('adm_test_batches').select('id,owner_login,total_count,created_at,adm_test_runs!inner(query,position)');
  const filtered = owner ? base.eq('owner_login', owner) : base;
  // 다음 페이지가 있는지 알기 위해 한 줄 더 읽습니다.
  const { data, error } = await filtered.order('created_at', { ascending: false }).order('id').range(offset, offset + PAGE_SIZE);
  if (error) throw new Error('History를 불러오지 못했습니다. 인터넷 연결과 로그인 상태를 확인해 주세요.');
  const rows = (data ?? []) as unknown as RawBatch[];
  return {
    hasMore: rows.length > PAGE_SIZE,
    entries: rows.slice(0, PAGE_SIZE).map((row): HistoryEntry => ({
      id: row.id,
      owner: row.owner_login,
      createdAt: row.created_at,
      totalCount: row.total_count,
      queries: [...row.adm_test_runs].sort((a, b) => a.position - b.position).map((run) => run.query),
    })),
  };
}
