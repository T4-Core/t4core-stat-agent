// 자동 생성 타입(openapi.d.ts)에 짧은 이름을 붙입니다.
import type { components } from './openapi';

type Schemas = components['schemas'];

export type ChatRequest = Schemas['ChatRequest'];
export type ChatResponse = Schemas['ChatResponse'];
export type SelectionItem = Schemas['SelectionItem'];
export type JudgeResult = Schemas['JudgeResult'];

export type PlotlyFigure = {
  data?: unknown[];
  layout?: Record<string, unknown>;
};
