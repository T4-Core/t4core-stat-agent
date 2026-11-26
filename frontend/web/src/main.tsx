// 프로그램 시작점: index.html 의 #root 에 React 앱을 붙입니다.
import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/tokens.css';
import './styles/global.css';
import './styles/main.css';
import './styles/flow.css';
import './styles/result.css';
import './styles/history.css';
import './styles/live.css';
import './styles/clarify.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
