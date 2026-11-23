// 범위 밖 질문과 오류 안내입니다. (Figma 시안이 없어 기존 빈 화면 디자인을 사용)
import { useEffect } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import { Character } from '../character';
import { Frame, QueryPill } from '../components/Layout';
import { routeForRun, updateRun, useRun } from '../store/history';

export function NoticePage() {
  const { id } = useParams();
  const run = useRun(id);
  const navigate = useNavigate();

  useEffect(() => {
    if (run && run.status !== 'error' && run.status !== 'out_of_scope') navigate(routeForRun(run), { replace: true });
  }, [navigate, run]);

  if (!run) return <Navigate to="/" replace />;

  const isError = run.status === 'error';
  const retry = () => {
    updateRun(run.id, { status: 'pending', sentAt: undefined, message: undefined });
    navigate(`/generating/${run.id}`, { replace: true });
  };

  return (
    <Frame variant="generating">
      <QueryPill className="generating-pill" question={run.question} />
      <Character className="generating-sloth" size="L" motion="error" />
      <section className="notice" role={isError ? 'alert' : 'status'}>
        <h1>{isError ? '답변을 가져오지 못했어요' : '통계로 답하기 어려운 질문이에요'}</h1>
        <p>{run.message ?? '질문을 바꿔 다시 시도해 주세요.'}</p>
        <div>
          <Link className="notice-button" to="/">새 질문하기</Link>
          {isError && <button type="button" className="notice-button primary" onClick={retry}>다시 시도</button>}
        </div>
      </section>
    </Frame>
  );
}
