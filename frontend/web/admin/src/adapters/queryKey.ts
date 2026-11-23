// 띄어쓰기 개수나 영문 대소문자만 다른 질문은 같은 쿼리로 봅니다.
export function queryKey(query: string) {
  return query.normalize('NFC').replace(/\s+/g, ' ').trim().toLowerCase();
}
