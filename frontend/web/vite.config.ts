import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

// 백엔드 주소는 .env.local 에서만 읽습니다. 폴더를 옮겨도 이 파일은 고칠 필요가 없습니다.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const backendUrl = env.BACKEND_URL || 'http://localhost:8000';
  const apiBasePath = env.VITE_API_BASE_PATH || '/api/v1';
  const target = { target: backendUrl, changeOrigin: true };
  const proxy = { [apiBasePath]: target, '/health': target };

  return {
    plugins: [react()],
    // 앱 입구만 검색합니다. 임시 시안 character/index.html 은 앱에 포함하지 않습니다.
    optimizeDeps: { entries: ['index.html'] },
    server: { port: 5173, proxy },
    preview: { port: 4173, proxy },
  };
});
