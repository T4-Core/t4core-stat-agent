// 주소별로 어떤 화면을 보여줄지 정합니다.
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { StageLayout } from './components/Layout';
import { ClarifyPage } from './pages/ClarifyPage';
import { GeneratingPage } from './pages/GeneratingPage';
import { HistoryPage } from './pages/HistoryPage';
import { MainPage } from './pages/MainPage';
import { NoticePage } from './pages/NoticePage';
import { ResultPage } from './pages/ResultPage';
import { SelectPage } from './pages/SelectPage';
import { ViewDetailPage } from './pages/ViewDetailPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<StageLayout />}>
          <Route index element={<MainPage />} />
          <Route path="generating/:id" element={<GeneratingPage />} />
          <Route path="select/:id" element={<SelectPage />} />
          <Route path="clarify/:id" element={<ClarifyPage />} />
          <Route path="notice/:id" element={<NoticePage />} />
          <Route path="result/:id" element={<ResultPage />} />
          <Route path="result/:id/tables/:viewNo" element={<ViewDetailPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
