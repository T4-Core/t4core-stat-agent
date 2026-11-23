/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_PATH?: string;
  readonly VITE_USE_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// plotly.js-dist-min 은 타입을 제공하지 않아 이 앱에서 쓰는 함수만 선언합니다.
declare module 'plotly.js-dist-min' {
  const Plotly: {
    newPlot(element: HTMLElement, data: unknown[], layout?: Record<string, unknown>, config?: Record<string, unknown>): Promise<unknown>;
    purge(element: HTMLElement): void;
    downloadImage(element: HTMLElement, options: Record<string, unknown>): Promise<unknown>;
  };
  export default Plotly;
}
