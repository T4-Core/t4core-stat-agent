// 관리자 페이지 시작점. 기존 화면의 색상 값과 글꼴만 읽어 옵니다.
import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css';
import '../../src/styles/tokens.css';
import './styles/admin.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import AdminApp from './AdminApp';

createRoot(document.getElementById('admin-root')!).render(
  <StrictMode>
    <AdminApp />
  </StrictMode>,
);
