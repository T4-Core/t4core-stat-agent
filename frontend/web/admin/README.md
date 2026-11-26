# T4core 관리자 콘솔

쿼리 테스트와 모듈별 에러 통계를 보는 데모·테스트용 페이지입니다. 기존 사용자 화면과 분리되어 있습니다..

## 실행

```bash
# frontend/web 폴더에서
npm install                              # 처음 한 번
cp admin/.env.example admin/.env.local   # 처음 한 번, 이후 Supabase 값 입력
npm run admin                            # http://localhost:5174
```

## 설정 값

`admin/.env.local`에 Supabase의 URL과 공개용 키만 넣습니다. `service_role` 또는 `secret` 키는 절대 넣지 마세요.

## Supabase와 팀원 계정

프로젝트 생성, DB 설정, 팀원 계정 추가는 [supabase/SETUP.md](supabase/SETUP.md)를 순서대로 따라 하면 됩니다.

## 삭제 방법

1. `admin/` 폴더를 지웁니다.
2. `package.json`에서 `admin`, `build:admin` 명령과 `@supabase/supabase-js`를 지운 뒤 `npm install`을 실행합니다.
3. Supabase 프로젝트를 삭제합니다.
