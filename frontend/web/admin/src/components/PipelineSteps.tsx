// 실행 중 단계 표시. 백엔드가 실시간 진행을 주지 않아 실제로 아는 상태만 보여줍니다.
import { MODULES, type ModuleKey } from '../adapters/issues';
import { moduleStyle } from '../adapters/moduleColors';
import type { RunItem } from '../runner/useQueryRunner';
import { numberOf } from './runView';

type StepState = 'done' | 'warn' | 'active' | 'input' | 'idle' | 'failed';
type Step = { key: ModuleKey; label: string; state: StepState; note: string };

const make = (pick: (key: ModuleKey) => Pick<Step, 'state' | 'note'>): Step[] => MODULES.map(({ key, label }) => ({ key, label, ...pick(key) }));

function buildSteps(item: RunItem): { steps: Step[]; caption: string } {
  const { result, live } = item;
  if (!result) {
    if (live === 'needs_clarification') {
      return { caption: '질의 분석에서 사용자 입력을 기다리는 중', steps: make((key) => (key === 'analysis' ? { state: 'input', note: '입력 대기' } : { state: 'idle', note: '' })) };
    }
    if (live === 'needs_selection') {
      return { caption: '검색 결과의 표 선택을 기다리는 중', steps: make((key) => (key === 'analysis' ? { state: 'done', note: '완료' } : key === 'search' ? { state: 'input', note: '입력 대기' } : { state: 'idle', note: '' })) };
    }
    return { caption: '백엔드가 단계별 진행을 알려주지 않아, 응답을 받으면 결과를 표시합니다.', steps: make(() => ({ state: 'active', note: '응답 대기' })) };
  }
  const view = result.views[0];
  if (!view) return { caption: result.message ?? '요청이 실패했습니다.', steps: make(() => ({ state: 'failed', note: '확인 불가' })) };
  const steps = view.steps.map((step): Step => {
    const count = step.issues.reduce((total, issue) => total + issue.count, 0);
    if (step.state === 'skipped') return { key: step.key, label: step.label, state: 'idle', note: '실행 안 함' };
    if (step.state === 'error') return { key: step.key, label: step.label, state: 'failed', note: count > 0 ? `문제 ${count}` : '중단' };
    if (step.state === 'warn') return { key: step.key, label: step.label, state: 'warn', note: `경고 ${count}` };
    return { key: step.key, label: step.label, state: 'done', note: step.time || '이상 없음' };
  });
  return { caption: '결과를 저장하고 있습니다.', steps };
}

export function PipelineSteps({ item }: { item: RunItem }) {
  const { steps, caption } = buildSteps(item);
  return (
    <section className="adm-steps" aria-label="중간 단계">
      <h2 title={item.question}>{numberOf(item.position)} · {item.question}</h2>
      <p>{caption}</p>
      <ol>
        {steps.map((step) => (
          <li key={step.key} className={`is-${step.state}`}>
            <span className="adm-step-dot" aria-hidden="true">{step.state === 'done' ? '✓' : step.state === 'warn' || step.state === 'failed' ? '!' : ''}</span>
            <span className="adm-step-label adm-mod" style={moduleStyle(step.key)}>{step.label}</span>
            <span className="adm-step-note">{step.note}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
