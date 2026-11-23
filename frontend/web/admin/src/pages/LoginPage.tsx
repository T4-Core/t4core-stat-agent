// 로그인 화면 (Figma 01 로그인)
import { useState, type FormEvent } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { Character } from '../../../src/character';
import { useAuth } from '../supabase/auth';
import { isSupabaseConfigured } from '../supabase/client';

export function LoginPage() {
  const { user, loading, signIn } = useAuth();
  const navigate = useNavigate();
  const [id, setId] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  if (!loading && user) return <Navigate to="/query-test" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!id.trim() || !password) {
      setError('아이디와 비밀번호를 입력해 주세요.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await signIn(id, password);
      navigate('/query-test', { replace: true });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '로그인하지 못했습니다.');
      setBusy(false);
    }
  }

  return (
    <main className="adm-shell">
      <div className="adm-app adm-login-app">
        <form className="adm-login-card" onSubmit={submit} noValidate>
          <Character motion="idle" size="S" />
          <div className="adm-login-title">
            <h1>T4core 관리자 콘솔</h1>
            <p>팀원 계정으로 로그인해 주세요.</p>
          </div>
          {!isSupabaseConfigured && (
            <p className="adm-notice" role="status">Supabase 연결 전입니다. admin/.env.local 에 URL과 공개용 키를 넣어 주세요.</p>
          )}
          <label className="adm-field">
            <span>아이디</span>
            <input value={id} onChange={(e) => setId(e.target.value)} placeholder="팀원 ID" autoComplete="username" autoCapitalize="none" spellCheck={false} autoFocus />
          </label>
          <label className="adm-field">
            <span>비밀번호</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="비밀번호 입력" autoComplete="current-password" />
          </label>
          {error && <p className="adm-error" role="alert">{error}</p>}
          <button className="adm-button" type="submit" disabled={busy || !isSupabaseConfigured}>
            {busy ? '로그인 중...' : '로그인'}
          </button>
        </form>
      </div>
    </main>
  );
}
