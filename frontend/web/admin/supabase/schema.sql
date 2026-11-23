-- T4core 관리자 콘솔 DB 설정
-- Supabase > SQL Editor 에 전체를 붙여 넣고 한 번 실행합니다. 다시 실행해도 데이터는 지워지지 않습니다.
-- 모든 이름은 adm_ 로 시작하며, 쓰기는 아래 함수로만 할 수 있습니다.

begin;

-- 1. 표 ----------------------------------------------------------------------

-- 팀원 (Supabase 계정을 만들면 자동으로 추가됩니다)
create table if not exists public.adm_profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  login_id text not null,
  created_at timestamptz not null default now()
);

-- 한 번에 실행한 쿼리 묶음
create table if not exists public.adm_test_batches (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references public.adm_profiles (id) on delete set null,
  owner_login text not null,
  title text not null check (char_length(title) between 1 and 200),
  total_count integer not null check (total_count >= 1),
  created_at timestamptz not null default now()
);

-- 쿼리 하나의 실행 결과. detail 은 중간 단계를 줄여 저장한 값입니다.
create table if not exists public.adm_test_runs (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null references public.adm_test_batches (id) on delete cascade,
  position integer not null check (position >= 0),
  query text not null check (char_length(query) between 1 and 2000),
  status text not null check (status in ('ok', 'needs_clarification', 'needs_selection', 'out_of_scope', 'error')),
  qa_status text check (qa_status in ('ok', 'warned', 'stopped')),
  has_answer boolean not null default false,
  chart_count integer not null default 0 check (chart_count >= 0),
  timings jsonb,
  detail jsonb check (detail is null or octet_length(detail::text) <= 262144),
  created_at timestamptz not null default now(),
  unique (batch_id, position)
);

-- 같은 종류의 오류 묶음. 해결 체크는 이 묶음 단위로 합니다.
create table if not exists public.adm_issue_groups (
  id uuid primary key default gen_random_uuid(),
  fingerprint text not null unique,
  module text not null check (module in ('analysis', 'search', 'm2', 'm3', 'm5', 'm6', 'qa')),
  point text not null default '',
  kind text not null default '',
  severity text not null check (severity in ('warning', 'error')),
  path_pattern text not null default '',
  message text not null,
  resolved boolean not null default false,
  resolved_by uuid references public.adm_profiles (id) on delete set null,
  resolved_by_login text,
  resolved_at timestamptz,
  created_at timestamptz not null default now()
);

-- 어떤 쿼리에서 어떤 오류 묶음이 몇 번 나왔는지
create table if not exists public.adm_run_issues (
  run_id uuid not null references public.adm_test_runs (id) on delete cascade,
  group_id uuid not null references public.adm_issue_groups (id) on delete cascade,
  occurrences integer not null default 1 check (occurrences >= 1),
  sample_path text,
  primary key (run_id, group_id)
);

create index if not exists adm_test_runs_created_idx on public.adm_test_runs (created_at desc);
create index if not exists adm_run_issues_group_idx on public.adm_run_issues (group_id);
create index if not exists adm_issue_groups_module_idx on public.adm_issue_groups (module);
create index if not exists adm_test_batches_owner_idx on public.adm_test_batches (owner_id);

-- 2. 통계 뷰 (읽는 사람의 권한으로 동작) --------------------------------------

create or replace view public.adm_issue_group_stats with (security_invoker = true) as
select
  g.id, g.module, g.point, g.kind, g.severity, g.path_pattern, g.message,
  g.resolved, g.resolved_by_login, g.resolved_at,
  count(*)::integer as run_count,
  sum(ri.occurrences)::integer as occurrence_count,
  min(r.created_at) as first_seen_at,
  max(r.created_at) as last_seen_at,
  (count(*) filter (where g.resolved and r.created_at > g.resolved_at))::integer as runs_after_resolved
from public.adm_issue_groups g
join public.adm_run_issues ri on ri.group_id = g.id
join public.adm_test_runs r on r.id = ri.run_id
group by g.id;

create or replace view public.adm_module_error_stats with (security_invoker = true) as
select
  module,
  count(*)::integer as group_count,
  (count(*) filter (where resolved))::integer as resolved_group_count,
  sum(occurrence_count)::integer as occurrence_count,
  (coalesce(sum(occurrence_count) filter (where resolved), 0))::integer as resolved_occurrence_count
from public.adm_issue_group_stats
group by module;

-- 3. 용량 보호 ----------------------------------------------------------------

-- 무료 한도 500MB 전에 300MB 경고, 400MB 저장 중단
create or replace function public.adm_storage_limits()
returns table (warn_bytes bigint, block_bytes bigint)
language sql immutable set search_path = ''
as $$ select 300::bigint * 1024 * 1024, 400::bigint * 1024 * 1024 $$;

create or replace function public.adm_storage_usage()
returns table (used_bytes bigint, warn_bytes bigint, block_bytes bigint, state text)
language sql stable security definer set search_path = ''
as $$
  select u.used, l.warn_bytes, l.block_bytes,
    case when u.used >= l.block_bytes then 'blocked' when u.used >= l.warn_bytes then 'warning' else 'ok' end
  from (select pg_catalog.pg_database_size(pg_catalog.current_database())::bigint as used) u
  cross join public.adm_storage_limits() l
$$;

-- 4. 쓰기 함수 ----------------------------------------------------------------

create or replace function public.adm_create_batch(p_title text, p_total integer)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  v_user uuid := auth.uid();
  v_login text;
  v_id uuid;
begin
  if v_user is null then raise exception 'ADMIN_LOGIN_REQUIRED' using errcode = '28000'; end if;
  select login_id into v_login from public.adm_profiles where id = v_user;
  if v_login is null then raise exception 'ADMIN_PROFILE_MISSING' using errcode = 'P0001'; end if;
  if (select s.state from public.adm_storage_usage() s) = 'blocked' then
    raise exception 'ADMIN_STORAGE_FULL' using errcode = 'P0001';
  end if;
  insert into public.adm_test_batches (owner_id, owner_login, title, total_count)
  values (v_user, v_login, p_title, p_total)
  returning id into v_id;
  return v_id;
end;
$$;

-- 쿼리 결과와 오류를 한 번에 저장합니다. 같은 순번을 다시 보내면 중복 저장하지 않습니다.
create or replace function public.adm_save_test_run(
  p_batch_id uuid,
  p_position integer,
  p_query text,
  p_status text,
  p_qa_status text,
  p_has_answer boolean,
  p_chart_count integer,
  p_timings jsonb,
  p_detail jsonb,
  p_issues jsonb
)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  v_user uuid := auth.uid();
  v_run uuid;
  v_group uuid;
  v_item jsonb;
  v_module text;
  v_point text;
  v_kind text;
  v_severity text;
  v_path text;
  v_pattern text;
  v_message text;
  v_count integer;
  v_issues jsonb := coalesce(p_issues, '[]'::jsonb);
begin
  if v_user is null then raise exception 'ADMIN_LOGIN_REQUIRED' using errcode = '28000'; end if;
  if not exists (select 1 from public.adm_test_batches b where b.id = p_batch_id and b.owner_id = v_user) then
    raise exception 'ADMIN_BATCH_NOT_OWNED' using errcode = '42501';
  end if;
  if pg_catalog.jsonb_typeof(v_issues) <> 'array' or pg_catalog.jsonb_array_length(v_issues) > 5000 then
    raise exception 'ADMIN_INVALID_ISSUES' using errcode = '22023';
  end if;

  select r.id into v_run from public.adm_test_runs r where r.batch_id = p_batch_id and r.position = p_position;
  if v_run is not null then return v_run; end if;

  if (select s.state from public.adm_storage_usage() s) = 'blocked' then
    raise exception 'ADMIN_STORAGE_FULL' using errcode = 'P0001';
  end if;

  insert into public.adm_test_runs (batch_id, position, query, status, qa_status, has_answer, chart_count, timings, detail)
  values (p_batch_id, p_position, p_query, p_status, p_qa_status, coalesce(p_has_answer, false), coalesce(p_chart_count, 0), p_timings, p_detail)
  returning id into v_run;

  for v_item in select value from pg_catalog.jsonb_array_elements(v_issues) loop
    v_module := v_item ->> 'module';
    v_point := coalesce(v_item ->> 'point', '');
    v_kind := pg_catalog.left(coalesce(v_item ->> 'kind', ''), 100);
    v_severity := v_item ->> 'severity';
    v_path := pg_catalog.left(coalesce(v_item ->> 'path', ''), 500);
    v_pattern := pg_catalog.regexp_replace(v_path, '\[\d+\]', '[]', 'g');
    v_message := pg_catalog.left(coalesce(nullif(v_item ->> 'message', ''), '메시지 없음'), 1000);
    v_count := greatest(coalesce((v_item ->> 'count')::integer, 1), 1);

    insert into public.adm_issue_groups (fingerprint, module, point, kind, severity, path_pattern, message)
    values (
      pg_catalog.md5(pg_catalog.concat_ws(pg_catalog.chr(31), v_module, v_point, v_kind, v_severity, v_pattern, v_message)),
      v_module, v_point, v_kind, v_severity, v_pattern, v_message
    )
    on conflict (fingerprint) do update set fingerprint = excluded.fingerprint
    returning id into v_group;

    insert into public.adm_run_issues (run_id, group_id, occurrences, sample_path)
    values (v_run, v_group, v_count, v_path)
    on conflict (run_id, group_id) do update
      set occurrences = public.adm_run_issues.occurrences + excluded.occurrences;
  end loop;

  return v_run;
end;
$$;

-- 해결 체크. 팀원 누구나 할 수 있고, 누가 체크했는지 남습니다.
create or replace function public.adm_set_issue_resolved(p_group_id uuid, p_resolved boolean)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  v_user uuid := auth.uid();
  v_login text;
begin
  if v_user is null then raise exception 'ADMIN_LOGIN_REQUIRED' using errcode = '28000'; end if;
  select login_id into v_login from public.adm_profiles where id = v_user;
  if v_login is null then raise exception 'ADMIN_PROFILE_MISSING' using errcode = 'P0001'; end if;
  update public.adm_issue_groups
  set resolved = p_resolved,
      resolved_by = case when p_resolved then v_user end,
      resolved_by_login = case when p_resolved then v_login end,
      resolved_at = case when p_resolved then now() end
  where id = p_group_id;
  if not found then raise exception 'ADMIN_GROUP_NOT_FOUND' using errcode = 'P0002'; end if;
end;
$$;

-- 용량 정리: 오래된 쿼리의 상세 내용만 지우고 통계는 남깁니다.
-- 팀원 화면에서는 호출할 수 없고 SQL Editor 에서만 실행합니다.
create or replace function public.adm_purge_old_details(p_days integer default 30)
returns integer
language plpgsql security definer set search_path = ''
as $$
declare
  v_count integer;
begin
  if p_days is null or p_days < 1 then raise exception 'ADMIN_INVALID_DAYS' using errcode = '22023'; end if;
  update public.adm_test_runs
  set detail = null
  where detail is not null and created_at < now() - pg_catalog.make_interval(days => p_days);
  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

-- 5. 팀원 자동 등록 -----------------------------------------------------------

create or replace function public.adm_handle_new_user()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  insert into public.adm_profiles (id, login_id)
  values (new.id, pg_catalog.split_part(coalesce(new.email, new.id::text), '@', 1))
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists adm_on_auth_user_created on auth.users;
create trigger adm_on_auth_user_created
  after insert on auth.users
  for each row execute function public.adm_handle_new_user();

-- 이 파일을 실행하기 전에 만든 계정도 등록합니다.
insert into public.adm_profiles (id, login_id)
select u.id, split_part(coalesce(u.email, u.id::text), '@', 1)
from auth.users u
on conflict (id) do nothing;

-- 6. 접근 권한: 로그인한 팀원만 읽고, 쓰기는 함수로만 ---------------------------

alter table public.adm_profiles enable row level security;
alter table public.adm_test_batches enable row level security;
alter table public.adm_test_runs enable row level security;
alter table public.adm_issue_groups enable row level security;
alter table public.adm_run_issues enable row level security;

drop policy if exists adm_profiles_read on public.adm_profiles;
create policy adm_profiles_read on public.adm_profiles for select to authenticated using (true);
drop policy if exists adm_batches_read on public.adm_test_batches;
create policy adm_batches_read on public.adm_test_batches for select to authenticated using (true);
drop policy if exists adm_batches_delete_own on public.adm_test_batches;
create policy adm_batches_delete_own on public.adm_test_batches for delete to authenticated using (owner_id = (select auth.uid()));
drop policy if exists adm_runs_read on public.adm_test_runs;
create policy adm_runs_read on public.adm_test_runs for select to authenticated using (true);
drop policy if exists adm_groups_read on public.adm_issue_groups;
create policy adm_groups_read on public.adm_issue_groups for select to authenticated using (true);
drop policy if exists adm_run_issues_read on public.adm_run_issues;
create policy adm_run_issues_read on public.adm_run_issues for select to authenticated using (true);

revoke all on table
  public.adm_profiles, public.adm_test_batches, public.adm_test_runs, public.adm_issue_groups, public.adm_run_issues,
  public.adm_issue_group_stats, public.adm_module_error_stats
from public, anon, authenticated;

grant select on table
  public.adm_profiles, public.adm_test_batches, public.adm_test_runs, public.adm_issue_groups, public.adm_run_issues,
  public.adm_issue_group_stats, public.adm_module_error_stats
to authenticated;
grant delete on table public.adm_test_batches to authenticated;

revoke all on function public.adm_storage_limits() from public, anon, authenticated;
revoke all on function public.adm_storage_usage() from public, anon, authenticated;
revoke all on function public.adm_create_batch(text, integer) from public, anon, authenticated;
revoke all on function public.adm_save_test_run(uuid, integer, text, text, text, boolean, integer, jsonb, jsonb, jsonb) from public, anon, authenticated;
revoke all on function public.adm_set_issue_resolved(uuid, boolean) from public, anon, authenticated;
revoke all on function public.adm_purge_old_details(integer) from public, anon, authenticated;
revoke all on function public.adm_handle_new_user() from public, anon, authenticated;

grant execute on function public.adm_storage_usage() to authenticated;
grant execute on function public.adm_create_batch(text, integer) to authenticated;
grant execute on function public.adm_save_test_run(uuid, integer, text, text, text, boolean, integer, jsonb, jsonb, jsonb) to authenticated;
grant execute on function public.adm_set_issue_resolved(uuid, boolean) to authenticated;

commit;
