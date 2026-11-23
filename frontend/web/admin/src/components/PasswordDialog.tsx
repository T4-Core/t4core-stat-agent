// 팀원이 처음 받은 비밀번호를 직접 바꾸는 창
import { useEffect, useState, type FormEvent } from 'react';
import { useAuth } from '../supabase/auth';

const MIN_LENGTH = 8;

export function PasswordDialog({ onClose }: { onClose: () => void }) {
  const { changePassword } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!current || !next) return setError('비밀번호를 모두 입력해 주세요.');
    if (next.length < MIN_LENGTH) return setError(`새 비밀번호는 ${MIN_LENGTH}자 이상이어야 합니다.`);
    if (next !== confirm) return setError('새 비밀번호가 서로 다릅니다.');
    setBusy(true);
    setError('');
    try {
      await changePassword(current, next);
      setDone(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '비밀번호를 바꾸지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="adm-dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <form className="adm-dialog" role="dialog" aria-modal="true" aria-labelledby="adm-password-title" onSubmit={submit} noValidate>
        <h2 id="adm-password-title">비밀번호 변경</h2>
        {done ? (
          <>
            <p className="adm-success" role="status">비밀번호를 변경했습니다.</p>
            <button className="adm-button" type="button" onClick={onClose}>닫기</button>
          </>
        ) : (
          <>
            <label className="adm-field"><span>현재 비밀번호</span><input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" autoFocus /></label>
            <label className="adm-field"><span>새 비밀번호</span><input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" placeholder={`${MIN_LENGTH}자 이상`} /></label>
            <label className="adm-field"><span>새 비밀번호 확인</span><input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" /></label>
            {error && <p className="adm-error" role="alert">{error}</p>}
            <div className="adm-dialog-actions">
              <button className="adm-button is-secondary" type="button" onClick={onClose}>취소</button>
              <button className="adm-button" type="submit" disabled={busy}>{busy ? '변경 중...' : '변경'}</button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}
