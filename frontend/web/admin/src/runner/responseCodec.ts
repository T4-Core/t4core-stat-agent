// 백엔드 응답 전체를 압축해 저장합니다. 쿼리당 보통 10KB 안팎이라 중간 결과와 차트까지 다시 볼 수 있습니다.
import type { ChatResponse } from '../../../src/api/types';

const MAX_STORED_BYTES = 240_000;

// 차트 템플릿은 그림마다 10KB가 넘고 화면에 쓰지 않습니다.
const withoutTemplate = (key: string, value: unknown) => (key === 'template' && typeof value === 'object' ? undefined : value);

async function pipe(bytes: Uint8Array, transform: ReadableWritablePair<Uint8Array, Uint8Array>) {
  const stream = new Blob([bytes as BlobPart]).stream().pipeThrough(transform);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function toBase64(bytes: Uint8Array) {
  let text = '';
  for (let index = 0; index < bytes.length; index += 0x8000) text += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  return btoa(text);
}

export async function encodeResponses(responses: ChatResponse[]) {
  const json = new TextEncoder().encode(JSON.stringify(responses, withoutTemplate));
  return toBase64(await pipe(json, new CompressionStream('gzip') as unknown as ReadableWritablePair<Uint8Array, Uint8Array>));
}

export async function decodeResponses(encoded: string) {
  const bytes = Uint8Array.from(atob(encoded), (char) => char.charCodeAt(0));
  const json = await pipe(bytes, new DecompressionStream('gzip') as unknown as ReadableWritablePair<Uint8Array, Uint8Array>);
  return JSON.parse(new TextDecoder().decode(json)) as ChatResponse[];
}

/** 압축본을 저장합니다. 압축에 실패하거나 너무 크면 기존 요약 저장으로 돌아갑니다. */
export async function toStoredDetail(base: unknown, responses: ChatResponse[]): Promise<{ detail: unknown; gz?: string }> {
  if (responses.length === 0 || typeof base !== 'object' || base === null) return { detail: base };
  try {
    const gz = await encodeResponses(responses);
    const { message, rounds, active_ms: activeMs, labels } = base as Record<string, unknown>;
    const detail = { version: 3, message, rounds, active_ms: activeMs, labels, gz };
    return new TextEncoder().encode(JSON.stringify(detail)).length <= MAX_STORED_BYTES ? { detail, gz } : { detail: base };
  } catch {
    return { detail: base };
  }
}
