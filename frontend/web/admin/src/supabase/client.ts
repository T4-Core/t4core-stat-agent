// Supabase 연결. 주소와 공개용 키는 admin/.env.local 에서만 읽습니다.
import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL?.trim();
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim();

export const isSupabaseConfigured = Boolean(url && key);

export const supabase = url && key
  ? createClient(url, key, { auth: { storageKey: 't4core-admin-auth' } })
  : null;
