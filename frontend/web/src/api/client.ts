// 백엔드 요청의 공통 처리. 주소는 환경변수에서만 가져옵니다.
export const API_BASE_PATH = (import.meta.env.VITE_API_BASE_PATH || '/api/v1').replace(/\/$/, '');
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

// 통계 답변은 여러 단계를 거쳐 오래 걸릴 수 있습니다.
const REQUEST_TIMEOUT_MS = 180_000;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly aborted = false,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function readDetail(body: unknown): string | null {
  if (typeof body !== 'object' || body === null || !('detail' in body)) return null;
  const { detail } = body;
  return typeof detail === 'string' ? detail : JSON.stringify(detail);
}

function friendlyMessage(status: number, detail: string | null) {
  if (status === 503) return 'HCX 설정을 확인해 주세요. 백엔드가 답변 모델을 호출하지 못했어요.';
  if (status === 502) return '답변 모델 호출에 실패했어요. 잠시 후 다시 시도해 주세요.';
  if (status === 409) return detail ?? '백엔드의 통계 데이터가 아직 준비되지 않았어요.';
  if (status === 404) return detail ?? '요청한 자료를 찾지 못했어요.';
  return detail ?? `요청에 실패했습니다. (${status})`;
}

export async function postJson<TResponse>(path: string, body: unknown, signal?: AbortSignal): Promise<TResponse> {
  const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${API_BASE_PATH}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    });
  } catch {
    if (signal?.aborted) throw new ApiError('요청을 중단했어요.', undefined, true);
    if (timeout.aborted) throw new ApiError('응답 시간이 너무 오래 걸려 기다림을 멈췄어요. 서버 작업은 계속될 수 있어요.');
    throw new ApiError('백엔드에 연결하지 못했습니다. 서버가 켜져 있는지 확인해 주세요.');
  }

  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(friendlyMessage(response.status, readDetail(data)), response.status);
  return data as TResponse;
}

/** GET 요청 (세션 복구처럼 짧은 조회). 실패하면 ApiError */
export async function getJson<TResponse>(path: string, signal?: AbortSignal): Promise<TResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_PATH}${path}`, { signal: signal ?? AbortSignal.timeout(10_000) });
  } catch {
    throw new ApiError('백엔드에 연결하지 못했습니다.', undefined, signal?.aborted ?? false);
  }
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(friendlyMessage(response.status, readDetail(data)), response.status);
  return data as TResponse;
}

export async function checkHealth() {
  try {
    const response = await fetch('/health', { signal: AbortSignal.timeout(5_000) });
    if (!response.ok) return false;
    const data = (await response.json()) as { status?: string };
    return data.status === 'ok';
  } catch {
    return false;
  }
}
