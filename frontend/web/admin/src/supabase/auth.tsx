// 로그인 상태를 관리합니다. 팀원은 아이디만 입력하고, 이메일 형식 변환은 여기서 처리합니다.
import type { User } from '@supabase/supabase-js';
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { supabase } from './client';

const EMAIL_DOMAIN = import.meta.env.VITE_ADMIN_EMAIL_DOMAIN?.trim() || 'team.local';
const ID_PATTERN = /^[a-z0-9._-]+$/;

type AuthValue = {
  user: User | null;
  loading: boolean;
  displayName: string;
  signIn: (id: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  changePassword: (current: string, next: string) => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

function toEmail(id: string) {
  const value = id.trim().toLowerCase();
  if (value.includes('@')) return value;
  if (!ID_PATTERN.test(value)) throw new Error('아이디는 영문 소문자, 숫자, . _ - 만 사용할 수 있습니다.');
  return `${value}@${EMAIL_DOMAIN}`;
}

function toMessage(error: { code?: string; status?: number }) {
  if (error.code === 'invalid_credentials') return '아이디 또는 비밀번호가 올바르지 않습니다.';
  if (error.code === 'weak_password') return '새 비밀번호가 너무 단순합니다.';
  if (error.code === 'same_password') return '현재 비밀번호와 다른 비밀번호를 입력해 주세요.';
  if (error.code === 'over_request_rate_limit') return '시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.';
  if (!error.status) return 'Supabase에 연결할 수 없습니다. 인터넷 연결과 설정을 확인해 주세요.';
  return '요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.';
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(Boolean(supabase));

  useEffect(() => {
    if (!supabase) return;
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
      setLoading(false);
    });
    return () => data.subscription.unsubscribe();
  }, []);

  const value = useMemo<AuthValue>(() => ({
    user,
    loading,
    displayName: user?.email?.split('@')[0] ?? '',
    async signIn(id, password) {
      if (!supabase) throw new Error('Supabase 설정이 필요합니다.');
      const email = toEmail(id);
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw new Error(toMessage(error));
    },
    async signOut() {
      await supabase?.auth.signOut({ scope: 'local' });
    },
    async changePassword(current, next) {
      if (!supabase || !user?.email) throw new Error('다시 로그인해 주세요.');
      const check = await supabase.auth.signInWithPassword({ email: user.email, password: current });
      if (check.error) {
        throw new Error(check.error.code === 'invalid_credentials' ? '현재 비밀번호가 올바르지 않습니다.' : toMessage(check.error));
      }
      const { error } = await supabase.auth.updateUser({ password: next });
      if (error) throw new Error(toMessage(error));
    },
  }), [user, loading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error('AuthProvider 안에서 사용해 주세요.');
  return value;
}
