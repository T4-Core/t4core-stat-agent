// 로그인 후 공통 틀: 왼쪽 사이드바 + 오른쪽 내용
import { Outlet, useLocation } from 'react-router-dom';
import { QueryTestPage } from '../pages/QueryTestPage';
import { AdminSidebar } from './AdminSidebar';

export function AdminLayout() {
  const { pathname } = useLocation();
  const onQueryTest = pathname === '/query-test';
  return (
    <div className="adm-shell">
      <div className="adm-app adm-with-sidebar">
        <AdminSidebar />
        <main className="adm-content">
          {/* 다른 메뉴를 봐도 실행 중인 쿼리가 끊기지 않도록 화면을 숨기기만 합니다. */}
          <div className="adm-keep" hidden={!onQueryTest}><QueryTestPage /></div>
          {!onQueryTest && <Outlet />}
        </main>
      </div>
    </div>
  );
}
