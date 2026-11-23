// 테스트 결과를 팀 공용 DB에 저장합니다. 실제 쓰기는 schema.sql 의 함수가 권한을 확인합니다.
import type { AdminIssue } from '../adapters/issues';
import { supabase } from './client';

function db() {
  if (!supabase) throw new Error('Supabase 설정이 필요합니다.');
  return supabase;
}

function toMessage(error: { message?: string }) {
  const message = error.message ?? '';
  if (message.includes('ADMIN_STORAGE_FULL')) return '팀 DB 저장 공간이 한도(400MB)에 도달했습니다. 오래된 결과를 정리한 뒤 다시 실행해 주세요.';
  if (message.includes('ADMIN_LOGIN_REQUIRED') || message.includes('JWT')) return '로그인이 만료되었습니다. 다시 로그인해 주세요.';
  if (message.includes('ADMIN_PROFILE_MISSING')) return '팀원 정보가 등록되지 않았습니다. 담당자에게 계정 확인을 요청해 주세요.';
  return '팀 DB에 저장하지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.';
}

export async function createBatch(title: string, total: number) {
  const { data, error } = await db().rpc('adm_create_batch', { p_title: title.slice(0, 200), p_total: total });
  if (error) throw new Error(toMessage(error));
  return data as string;
}

export async function deleteBatch(id: string) {
  const { error } = await db().from('adm_test_batches').delete().eq('id', id);
  if (error) throw new Error(toMessage(error));
}

export type SaveRunInput = {
  batchId: string;
  position: number;
  query: string;
  status: string;
  qaStatus: string | null;
  hasAnswer: boolean;
  chartCount: number;
  timings: Record<string, number> | null;
  detail: unknown;
  issues: AdminIssue[];
};

export async function saveRun(input: SaveRunInput) {
  const { data, error } = await db().rpc('adm_save_test_run', {
    p_batch_id: input.batchId,
    p_position: input.position,
    p_query: input.query,
    p_status: input.status,
    p_qa_status: input.qaStatus,
    p_has_answer: input.hasAnswer,
    p_chart_count: input.chartCount,
    p_timings: input.timings,
    p_detail: input.detail,
    p_issues: input.issues.map(({ module, point, kind, severity, path, message, count }) => ({ module, point, kind, severity, path, message, count })),
  });
  if (error) throw new Error(toMessage(error));
  return data as string;
}

export type StorageUsage = { used_bytes: number; warn_bytes: number; block_bytes: number; state: 'ok' | 'warning' | 'blocked' };

export async function getStorageUsage() {
  const { data, error } = await db().rpc('adm_storage_usage');
  if (error) throw new Error(toMessage(error));
  return (Array.isArray(data) ? data[0] : data) as StorageUsage;
}
