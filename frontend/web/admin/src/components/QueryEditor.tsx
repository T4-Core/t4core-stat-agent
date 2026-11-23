// 쿼리 입력과 실행 전 확인 (Figma 02)
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import { decodeCsv, parseQuestions } from '../runner/csv';
import type { QueryDraft } from '../runner/draft';
import type { StorageUsage } from '../supabase/testRuns';

const MAX_QUESTION = 2000;

type Props = {
  hidden: boolean;
  draft: QueryDraft | null;
  ready: boolean;
  usage: StorageUsage | null;
  error: string;
  onRun: (questions: string[]) => void;
};

export function QueryEditor({ hidden, draft, ready, usage, error, onRun }: Props) {
  const [mode, setMode] = useState<'one' | 'many'>('one');
  const [value, setValue] = useState('');
  const [fileError, setFileError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);
  const linesRef = useRef<HTMLDivElement>(null);

  // History에서 고른 쿼리를 입력칸에 넣기만 합니다.
  useEffect(() => {
    if (!draft) return;
    setMode(draft.questions.length > 1 ? 'many' : 'one');
    setValue(draft.questions.join('\n'));
    setFileError('');
  }, [draft]);

  const questions = useMemo(() => {
    if (mode === 'one') {
      const text = value.replace(/\s+/g, ' ').trim();
      return text ? [text] : [];
    }
    return value.split('\n').map((line) => line.trim()).filter(Boolean);
  }, [mode, value]);
  const lineCount = Math.max(1, value.split('\n').length);
  const tooLong = questions.findIndex((item) => item.length > MAX_QUESTION);
  const count = questions.length;
  const blocked = usage?.state === 'blocked';
  const canRun = ready && count > 0 && tooLong < 0 && !blocked;

  const loadCsv = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const parsed = parseQuestions(decodeCsv(await file.arrayBuffer()));
      if (parsed.length === 0) {
        setFileError('CSV에서 질문을 찾지 못했습니다. 첫 번째 칸에 질문을 넣어 주세요.');
        return;
      }
      setFileError('');
      setMode('many');
      setValue(parsed.join('\n'));
    } catch {
      setFileError('CSV 파일을 읽지 못했습니다.');
    }
  };

  const run = () => {
    if (!canRun) return;
    if (count > 1 && !window.confirm(`쿼리 ${count}개를 실행할까요?\n예상 HCX 호출은 ${count * 3}~${count * 5}회이고, 시작하면 중지할 수 없습니다.`)) return;
    onRun(questions);
  };

  return (
    <div className="adm-editor-body" hidden={hidden}>
      <div className="adm-editor">
        <div className="adm-editor-head">
          <div className="adm-mode" role="group" aria-label="실행 방식">
            <button type="button" className={mode === 'one' ? 'is-on' : ''} aria-pressed={mode === 'one'} onClick={() => setMode('one')}>한 개</button>
            <button type="button" className={mode === 'many' ? 'is-on' : ''} aria-pressed={mode === 'many'} onClick={() => setMode('many')}>여러 개</button>
          </div>
          <span>{mode === 'many' ? `한 줄에 질문 하나씩 입력 · ${count}개` : '질문 하나를 입력해 주세요'}</span>
        </div>
        <div className={`adm-textarea${mode === 'many' ? ' has-lines' : ''}`}>
          {mode === 'many' && (
            <div className="adm-line-numbers" ref={linesRef} aria-hidden="true">
              {Array.from({ length: lineCount }, (_, index) => <span key={index}>{String(index + 1).padStart(2, '0')}</span>)}
            </div>
          )}
          <textarea
            value={value}
            wrap={mode === 'many' ? 'off' : 'soft'}
            onChange={(event) => setValue(event.target.value)}
            onScroll={(event) => { if (linesRef.current) linesRef.current.scrollTop = event.currentTarget.scrollTop; }}
            aria-label="테스트할 질문"
            placeholder={mode === 'many' ? '최근 5년 서울 출생아 수 추이 보여줘\n시도별 65세 이상 인구 비율 알려줘' : '예: 최근 5년 서울 출생아 수 추이 보여줘'}
          />
        </div>
        <div className="adm-editor-actions">
          <input ref={fileRef} type="file" accept=".csv,text/csv" hidden aria-label="CSV 파일 선택" onChange={(event) => void loadCsv(event)} />
          <button type="button" className="adm-button is-outline" onClick={() => fileRef.current?.click()}>CSV 불러오기</button>
          <button type="button" className="adm-text-button" onClick={() => { setValue(''); setFileError(''); }}>지우기 ›</button>
          {fileError && <span className="adm-inline-error" role="alert">{fileError}</span>}
          {tooLong >= 0 && <span className="adm-inline-error" role="alert">{tooLong + 1}번째 질문이 {MAX_QUESTION}자를 넘습니다.</span>}
        </div>
      </div>
      <aside className="adm-run-panel">
        <h2>실행 전 확인</h2>
        <div className="adm-estimate">
          <span>예상 HCX 호출</span>
          <strong>{count * 3} ~ {count * 5}회</strong>
          <small>쿼리 {count}개 × 쿼리당 3~5회</small>
        </div>
        <dl>
          <div><dt>실행 방식</dt><dd>실제 사용자 흐름</dd></div>
          <div><dt>차트</dt><dd>그리기 포함</dd></div>
          <div><dt>되묻기</dt><dd>화면에서 직접 선택</dd></div>
          <div><dt>표 값 충돌</dt><dd>화면에서 직접 선택</dd></div>
          <div><dt>기록</dt><dd>팀 리포트에 저장</dd></div>
        </dl>
        <span className="adm-grow" />
        {usage && usage.state !== 'ok' && (
          <p className="adm-error" role="alert">
            팀 DB 사용량 {Math.round(usage.used_bytes / 1024 / 1024)}MB. {blocked ? '저장 한도에 도달해 실행할 수 없습니다.' : '오래된 결과 정리가 필요합니다.'}
          </p>
        )}
        {error && <p className="adm-error" role="alert">{error}</p>}
        <div className="adm-warning">
          <b>실행을 시작하면 중지할 수 없어요</b>
          <p>현재 백엔드에 실행 중지 기능이 구현되어 있지 않습니다. 쿼리 수와 예상 HCX 호출 수를 확인하고 신중하게 실행해 주세요.</p>
        </div>
        <button type="button" className="adm-button" disabled={!canRun} onClick={run}>
          {ready ? `${count}개 쿼리 실행` : '화면 준비 중...'}
        </button>
      </aside>
    </div>
  );
}
