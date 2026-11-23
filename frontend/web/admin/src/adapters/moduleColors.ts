// 모듈마다 고정된 색입니다. 빨강(오류)과 주황(경고)은 상태 전용이라 모듈 색으로 쓰지 않습니다.
import type { CSSProperties } from 'react';
import type { ModuleKey } from './issues';

export const MODULE_COLORS: Record<ModuleKey, string> = {
  analysis: '#2563c9',
  search: '#12a08f',
  m2: '#7a55cc',
  m3: '#c42f92',
  m5: '#1f93c7',
  m6: '#5f9426',
  qa: '#4848ad',
};

export const moduleStyle = (key: ModuleKey) => ({ '--module': MODULE_COLORS[key] }) as CSSProperties;
