// 쿼리 테스트 화면 (Figma 02 입력, 03 실행 중, 04 되묻기, 05 결과)
import { useEffect, useState } from 'react';
import { PipelineSteps } from '../components/PipelineSteps';
import { QueryEditor } from '../components/QueryEditor';
import { QueryTable } from '../components/QueryTable';
import { ResultReport } from '../components/ResultReport';
import { badgeOf } from '../components/runView';
import { setRunnerPhase, subscribeDraft, type QueryDraft } from '../runner/draft';
import { useQueryRunner, type RunnerState } from '../runner/useQueryRunner';
import { useAuth } from '../supabase/auth';
import { getStorageUsage, type StorageUsage } from '../supabase/testRuns';

function headline(state: RunnerState) {
  const total = state.items.length;
  const estimate = `예상 HCX ${total * 3}~${total * 5}회`;
  if (state.phase === 'starting') return '백엔드와 저장 공간 확인 중';
  const item = state.items[state.current];
  const number = state.current + 1;
  if (state.phase === 'paused') return `${number} / ${total} 저장 실패 · 다음 쿼리를 시작하지 않았습니다`;
  if (item?.state === 'input') return `${number} / ${total} 입력 대기 · ${estimate}`;
  if (item?.state === 'saving') return `${number} / ${total} 팀 리포트에 저장 중 · ${estimate}`;
  return `${number} / ${total} 실행 중 · ${estimate}`;
}

export function QueryTestPage() {
  const { displayName } = useAuth();
  const { frameRef, ready, state, start, retrySave, skipSave, endEarly, reset, rerun } = useQueryRunner();
  const [large, setLarge] = useState(false);
  const [usage, setUsage] = useState<StorageUsage | null>(null);
  const [draft, setDraft] = useState<QueryDraft | null>(null);
  const idle = state.phase === 'idle';
  const done = state.phase === 'done';
  const live = !idle && !done;
  const item = state.items[Math.max(state.current, 0)];
  const waiting = item?.state === 'input';
  const badge = item ? badgeOf(item) : { label: '대기', tone: 'muted' };
  const finished = state.items.filter((entry) => entry.result || entry.state === 'skipped').length;
  const progress = state.items.length > 0 ? Math.round((finished / state.items.length) * 100) : 0;

  useEffect(() => {
    setRunnerPhase(state.phase);
  }, [state.phase]);

  useEffect(() => () => setRunnerPhase('idle'), []);

  // History에서 불러오면 결과 화면을 닫고 입력칸에 넣습니다. 실행은 하지 않습니다.
  useEffect(() => subscribeDraft((next) => {
    reset();
    setDraft(next);
  }), [reset]);

  useEffect(() => {
    if (!idle) return;
    let cancelled = false;
    void getStorageUsage().then((value) => { if (!cancelled) setUsage(value); }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [idle]);

  useEffect(() => {
    if (!live) setLarge(false);
  }, [live]);

  useEffect(() => {
    if (!large) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setLarge(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [large]);

  return (
    <section className="adm-query">
      {!done && (
        <header className="adm-run-header">
          <div className="adm-run-title">
            <h1>쿼리 테스트</h1>
            {idle ? <p>실제 사용자 흐름으로 쿼리를 실행하고 모든 중간 단계를 확인합니다.</p> : <p>{headline(state)}</p>}
            {live && <span className="adm-no-stop">실행 중지 기능 없음 · 시작한 쿼리는 끝까지 실행됩니다</span>}
          </div>
          {live && <div className="adm-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><i style={{ width: `${Math.max(progress, 3)}%` }} /></div>}
        </header>
      )}

      {/* 실행이 실패해도 입력한 질문이 사라지지 않도록 숨기기만 합니다. */}
      <QueryEditor hidden={!idle} draft={draft} ready={ready} usage={usage} error={state.error} onRun={(questions) => void start(questions)} />

      {state.phase === 'paused' && item && (
        <div className="adm-paused" role="alert">
          <p><b>{state.current + 1}번째 결과를 팀 DB에 저장하지 못했습니다.</b> {item.saveError}</p>
          <button type="button" className="adm-button is-compact" onClick={retrySave}>저장 다시 시도</button>
          {state.current < state.items.length - 1 && <button type="button" className="adm-button is-outline" onClick={skipSave}>저장 없이 다음 쿼리</button>}
          <button type="button" className="adm-button is-outline" onClick={endEarly}>여기서 끝내기</button>
        </div>
      )}

      {/* 사용자 화면은 실행 내내 유지되어야 해서 숨기기만 합니다. */}
      <div className="adm-live" hidden={!live}>
        <section className={`adm-preview${waiting ? ' is-waiting' : ''}${large ? ' is-large' : ''}`} aria-label="실제 사용자 화면">
          <header>
            <h2>실제 사용자 화면</h2>
            <span className="adm-grow" />
            <button type="button" className="adm-link-button" onClick={() => setLarge(!large)}>{large ? '작게 보기' : '크게 보기'}</button>
            <span className={`adm-badge is-${badge.tone}`}>{badge.label}</span>
          </header>
          <iframe ref={frameRef} src={`${import.meta.env.BASE_URL}preview.html`} title="실제 사용자 화면" />
        </section>
        {large && <div className="adm-preview-backdrop" onClick={() => setLarge(false)} />}
        {live && item && <PipelineSteps item={item} />}
      </div>

      {live && <QueryTable items={state.items} current={state.current} scroll />}

      {done && <ResultReport key={state.startedAt} items={state.items} startedAt={state.startedAt} owner={displayName} primaryLabel="새 테스트" onPrimary={reset} onRerun={rerun} />}
    </section>
  );
}
