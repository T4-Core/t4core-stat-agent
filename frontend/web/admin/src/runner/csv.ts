// 질문 CSV 불러오기와 결과 CSV 내려받기
const HEADERS = new Set(['질문', 'question', 'query', '쿼리']);

/** 엑셀의 한글 CSV(EUC-KR)도 읽을 수 있게 UTF-8 실패 시 다시 해석합니다. */
export function decodeCsv(buffer: ArrayBuffer) {
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(buffer);
  } catch {
    return new TextDecoder('euc-kr').decode(buffer);
  }
}

/** 각 줄의 첫 번째 칸을 질문으로 읽습니다. 따옴표 안의 쉼표와 줄바꿈도 처리합니다. */
export function parseQuestions(source: string) {
  const content = source.replace(/^﻿/, '');
  const firstCells: string[] = [];
  let cell = '';
  let column = 0;
  let quoted = false;
  const endRow = () => {
    if (column === 0) firstCells.push(cell);
    cell = '';
    column = 0;
  };
  for (let index = 0; index < content.length; index += 1) {
    const char = content[index];
    if (quoted) {
      if (char === '"' && content[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"' && cell === '') quoted = true;
    else if (char === ',') {
      if (column === 0) firstCells.push(cell);
      cell = '';
      column += 1;
    } else if (char === '\n') endRow();
    else if (char !== '\r') cell += char;
  }
  endRow();
  const questions = firstCells.map((item) => item.replace(/\s+/g, ' ').trim()).filter(Boolean);
  return questions.length > 0 && HEADERS.has(questions[0].toLowerCase()) ? questions.slice(1) : questions;
}

function safeCell(value: string | number) {
  let text = String(value);
  // 엑셀이 글자를 수식으로 실행하지 않도록 막습니다.
  if (typeof value === 'string' && /^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function downloadCsv(fileName: string, rows: (string | number)[][]) {
  const body = rows.map((row) => row.map(safeCell).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([`﻿${body}`], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
