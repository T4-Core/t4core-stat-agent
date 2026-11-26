// 관리자 페이지의 주소와 로그인 여부에 따른 이동을 정합니다.
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { AdminLayout } from './components/AdminLayout';
import { ErrorReportPage } from './pages/ErrorReportPage';
import { HistoryPage } from './pages/HistoryPage';
import { HistoryResultPage } from './pages/HistoryResultPage';
import { LoginPage } from './pages/LoginPage';
import { AuthProvider, useAuth } from './supabase/auth';

function RequireLogin() {
  const { user, loading } = useAuth();
  if (loading) return <div className="adm-loading" role="status">로그인 정보를 확인하는 중입니다.</div>;
  return user ? <Outlet /> : <Navigate to="/login" replace />;
}

export default function AdminApp() {
  return (
    <AuthProvider>
      <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '') || '/'}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireLogin />}>
            <Route element={<AdminLayout />}>
              {/* 쿼리 테스트 화면은 AdminLayout 이 항상 띄워 둡니다. */}
              <Route path="/query-test" element={null} />
              <Route path="/errors" element={<ErrorReportPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/history/:batchId" element={<HistoryResultPage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/query-test" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
