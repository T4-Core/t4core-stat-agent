// 백엔드가 준 근거 표를 그대로 보여줍니다. 계산에 쓴 행은 강조됩니다.
import type { EvidenceTableData } from '../data/types';

const isNumeric = (text: string) => /^[+-]?[\d,.]+\s*[%가-힣a-zA-Z]{0,4}$/.test(text);

export function EvidenceTable({ table, className = '' }: { table: EvidenceTableData; className?: string }) {
  const highlighted = new Set(table.highlight);
  const numeric = table.columns.map((_, column) => table.rows.some((row) => isNumeric(row[column] ?? '')) && column > 0);

  return (
    <div className={`evidence-wrap ${className}`}>
      <table className="view-table">
        <thead>
          <tr>{table.columns.map((column, index) => <th scope="col" key={`${column}-${index}`} className={numeric[index] ? 'right' : undefined}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={rowIndex} className={highlighted.has(rowIndex) ? 'hl' : undefined}>
              {row.map((cell, index) => <td key={index} className={numeric[index] ? 'right' : undefined}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {table.truncated && <p className="evidence-note">전체 {table.totalRows.toLocaleString('ko-KR')}행 중 {table.rows.length.toLocaleString('ko-KR')}행만 표시합니다.</p>}
    </div>
  );
}
