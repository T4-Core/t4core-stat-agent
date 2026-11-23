// 실행 기록. 다시 테스트는 입력칸에 넣기만 하고, 결과 보기는 저장된 결과를 엽니다.
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useNavigate } from 'react-router-dom';
import { getRunnerPhase, requestDraft, subscribeRunnerPhase } from '../runner/draft';
import { useAuth } from '../supabase/auth';
import { fetchHistory, type HistoryEntry } from '../supabase/history';

export function formatDateTime(value: string) {
  const date = new Date(value);
  const pad = (number: number) => String(number).padStart(2, '0');
  return `${date.getFullYear()}.${pad(date.getMonth() + 1)}.${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function HistoryPage() {
  const { displayName } = useAuth();
  const navigate = useNavigate();
  const phase = useSyncExternalStore(subscribeRunnerPhase, getRunnerPhase);
  const [scope, setScope] = useState<'all' | 'mine'>('all');
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const request = useRef(0);
  const busy = phase === 'starting' || phase === 'running' || phase === 'paused';

  const load = useCallback(async (offset: number) => {
    const id = request.current + 1;
    request.current = id;
    setLoading(true);
    setError('');
    try {
      const result = await fetchHistory(offset, scope === 'mine' ? displayName : null);
      if (request.current !== id) return;
      setEntries((current) => (offset === 0 ? result.entries : [...current, ...result.entries]));
      setHasMore(result.hasMore);
    } catch (cause) {
      if (request.current === id) setError(cause instanceof Error ? cause.message : 'History를 불러오지 못했습니다.');
    } finally {
      if (request.current === id) setLoading(false);
    }
  }, [displayName, scope]);

  useEffect(() => {
    void load(0);
    return () => { request.current += 1; };
  }, [load]);

  const retest = (entry: HistoryEntry) => {
    if (requestDraft(entry.queries)) navigate('/query-test');
  };

  return (
    <section className="adm-history">
      <header className="adm-report-head">
        <div>
          <h1>History</h1>
          <p>다시 테스트는 쿼리를 입력칸에 불러오기만 하고, 결과 보기는 그때 저장된 결과를 엽니다.</p>
        </div>
        <span className="adm-grow" />
        <div className="adm-tabs" role="group" aria-label="기록 범위">
          <button type="button" className={scope === 'all' ? 'is-on' : ''} aria-pressed={scope === 'all'} onClick={() => setScope('all')}>팀 전체</button>
          <button type="button" className={scope === 'mine' ? 'is-on' : ''} aria-pressed={scope === 'mine'} onClick={() => setScope('mine')}>내 기록</button>
        </div>
      </header>

      {busy && <p className="adm-notice" role="status">쿼리 실행 중에는 다시 테스트를 할 수 없습니다. 결과 보기는 사용할 수 있습니다.</p>}
      {error && <p className="adm-error" role="alert">{error}</p>}

      <div className="adm-history-table">
        <div className="adm-history-row is-head"><span>날짜·시간</span><span>쿼리</span><span>실행자</span><span /></div>
        {entries.map((entry) => {
          const others = entry.queries.length - 1;
          const skipped = entry.totalCount - entry.queries.length;
          const name = `${formatDateTime(entry.createdAt)} ${entry.owner}의 실행`;
          return (
            <div key={entry.id} className="adm-history-row">
              <span className="adm-history-date">{formatDateTime(entry.createdAt)}</span>
              <span className="adm-history-query">
                <b title={entry.queries[0]}>{entry.queries[0]}</b>
                {others > 0 && <em>외 {others}개</em>}
                {skipped > 0 && <small>건너뛴 {skipped}개 제외</small>}
              </span>
              <span className="adm-history-owner">{entry.owner}</span>
              <span className="adm-history-actions">
                <button type="button" className="adm-button is-outline" disabled={busy} aria-label={`${name} 다시 테스트`} onClick={() => retest(entry)}>다시 테스트</button>
                <button type="button" className="adm-button is-compact" aria-label={`${name} 결과 보기`} onClick={() => navigate(`/history/${entry.id}`)}>결과 보기</button>
              </span>
            </div>
          );
        })}
        {!loading && entries.length === 0 && !error && <p className="adm-issue-empty">{scope === 'mine' ? '내 실행 기록이 없습니다.' : '실행 기록이 없습니다.'}</p>}
        {loading && <p className="adm-issue-empty" role="status">불러오는 중입니다.</p>}
      </div>
      {hasMore && !loading && <button type="button" className="adm-button is-outline adm-history-more" onClick={() => void load(entries.length)}>더 보기</button>}
    </section>
  );
}
