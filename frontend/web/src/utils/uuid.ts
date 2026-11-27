// [NEW] KOS-56
// crypto.randomUUID 는 보안 컨텍스트(HTTPS, localhost)에서만 제공되므로 HTTP 배포에서는 직접 생성한다.
// 이 값은 backend session_id 로도 쓰이므로 폴백도 암호학적 난수(getRandomValues)를 사용한다.
export function randomUUID(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();

  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10xx

  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}