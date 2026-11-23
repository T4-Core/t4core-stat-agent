import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

// 관리자 페이지 전용 서버 설정입니다. 기존 화면의 vite.config.ts 와 독립적으로 동작합니다.
const adminRoot = fileURLToPath(new URL('.', import.meta.url));
const frontendRoot = fileURLToPath(new URL('..', import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, adminRoot, '');
  const backendUrl = env.BACKEND_URL || 'http://localhost:8000';
  const apiBasePath = env.VITE_API_BASE_PATH || '/api/v1';
  const target = { target: backendUrl, changeOrigin: true };
  const proxy = { [apiBasePath]: target, '/health': target };

  return {
    root: adminRoot,
    envDir: adminRoot,
    // 3D 캐릭터 파일은 기존 화면의 public 폴더에 있습니다.
    publicDir: `${frontendRoot}public`,
    // 기존 개발 서버와 동시에 켜도 충돌하지 않도록 캐시를 따로 씁니다.
    cacheDir: `${frontendRoot}node_modules/.vite-admin`,
    plugins: [react()],
    optimizeDeps: { entries: ['index.html', 'preview.html'] },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      rollupOptions: { input: { main: `${adminRoot}index.html`, preview: `${adminRoot}preview.html` } },
    },
    server: { port: 5174, strictPort: true, proxy, fs: { allow: [frontendRoot] } },
    preview: { port: 4174, strictPort: true, proxy },
  };
});
