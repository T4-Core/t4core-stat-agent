// 쿼리 한 줄의 상태 표시와 숫자를 계산합니다.
import { summarizeIssues, type AdminIssue } from '../adapters/issues';
import { queryKey } from '../adapters/queryKey';
import type { RunItem } from '../runner/useQueryRunner';

export type Badge = { label: string; tone: 'ok' | 'running' | 'input' | 'warn' | 'error' | 'muted' };

export function badgeOf(item: RunItem): Badge {
  switch (item.state) {
    case 'queued': return { label: '대기', tone: 'muted' };
    case 'running': return { label: '실행 중', tone: 'running' };
    case 'input': return { label: '입력 필요', tone: 'input' };
    case 'saving': return { label: '저장 중', tone: 'running' };
    case 'skipped': return { label: '건너뜀', tone: 'muted' };
    case 'save_failed': return { label: '저장 실패', tone: 'error' };
    default:
  }
  const result = item.result;
  if (!result || result.status === 'error') return { label: '오류', tone: 'error' };
  if (result.status === 'out_of_scope') return { label: '범위 밖', tone: 'muted' };
  if (result.summary.qaStatus === 'stopped' || result.issues.some((issue) => issue.severity === 'error')) return { label: '오류', tone: 'error' };
  return result.issues.length > 0 ? { label: '경고', tone: 'warn' } : { label: '성공', tone: 'ok' };
}

export function countsOf(item: RunItem) {
  const issues = item.result?.issues ?? [];
  const warnings = issues.filter((issue) => issue.severity === 'warning').reduce((total, issue) => total + issue.count, 0);
  const moduleErrors = issues.filter((issue) => issue.severity === 'error').reduce((total, issue) => total + issue.count, 0);
  // 백엔드 요청 실패는 모듈을 알 수 없어 쿼리의 오류로만 1건 셉니다.
  const errors = moduleErrors + (item.result?.status === 'error' ? 1 : 0);
  return { warnings, errors };
}

/** 같은 질문을 한 번으로 묶습니다. 상태는 최신 실행, 문제는 실행들에서 나온 종류를 한 번씩 셉니다. */
export function mergeByQuery(items: RunItem[]) {
  const byQuery = new Map<string, RunItem[]>();
  for (const item of items) {
    const key = queryKey(item.question);
    byQuery.set(key, [...(byQuery.get(key) ?? []), item]);
  }
  return [...byQuery.values()].map((list): RunItem => {
    const finished = list.filter((item) => item.result);
    const latest = finished.at(-1) ?? list[list.length - 1];
    if (!latest.result || finished.length < 2) return latest;
    const issues = new Map<string, AdminIssue>();
    for (const item of finished) {
      for (const issue of summarizeIssues(item.result?.issues ?? [])) {
        const key = [issue.module, issue.point, issue.kind, issue.severity, issue.pattern, issue.message].join('\u001f');
        issues.set(key, { module: issue.module, point: issue.point, kind: issue.kind, severity: issue.severity, path: issue.pattern, message: issue.message, count: issue.count, source: issue.source });
      }
    }
    return { ...latest, clarified: list.some((item) => item.clarified), result: { ...latest.result, issues: [...issues.values()] } };
  });
}

export const formatSeconds =(ms: number) => `${(ms / 1000).toFixed(1)}초`;

export function formatDuration(ms: number) {
  const seconds = Math.round(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes}분 ${seconds % 60}초` : `${seconds}초`;
}

export const numberOf = (position: number) => String(position + 1).padStart(2, '0');
