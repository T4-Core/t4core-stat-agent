// 되묻기: 시점·지역·대상 중 빠진 조건을 고릅니다. (Figma 시안이 없어 기존 칩 디자인을 사용)
import { useEffect, useMemo, useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { toClarifications } from '../api/adapters';
import { Character } from '../character';
import { Frame, QueryPill } from '../components/Layout';
import type { ClarificationGroup } from '../data/types';
import { continueRun, usePayload } from '../store/agent';
import { removeRun, routeForRun, useRun } from '../store/history';

export function ClarifyPage() {
  const { id } = useParams();
  const run = useRun(id);
  const navigate = useNavigate();
  const { payload, loading } = usePayload(id);
  const response = payload?.responses[0];
  const groups = useMemo(() => (response ? toClarifications(response) : []), [response]);
  const [selected, setSelected] = useState<Record<string, string[]>>({});

  useEffect(() => {
    if (run && run.status !== 'needs_clarification') navigate(routeForRun(run), { replace: true });
  }, [navigate, run]);

  if (!run) return <Navigate to="/" replace />;
  if (loading) return <Frame variant="select"><span /></Frame>;
  if (!response || groups.length === 0) return <Navigate to="/" replace />;

  const toggle = (group: ClarificationGroup, value: string) => {
    setSelected((current) => {
      const values = current[group.slot] ?? [];
      if (!group.multi) return { ...current, [group.slot]: [value] };
      return { ...current, [group.slot]: values.includes(value) ? values.filter((item) => item !== value) : [...values, value] };
    });
  };
  const complete = groups.every((group) => (selected[group.slot]?.length ?? 0) > 0);
  const submit = () => {
    continueRun(run.id, response, { selections: selected });
    navigate(`/generating/${run.id}`, { replace: true });
  };
  const rewrite = () => {
    navigate('/', { replace: true });
    removeRun(run.id);
  };

  return (
    <Frame variant="select">
      <QueryPill className="select-pill" question={run.question} />
      <Character className="select-sloth" size="S" motion="asking" />
      <div className="select-heading">
        <h1>조금만 더 알려주세요</h1>
        <p>정확한 통계를 찾으려면 아래 조건을 골라 주세요.</p>
      </div>
      <section className="clarify-card" aria-label="추가 조건 선택">
        {groups.map((group) => (
          <fieldset key={group.slot}>
            <legend><b>{group.slot}</b>{group.reason}{group.multi && <small>여러 개 선택 가능</small>}</legend>
            <div>
              {group.options.map((option) => {
                const on = selected[group.slot]?.includes(option.value) ?? false;
                return <button type="button" key={option.id} className={on ? 'target-chip selected' : 'target-chip'} aria-pressed={on} onClick={() => toggle(group, option.value)}>{option.label}</button>;
              })}
            </div>
          </fieldset>
        ))}
        <footer>
          <button type="button" className="panel-button" onClick={rewrite}>질문 다시 쓰기</button>
          <button type="button" className="panel-button primary" disabled={!complete} onClick={submit}>선택 완료</button>
        </footer>
      </section>
    </Frame>
  );
}
