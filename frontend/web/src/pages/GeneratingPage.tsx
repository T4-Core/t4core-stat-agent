// 2. 답변 생성 중: 백엔드가 진행 상황을 주지 않아 단계는 시간 기준으로 표시합니다.
import { useEffect, useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import active from '../assets/figma/step-active.svg';
import check from '../assets/figma/step-check.svg';
import pending from '../assets/figma/step-pending.svg';
import { Character } from '../character';
import { ThinkingBubble } from '../character/ThinkingBubble';
import { Frame, QueryPill } from '../components/Layout';
import { startRun, stopRun } from '../store/agent';
import { routeForRun, useRun } from '../store/history';

const STEPS = ['질문 이해하기', '알맞은 통계표 찾기', '데이터 불러오기', '차트와 답변 만들기'];
const TITLES = ['질문을 이해하고 있어요…', '알맞은 통계표를 찾고 있어요…', '통계표에서 숫자를 찾고 있어요…', '차트와 답변을 만들고 있어요…'];
const STEP_MS = 1100;

export function GeneratingPage() {
  const { id } = useParams();
  const run = useRun(id);
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const status = run?.status;

  useEffect(() => {
    if (id) startRun(id);
  }, [id]);

  useEffect(() => {
    if (step >= STEPS.length - 1) return;
    const timer = window.setTimeout(() => setStep(step + 1), STEP_MS);
    return () => window.clearTimeout(timer);
  }, [step]);

  useEffect(() => {
    if (run && status !== 'pending') navigate(routeForRun(run), { replace: true });
  }, [navigate, run, status]);

  if (!run) return <Navigate to="/" replace />;

  const stop = () => {
    navigate('/', { replace: true });
    stopRun(run.id);
  };

  return (
    <Frame variant="generating">
      <QueryPill className="generating-pill" question={run.question} />
      <Character className="generating-sloth" size="L" motion="thinking" />
      <ThinkingBubble className="generating-bubble" step={step} />
      <h1 className="generating-title">{TITLES[step]}</h1>
      <ol className="progress-card">
        {STEPS.map((label, index) => {
          const state = index < step ? 'done' : index === step ? 'active' : 'pending';
          return (
            <li className={`progress-step ${state}`} key={label} aria-current={state === 'active' ? 'step' : undefined}>
              {state === 'done' ? <span className="step-check"><img src={check} alt="" width={13} height={13} /></span> : <img src={state === 'active' ? active : pending} alt="" width={24} height={24} />}
              <span className="step-label">{label}</span>
              {index === 0 && state === 'done' && run.tags.length > 0 && <span className="step-tag">{run.tags.join(' · ')}</span>}
            </li>
          );
        })}
      </ol>
      <button type="button" className="stop-button" onClick={stop}>중단</button>
    </Frame>
  );
}
