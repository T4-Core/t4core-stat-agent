// 실행 결과를 질문과 최종 결과(차트 · 답변 · 출처)만 담은 HTML 한 장으로 내려받습니다.
// 차트는 화면과 같은 모양의 SVG 그림으로 넣어 인터넷 없이도 열립니다.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { flushSync } from 'react-dom';
import { createRoot } from 'react-dom/client';
import type { PlotlyFigure } from '../../../src/api/types';
import { PlotlyChart } from '../../../src/components/PlotlyChart';
import { tablesOf, usedTables } from '../components/PipelineDashboard';
import { numberOf } from '../components/runView';
import { decodeResponses } from './responseCodec';
import type { RunItem } from './useQueryRunner';

type D = Record<string, any>;

const CHART_WIDTH = 640;
const CHART_HEIGHT = 320;
const MAX_TABLE_ROWS = 40;

const list = (value: unknown): any[] => (Array.isArray(value) ? value : []);

function escape(value: unknown) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] as string);
}

function cell(value: unknown) {
  if (value === null || value === undefined) return '';
  return escape(typeof value === 'object' ? JSON.stringify(value) : value);
}

/** 화면과 같은 차트를 보이지 않는 곳에 그린 뒤 SVG 그림 주소로 바꿉니다. */
async function chartImage(figure: PlotlyFigure, chartType?: string): Promise<string | null> {
  const host = document.createElement('div');
  host.style.cssText = `position:fixed;left:-10000px;top:0;width:${CHART_WIDTH}px;height:${CHART_HEIGHT}px;pointer-events:none;`;
  document.body.appendChild(host);
  const root = createRoot(host);
  try {
    flushSync(() => root.render(<PlotlyChart figure={figure} width={CHART_WIDTH} height={CHART_HEIGHT} chartType={chartType} />));
    // 차트 라이브러리를 불러와 그리는 데 시간이 걸려 최대 10초 기다립니다.
    for (let tries = 0; tries < 100; tries += 1) {
      if (host.querySelector('.chart-failed')) return null;
      const plot = host.querySelector<HTMLElement>('.plotly-chart');
      if (plot && (plot as any)._fullLayout && plot.querySelector('.main-svg')) {
        const { default: Plotly } = await import('plotly.js-dist-min');
        const toImage = (Plotly as unknown as { toImage: (element: HTMLElement, options: Record<string, unknown>) => Promise<string> }).toImage;
        return await toImage(plot, { format: 'svg', width: CHART_WIDTH, height: CHART_HEIGHT });
      }
      await new Promise((resolve) => window.setTimeout(resolve, 100));
    }
    return null;
  } catch {
    return null;
  } finally {
    root.unmount();
    host.remove();
  }
}

function tableHtml(table: D) {
  const columns = list(table.columns);
  if (columns.length === 0) return '';
  const rows = list(table.rows);
  const shown = rows.slice(0, MAX_TABLE_ROWS);
  const marked = new Set(list(table.highlight_rows));
  return `<div class="table-wrap"><b>${escape(table.title)}</b><table><thead><tr>${columns.map((head) => `<th>${cell(head)}</th>`).join('')}</tr></thead><tbody>${shown
    .map((row, index) => `<tr${marked.has(index) ? ' class="is-hl"' : ''}>${list(row).map((value) => `<td>${cell(value)}</td>`).join('')}</tr>`)
    .join('')}</tbody></table>${rows.length > shown.length ? `<p class="small">앞 ${shown.length}행만 표시 (전체 ${rows.length}행)</p>` : ''}</div>`;
}

function sourcesHtml(tbls: string[], tables: ReturnType<typeof tablesOf>) {
  if (tbls.length === 0) return '';
  const items = tbls.map((tbl) => {
    const info = tables[tbl] ?? {};
    const name = escape(info.name ?? tbl);
    const link = info.url ? `<a href="${escape(info.url)}" target="_blank" rel="noreferrer">${name} ↗</a>` : name;
    return `<li>${link}<small>${escape([info.survey, tbl].filter(Boolean).join(' · '))}</small></li>`;
  });
  return `<div class="sources"><b>KOSIS 통계표</b><ul>${items.join('')}</ul></div>`;
}

function caveatsHtml(caveats: string[]) {
  return caveats.length > 0 ? `<div class="caveats"><b>주의사항</b><ul>${caveats.map((caveat) => `<li>${escape(caveat)}</li>`).join('')}</ul></div>` : '';
}

function answerHtml(body: string, extra = '') {
  return `<div class="answer"><b>답변</b>${body ? `<div class="answer-text">${escape(body)}</div>` : '<p class="empty">답변이 생성되지 않았습니다.</p>'}${extra}</div>`;
}

/** 관리자 화면의 '최종 결과'와 같은 내용을 만듭니다. */
async function finalHtml(r: D, label?: string) {
  const m = r.modules;
  const answer = m?.answer;
  const body = String(answer?.answer ?? r.result?.answer ?? '');
  const charts = list(m?.drawn).filter((d) => d.status === 'drawn' && d.figure);
  const table = charts.length === 0 ? list(answer?.tables)[0] : null;
  const caveats = [...new Set(list(answer?.caveats ?? r.result?.caveats).map((c) => (typeof c === 'object' && c ? c.text : c)).filter(Boolean).map(String))];

  const figures: string[] = [];
  for (const d of charts) {
    const image = await chartImage(d.figure as PlotlyFigure, d.chart_type);
    const caption = d.title ? `<figcaption>${escape(d.title)}</figcaption>` : '';
    figures.push(`<figure>${caption}${image ? `<img src="${escape(image)}" alt="${escape(d.title ?? '통계 차트')}">` : '<p class="empty">차트를 그림으로 바꾸지 못했습니다.</p>'}</figure>`);
  }
  const visual = figures.join('') + (table ? tableHtml(table) : '');
  const extra = sourcesHtml(usedTables(r, charts), tablesOf(r)) + caveatsHtml(caveats);
  return `<div class="final${visual ? '' : ' is-single'}">${label ? `<h3>${escape(label)}</h3>` : ''}${visual ? `<div class="visual">${visual}</div>` : ''}${answerHtml(body, extra)}</div>`;
}

async function itemHtml(item: RunItem) {
  const head = `<header><span class="no">${numberOf(item.position)}</span><h2>${escape(item.question)}</h2></header>`;
  const result = item.result;
  let content: string;
  if (!result) {
    content = `<div class="final is-single">${answerHtml('', `<p class="small">${item.state === 'skipped' ? '실행하지 않은 쿼리입니다.' : '결과가 없습니다.'}</p>`)}</div>`;
  } else if (result.gz) {
    let responses: D[] | null = null;
    try {
      responses = (await decodeResponses(result.gz)) as unknown as D[];
    } catch {
      responses = null;
    }
    if (!responses || responses.length === 0) content = `<div class="final is-single">${answerHtml('', '<p class="small">저장된 결과를 열지 못했습니다.</p>')}</div>`;
    else {
      const parts: string[] = [];
      for (const [index, response] of responses.entries()) parts.push(await finalHtml(response, responses.length > 1 ? result.labels?.[index] ?? `응답 ${index + 1}` : undefined));
      content = parts.join('');
    }
  } else if (result.views.length > 0) {
    // 예전 형식 기록은 차트가 저장되어 있지 않아 답변만 보여줍니다.
    content = result.views
      .map((view) => `<div class="final is-single">${result.views.length > 1 ? `<h3>${escape(view.label)}</h3>` : ''}${answerHtml(view.answer, caveatsHtml(view.caveats))}</div>`)
      .join('');
  } else {
    content = `<div class="final is-single">${answerHtml('', result.message ? `<p class="small">${escape(result.message)}</p>` : '')}</div>`;
  }
  return `<section class="query">${head}${content}</section>`;
}

const STYLE = `
*{box-sizing:border-box}
body{margin:0;padding:32px 24px 48px;color:#1f2a27;background:#f3f7f6;font-family:'Pretendard Variable',Pretendard,system-ui,sans-serif;font-size:13px;line-height:1.55}
main{display:flex;flex-direction:column;gap:20px;max-width:1240px;margin:0 auto}
.top h1{margin:0;color:#1e2928;font-size:22px}
.top p{margin:4px 0 0;color:#6b7672}
.query{display:flex;flex-direction:column;gap:10px;break-inside:avoid}
.query>header{display:flex;align-items:baseline;gap:10px}
.query h2{margin:0;color:#1e2928;font-size:18px;font-weight:700;overflow-wrap:anywhere}
.no{color:#8a9794;font-size:13px;font-weight:700}
.final{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(280px,.85fr);gap:12px 16px;padding:14px 16px 16px;background:#fff;border:1px solid #e2eae8;border-top:3px solid #6b998d;border-radius:12px}
.final.is-single{grid-template-columns:minmax(0,1fr)}
.final>h3{grid-column:1/-1;margin:0;color:#1e2928;font-size:14px}
.visual,.answer{display:flex;flex-direction:column;gap:10px;min-width:0}
figure{margin:0}
figcaption{margin-bottom:4px;font-weight:700}
figure img{display:block;width:100%;height:auto}
.answer>b{color:#1e2928}
.answer-text{padding:10px 12px;background:#fafcfb;border:1px solid #e2eae8;border-radius:8px;font-size:14.5px;white-space:pre-wrap;overflow-wrap:anywhere}
.sources,.caveats{padding:8px 10px;background:#f3f7f6;border-radius:8px;font-size:12.5px}
.sources ul,.caveats ul{margin:4px 0 0;padding:0;list-style:none;display:flex;flex-direction:column;gap:4px}
.caveats{color:#55625f;font-size:12px}
.caveats ul{padding-left:16px;list-style:disc;gap:0}
.sources li{display:flex;flex-direction:column;overflow-wrap:anywhere}
.sources small{color:#8a9794;font-size:11px}
a{color:#4e7a6e;font-weight:600;text-decoration:none}
a:hover{text-decoration:underline}
.table-wrap{overflow-x:auto}
table{width:100%;margin-top:4px;border-collapse:collapse;font-size:12px}
th,td{padding:4px 8px;text-align:left;border-bottom:1px solid #e2eae8;white-space:nowrap}
th{background:#f3f7f6}
tr.is-hl td{background:#e7f0ed;font-weight:600}
.small{margin:2px 0;color:#6b7672;font-size:12px}
.empty{margin:4px 0;color:#8a9794;font-style:italic}
@media (max-width:900px){.final{grid-template-columns:minmax(0,1fr)}}
@media print{body{background:#fff;padding:0}}
`;

/** 실행한 모든 쿼리의 최종 결과를 HTML 파일로 내려받습니다. */
export async function downloadHtmlReport(fileName: string, items: RunItem[], meta: string) {
  const sections: string[] = [];
  for (const item of items) sections.push(await itemHtml(item));
  const html = `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>쿼리 테스트 답변 결과</title>
<style>${STYLE}</style>
</head>
<body>
<main>
<header class="top"><h1>쿼리 테스트 답변 결과</h1><p>${escape(meta)}</p></header>
${sections.join('\n')}
</main>
</body>
</html>
`;
  const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
