// 실제 응답은 용량이 커서 브라우저의 IndexedDB 에 저장합니다.
import type { ChatResponse } from '../api/types';

export type RunPayload = { responses: ChatResponse[]; labels?: string[] };

const DB_NAME = 'kosis-agent';
const STORE = 'payloads';
const memory = new Map<string, RunPayload>();

function openDb() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore<T>(mode: IDBTransactionMode, work: (store: IDBObjectStore) => IDBRequest<T>) {
  const db = await openDb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const transaction = db.transaction(STORE, mode);
      const request = work(transaction.objectStore(STORE));
      transaction.oncomplete = () => resolve(request.result);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally {
    db.close();
  }
}

export async function savePayload(id: string, payload: RunPayload) {
  memory.set(id, payload);
  try {
    await withStore('readwrite', (store) => store.put(payload, id));
  } catch {
    // 저장 공간이 부족해도 현재 화면은 메모리의 응답으로 계속 동작합니다.
  }
}

export function peekPayload(id: string) {
  return memory.get(id);
}

export async function loadPayload(id: string) {
  const cached = memory.get(id);
  if (cached) return cached;
  try {
    const saved = await withStore<RunPayload | undefined>('readonly', (store) => store.get(id));
    if (saved) memory.set(id, saved);
    return saved ?? null;
  } catch {
    return null;
  }
}

export async function deletePayload(id: string) {
  memory.delete(id);
  try {
    await withStore('readwrite', (store) => store.delete(id));
  } catch {
    // 지우지 못해도 목록에서는 이미 사라진 상태입니다.
  }
}
