# Supabase 설정 안내

프로젝트 담당자 한 명만 진행합니다. 팀원은 Supabase에 가입하지 않습니다. Supabase 화면의 메뉴 이름은 업데이트로 조금 달라질 수 있습니다.

## 1. 프로젝트 만들기

1. https://supabase.com 에 가입하고 **New project**를 누릅니다.
2. 이름은 `t4core-admin`, 지역은 **Northeast Asia (Seoul)** 을 고릅니다.
3. Database Password를 정하고 안전한 곳에 보관합니다. 팀원에게 공유하지 않습니다.
4. 무료(Free) 요금제로 생성하고 준비가 끝날 때까지 기다립니다.

## 2. DB 표와 권한 만들기

1. 왼쪽 메뉴에서 **SQL Editor**를 열고 새 쿼리를 만듭니다.
2. `admin/supabase/schema.sql` 전체를 복사해 붙여 넣고 **Run**을 누릅니다.
3. `Success. No rows returned`가 나오면 완료입니다.

위험한 작업이라는 확인 창이 나오면 실행해도 됩니다. 이 파일의 `drop`은 같은 이름의 권한 규칙과 트리거를 새로 만들기 위한 것이고, 데이터를 지우지 않습니다.

## 3. 외부 가입 막기

1. **Authentication**의 가입 설정(Sign In / Providers)을 엽니다.
2. **Allow new users to sign up**을 끄고 저장합니다.

꺼도 담당자가 만든 계정의 로그인은 정상 동작합니다.

## 4. 팀원 계정 만들기

**Authentication > Users > Add user > Create new user**에서 팀원마다 반복합니다.

- Email: `아이디@team.local` (예: `minji@team.local`)
- Password: 처음 쓸 비밀번호 (8자 이상)
- **Auto Confirm User**: 켬

아이디는 영문 소문자, 숫자, `.`, `_`, `-`만 사용합니다. 로그인 화면에는 `minji`만 입력합니다.

`team.local` 주소가 거부되면 `team.test`로 만들고, `admin/.env.local`의 `VITE_ADMIN_EMAIL_DOMAIN`도 같은 값으로 바꿉니다.

## 5. 연결 값 넣기

1. 상단의 **Connect** 또는 **Settings > API Keys**에서 Project URL과 **Publishable key**를 복사합니다.
2. `admin/.env.local`에 넣습니다.

```env
VITE_SUPABASE_URL=https://프로젝트주소.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_로_시작하는_값
```

3. `npm run admin`을 다시 실행하고 로그인합니다.

`sb_secret_`으로 시작하는 키나 `service_role` 키는 모든 데이터에 접근할 수 있으므로 **절대 넣거나 공유하지 마세요.**

## 6. 팀원에게 전달할 것

- 관리자 페이지 코드
- 위의 URL과 Publishable key
- 각자의 아이디와 처음 비밀번호 (로그인 후 사이드바에서 변경)

## 용량 관리

관리자 페이지는 DB가 300MB가 되면 경고하고 400MB가 되면 저장을 멈춥니다. 공간이 필요하면 SQL Editor에서 실행합니다.

```sql
-- 30일이 지난 쿼리의 상세 내용만 삭제 (통계와 오류 목록은 유지)
select public.adm_purge_old_details(30);
```

```sql
-- 지운 공간을 실제로 돌려받기 (위 명령과 따로 실행)
vacuum full public.adm_test_runs;
```

Supabase 프로젝트는 약 1주일간 사용이 적으면 일시 중지될 수 있습니다. 데이터는 유지되며 Supabase 화면에서 다시 시작하면 됩니다.
