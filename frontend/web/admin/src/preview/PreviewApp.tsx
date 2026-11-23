// 기존 사용자 화면을 수정 없이 그대로 띄우고, 진행 상태만 관리자 화면에 전달합니다.
import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css';
import '../../../src/styles/tokens.css';
import '../../../src/styles/global.css';
import '../../../src/styles/main.css';
import '../../../src/styles/flow.css';
import '../../../src/styles/result.css';
import '../../../src/styles/history.css';
import '../../../src/styles/live.css';
import './preview.css';
import { useEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { StageLayout } from '../../../src/components/Layout';
import { ClarifyPage } from '../../../src/pages/ClarifyPage';
import { GeneratingPage } from '../../../src/pages/GeneratingPage';
import { NoticePage } from '../../../src/pages/NoticePage';
import { ResultPage } from '../../../src/pages/ResultPage';
import { SelectPage } from '../../../src/pages/SelectPage';
import { ViewDetailPage } from '../../../src/pages/ViewDetailPage';
import { loadPayload } from '../../../src/store/payloads';
import { createRun, removeRun, useRuns } from '../../../src/store/history';
import type { ParentMessage, PreviewMessage, RunRound } from '../runner/protocol';

type Active = { token: string; id: string; last: string; pendingAt: number; activeMs: number; rounds: RunRound[] };

let activeRunId: string | null = null;

function post(message: PreviewMessage) {
  window.parent.postMessage(message, window.location.origin);
}

function Bridge() {
  const navigate = useNavigate();
  const runs = useRuns();
  const active = useRef<Active | null>(null);

  useEffect(() => {
    const onMessage = (event: MessageEvent<ParentMessage>) => {
      if (event.origin !== window.location.origin || event.source !== window.parent) return;
      const message = event.data;
      if (message?.source !== 'adm-parent') return;
      if (message.type === 'reset') {
        const current = active.current;
        active.current = null;
        activeRunId = null;
        navigate('/', { replace: true });
        if (current) removeRun(current.id);
        return;
      }
      if (active.current) return;
      const run = createRun({ question: message.question, tags: [], needsSelection: false });
      activeRunId = run.id;
      active.current = { token: message.token, id: run.id, last: 'pending', pendingAt: Date.now(), activeMs: 0, rounds: [] };
      post({ source: 'adm-preview', type: 'status', token: message.token, status: 'pending' });
      navigate(`/generating/${run.id}`, { replace: true });
    };
    window.addEventListener('message', onMessage);
    post({ source: 'adm-preview', type: 'ready' });
    return () => window.removeEventListener('message', onMessage);
  }, [navigate]);

  useEffect(() => {
    const current = active.current;
    if (!current) return;
    const run = runs.find((item) => item.id === current.id);
    if (!run) {
      active.current = null;
      activeRunId = null;
      post({ source: 'adm-preview', type: 'cancelled', token: current.token });
      return;
    }
    if (run.status === current.last) return;
    if (current.last === 'pending') current.activeMs += Date.now() - current.pendingAt;
    current.last = run.status;
    if (run.status === 'pending') {
      current.pendingAt = Date.now();
      post({ source: 'adm-preview', type: 'status', token: current.token, status: 'pending' });
      return;
    }

    const status = run.status;
    const message = run.message;
    void (status === 'error' ? Promise.resolve(null) : loadPayload(run.id)).then((payload) => {
      if (active.current !== current) return;
      const response = payload?.responses[0];
      if (status === 'needs_clarification' || status === 'needs_selection') {
        current.rounds.push({ status, timings: response?.timings ?? {} });
        post({ source: 'adm-preview', type: 'status', token: current.token, status });
        return;
      }
      for (const item of payload?.responses ?? []) current.rounds.push({ status: item.status, timings: item.timings ?? {} });
      if (status === 'error') current.rounds.push({ status: 'error', timings: {} });
      post({
        source: 'adm-preview',
        type: 'finished',
        token: current.token,
        outcome: {
          status: status === 'done' ? 'ok' : status === 'out_of_scope' ? 'out_of_scope' : 'error',
          responses: payload?.responses ?? [],
          labels: payload?.labels,
          message,
          rounds: current.rounds,
          activeMs: current.activeMs,
        },
      });
    });
  }, [runs]);

  return null;
}

// 테스트 중 다른 질문이 추가로 전송되어 비용이 나가지 않도록 막습니다.
function GuardedGenerating() {
  const { id } = useParams();
  const allowed = id === activeRunId;
  useEffect(() => {
    if (id && !allowed) removeRun(id);
  }, [allowed, id]);
  if (allowed) return <GeneratingPage />;
  return <Navigate to={activeRunId ? `/result/${activeRunId}` : '/'} replace />;
}

function Idle() {
  return <div className="adm-preview-idle">쿼리를 실행하면 실제 사용자 화면이 여기에 표시됩니다.</div>;
}

// 미리보기 안에서 머리글 링크로 다른 화면에 가지 않도록 합니다.
document.addEventListener('click', (event) => {
  if ((event.target as Element | null)?.closest('.app-header a')) event.preventDefault();
}, true);

createRoot(document.getElementById('root')!).render(
  <MemoryRouter>
    <Bridge />
    <Routes>
      <Route element={<StageLayout />}>
        <Route path="generating/:id" element={<GuardedGenerating />} />
        <Route path="select/:id" element={<SelectPage />} />
        <Route path="clarify/:id" element={<ClarifyPage />} />
        <Route path="notice/:id" element={<NoticePage />} />
        <Route path="result/:id" element={<ResultPage />} />
        <Route path="result/:id/tables/:viewNo" element={<ViewDetailPage />} />
        <Route path="*" element={<Idle />} />
      </Route>
    </Routes>
  </MemoryRouter>,
);
