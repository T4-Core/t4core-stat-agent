// History의 결과 보기: 그때 저장된 결과를 실행 결과 화면으로 다시 보여줍니다. HCX를 호출하지 않습니다.
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ResultReport } from '../components/ResultReport';
import { requestDraft } from '../runner/draft';
import { fetchBatchResult } from '../supabase/history';

type Loaded = Awaited<ReturnType<typeof fetchBatchResult>>;

export function HistoryResultPage() {
  const { batchId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!batchId) return;
    let cancelled = false;
    setData(null);
    setError('');
    fetchBatchResult(batchId)
      .then((result) => { if (!cancelled) setData(result); })
      .catch((cause: unknown) => { if (!cancelled) setError(cause instanceof Error ? cause.message : '저장된 결과를 불러오지 못했습니다.'); });
    return () => { cancelled = true; };
  }, [batchId]);

  const retest = (questions: string[]) => {
    if (requestDraft(questions)) navigate('/query-test');
    else window.alert('쿼리 실행이 끝난 뒤 다시 테스트할 수 있습니다.');
  };

  if (!data) {
    return (
      <section className="adm-history">
        {error ? (
          <>
            <p className="adm-error" role="alert">{error}</p>
            <button type="button" className="adm-button is-outline adm-history-more" onClick={() => navigate('/history')}>History로</button>
          </>
        ) : <div className="adm-report-loading" role="status">저장된 결과를 불러오는 중입니다.</div>}
      </section>
    );
  }

  return (
    <section className="adm-history">
      <ResultReport
        items={data.items}
        startedAt={new Date(data.createdAt).getTime()}
        owner={data.owner}
        extraSkipped={Math.max(0, data.totalCount - data.items.length)}
        primaryLabel="History로"
        onPrimary={() => navigate('/history')}
        secondaryLabel="다시 테스트"
        onSecondary={() => retest(data.items.map((item) => item.question))}
        rerunMode="draft"
        onRerun={(question) => retest([question])}
      />
    </section>
  );
}
