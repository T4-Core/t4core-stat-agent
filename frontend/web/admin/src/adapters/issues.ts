// 백엔드 응답의 QA 결과를 모듈별 오류로 바꿉니다. 참고용 info 는 세지 않습니다.
import type { ChatResponse } from '../../../src/api/types';

export type ModuleKey = 'analysis' | 'search' | 'm2' | 'm3' | 'm5' | 'm6' | 'qa';

export type AdminIssue = {
  module: ModuleKey;
  point: string;
  kind: string;
  severity: 'warning' | 'error';
  path: string;
  message: string;
  count: number;
  source: 'qa' | 'module';
};

export const MODULES: { key: ModuleKey; label: string }[] = [
  { key: 'analysis', label: '질의 분석' },
  { key: 'search', label: '검색·View' },
  { key: 'm2', label: '모듈 2 · 차트 계획' },
  { key: 'm3', label: '모듈 3 · 계산' },
  { key: 'm5', label: '모듈 5 · 차트 그리기' },
  { key: 'm6', label: '모듈 6 · 답변 작성' },
  { key: 'qa', label: 'QA 최종 검사' },
];

type Dict = Record<string, unknown>;

const asDict = (value: unknown): Dict | null => (typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Dict : null);
const asList = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown) => (typeof value === 'string' ? value : '');

function moduleOfPoint(point: string): ModuleKey {
  if (point === 'A0') return 'search';
  if (point.startsWith('M2')) return 'm2';
  if (point.startsWith('M3')) return 'm3';
  if (point.startsWith('M5')) return 'm5';
  if (point.startsWith('M6')) return 'm6';
  return 'qa';
}

export function toIssues(responses: ChatResponse[]): AdminIssue[] {
  const issues: AdminIssue[] = [];
  for (const response of responses) {
    const modules = asDict(response.modules);
    for (const item of asList(asDict(modules?.qa)?.issues)) {
      const issue = asDict(item);
      if (!issue || (issue.severity !== 'warning' && issue.severity !== 'error')) continue;
      const point = text(issue.point);
      issues.push({
        module: moduleOfPoint(point),
        point,
        kind: text(issue.kind),
        severity: issue.severity,
        path: text(issue.path),
        message: text(issue.message) || '메시지 없음',
        count: typeof issue.count === 'number' && issue.count > 0 ? issue.count : 1,
        source: 'qa',
      });
    }
    for (const item of asList(modules?.chart_errors)) {
      const error = asDict(item);
      if (error?.level !== 'error') continue;
      issues.push({ module: 'm2', point: 'chart_errors', kind: text(error.node), severity: 'error', path: text(error.chart_id), message: text(error.reason) || '차트 계획 오류', count: 1, source: 'module' });
    }
    for (const item of asList(modules?.drawn)) {
      const drawn = asDict(item);
      if (drawn?.status !== 'failed') continue;
      issues.push({ module: 'm5', point: 'drawn', kind: 'failed', severity: 'error', path: text(drawn.chart_id), message: text(drawn.reason) || '차트를 그리지 못했습니다.', count: 1, source: 'module' });
    }
  }
  return issues;
}

export function countByModule(issues: AdminIssue[]) {
  const counts: Partial<Record<ModuleKey, number>> = {};
  for (const issue of issues) counts[issue.module] = (counts[issue.module] ?? 0) + issue.count;
  return counts;
}

export type IssueSummary = Pick<AdminIssue, 'module' | 'point' | 'kind' | 'severity' | 'message' | 'source'> & { pattern: string; count: number };

/** 같은 경로·메시지의 오류를 한 줄로 묶습니다. DB의 묶음 기준과 같습니다. */
export function summarizeIssues(issues: AdminIssue[]): IssueSummary[] {
  const groups = new Map<string, IssueSummary>();
  for (const issue of issues) {
    const pattern = issue.path.replace(/\[\d+\]/g, '[]');
    const key = [issue.module, issue.point, issue.kind, issue.severity, pattern, issue.message].join('\u001f');
    const group = groups.get(key);
    if (group) group.count += issue.count;
    else groups.set(key, { module: issue.module, point: issue.point, kind: issue.kind, severity: issue.severity, message: issue.message, source: issue.source, pattern, count: issue.count });
  }
  const order = MODULES.map((item) => item.key);
  return [...groups.values()].sort((a, b) => order.indexOf(a.module) - order.indexOf(b.module) || b.count - a.count);
}
