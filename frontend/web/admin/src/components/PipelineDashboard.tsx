// 쿼리 한 개의 단계별 결과. 골든셋 대시보드처럼 단계 카드 + 펼치는 중간 결과 + 모듈 사이 QA 칸으로 보여줍니다.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { createContext, isValidElement, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { ChatResponse, PlotlyFigure } from '../../../src/api/types';
import { PlotlyChart } from '../../../src/components/PlotlyChart';
import type { ModuleKey } from '../adapters/issues';
import { moduleStyle } from '../adapters/moduleColors';
import { decodeResponses } from '../runner/responseCodec';
import '../styles/pipeline.css';

type D = Record<string, any>;

const MAX_TABLE_ROWS = 40;
const MAX_JSON = 120_000;
const STATUS_KO: D = { ok: '정상', warned: '경고', partial: '일부만', stopped: '중단', error: '오류', failed: '형식 오류', needs_clarification: '되묻기', needs_selection: '표 선택', out_of_scope: '범위 밖' };
const GATES_AFTER: Record<string, string[]> = { views: ['A0', 'M2-in'], m2: ['M2-out', 'M3-in'], m3: ['M3-out'], m5: ['M5-out', 'M6-in'], m6: ['M6-out', 'A9'] };
const GATE_INFO: Record<string, [string, string]> = {
  A0: ['Generator 입구', '검색·View 결과(ViewSet)가 Generator로 들어올 때'],
  'M2-in': ['모듈 2 입력', 'ViewSet을 모듈 2 입력으로 바꾼 값'],
  'M2-out': ['모듈 2 출력', '차트 계획 chart_plan'],
  'M3-in': ['모듈 3 입력', '모듈 2 출력을 모듈 3 요청으로 바꾼 값'],
  'M3-out': ['모듈 3 출력', '계산 결과 · 차트 내용 (모듈 5 입력도 이 값)'],
  'M5-out': ['모듈 5 출력', '그린 차트'],
  'M6-in': ['모듈 6 입력', '모듈 3 출력으로 만든 답변 요청'],
  'M6-out': ['모듈 6 출력', '답변 · 근거 표'],
  A9: ['최종 결과', '화면으로 나가는 결과'],
};
const SEV_KO: D = { error: '오류', warning: '경고', info: 'info' };
const KIND_KO: D = { missing: '필수 필드 없음', type: '타입 다름', enum: '허용값 밖', extra: '스키마에 없는 키', fixed_type: '타입 보정', default: '빠진 선택 필드', exception: '모듈 실행 실패', empty: '빈 값', ref: 'id 짝 없음', note: '모듈 메모', withheld: '계산 보류', plan_warning: '모듈 3 경고', answer_fallback: '규칙 문장 대체', condition_unused: '조건 미적용', ratio_missing: '비율 계산 없음', measure_mismatch: '지표 불일치', too_many_marks: '막대 과다', chart_answer_mismatch: '차트·답변 불일치', answer_caveat_conflict: '답변·주의사항 모순', value_list: '값 나열 답변', no_data: '데이터 없음', indicator_not_found: '지표 없음' };
const SEM_KINDS = new Set(['note', 'withheld', 'plan_warning', 'answer_fallback', 'condition_unused', 'ratio_missing', 'measure_mismatch', 'too_many_marks', 'chart_answer_mismatch', 'answer_caveat_conflict', 'value_list']);
const ACTION_KO: D = { fixed: '보정', warn: '경고만', info: '기록만', retry: '재시도', drop: '그 항목 뺌', stop: '중단', skip: '건너뜀', inspect: '검사만' };
const NO_TRACE = '후보 소거 과정, HCX에 보낸 메시지, 초안처럼 모듈 내부 기록은 백엔드 /chat 응답에 포함되지 않아 표시할 수 없습니다.';

const STAGE_MODULE: Record<string, ModuleKey> = { rewrite: 'analysis', views: 'search', m2: 'm2', m3: 'm3', m5: 'm5', m6: 'm6', qa: 'qa' };

const isSem = (issue: D) => issue.severity === 'warning' && SEM_KINDS.has(issue.kind);
const sevLabel = (issue: D) => (issue.severity === 'warning' ? (isSem(issue) ? '내용 경고' : '형식 경고') : SEV_KO[issue.severity] ?? issue.severity);
const list = (value: unknown): any[] => (Array.isArray(value) ? value : []);
const shortId = (id: unknown) => { const parts = String(id ?? '').split('::'); return parts.length >= 4 ? `${parts[1]} · ${parts[3]}` : String(id ?? ''); };
const tblOf = (id: unknown) => { const parts = String(id ?? '').split('::'); if (parts.length < 2) return String(id ?? ''); const index = parts[1].indexOf('_'); return index > 0 ? parts[1].slice(index + 1) : parts[1]; };
const isEmpty = (value: unknown) => value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0);
const text = (value: unknown) => (isEmpty(value) ? '-' : typeof value === 'object' ? JSON.stringify(value) : String(value));

function groupIssues(items: unknown): D[] {
  const groups = new Map<string, D>();
  for (const issue of list(items)) {
    const path = issue.severity === 'error' ? String(issue.path ?? '') : String(issue.path ?? '').replace(/\[\d+\]/g, '[]');
    const key = [issue.point, issue.severity, issue.kind, path, issue.action, issue.message].join('|');
    const current = groups.get(key);
    if (current) current.count += issue.count || 1;
    else groups.set(key, { ...issue, path, count: issue.count || 1 });
  }
  return [...groups.values()];
}

function gateState(qa: D | null | undefined, point: string): [string, string] | null {
  if (!qa) return null;
  const issues = list(qa.issues).filter((issue) => issue.point === point);
  const retries = list(qa.retries).filter((item) => item.point === point);
  if (qa.stopped_at === point) return ['bad', '중단'];
  if (list(qa.skipped).includes(point)) return ['part', '건너뜀'];
  if (list(qa.dropped).some((item) => item.point === point)) return ['part', '일부 뺌'];
  if (retries.length && retries.every((item) => item.result === 'passed')) return ['warn', '재시도 후 통과'];
  if (issues.some((issue) => issue.severity === 'error')) return ['bad', '오류'];
  if (retries.length) return ['warn', '재시도'];
  if (issues.some(isSem)) return ['warn', '내용 경고'];
  if (issues.some((issue) => issue.severity === 'warning')) return ['fmt', '형식 경고'];
  return list(qa.checked).includes(point) ? ['ok', '통과'] : ['na', '검사 안 함'];
}

// ── 공통 부품 ──
const ExpandContext = createContext({ signal: 0, stages: true, deep: false });
const TablesContext = createContext<Record<string, { name?: string; survey?: string; url?: string }>>({});

function Det({ title, children, defaultOpen = false }: { title: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const expand = useContext(ExpandContext);
  const [open, setOpen] = useState(defaultOpen || expand.deep);
  useEffect(() => { if (expand.signal) setOpen(expand.deep); }, [expand.deep, expand.signal]);
  return (
    <details className="pd-det" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>{title}</summary>
      {/* 큰 표와 JSON은 펼쳤을 때만 만듭니다. */}
      {open && children}
    </details>
  );
}

function Json({ title, value }: { title: string; value: unknown }) {
  if (value === undefined || value === null) return null;
  return <Det title={title}><JsonBody value={value} /></Det>;
}

function JsonBody({ value }: { value: unknown }) {
  const body = useMemo(() => {
    const json = JSON.stringify(value, null, 1) ?? '';
    return json.length > MAX_JSON ? `${json.slice(0, MAX_JSON)}\n… (표시 한도를 넘어 생략했습니다)` : json;
  }, [value]);
  return <pre className="pd-pre" tabIndex={0}>{body}</pre>;
}

const Empty = ({ children }: { children: ReactNode }) => <p className="pd-empty">{children}</p>;
const StepBox = ({ title, children }: { title: ReactNode; children: ReactNode }) => <div className="pd-step"><div className="pd-step-title">{title}</div>{children}</div>;
const Mid = ({ children }: { children: ReactNode }) => <div className="pd-mid"><div className="pd-mid-title">중간 결과 (눌러서 펼치기)</div>{children}</div>;
const Chip = ({ tone = '', children }: { tone?: string; children: ReactNode }) => <span className={`pd-chip ${tone}`}>{children}</span>;

// 모듈 메모는 중립 색입니다. 주황은 QA 경고에만 씁니다.
function Notes({ items, tone = 'info' }: { items: unknown; tone?: 'warn' | 'err' | 'info' }) {
  const rows = list(items);
  if (rows.length === 0) return null;
  return <div className={`pd-box is-${tone}`}>{rows.map((item, index) => <div key={index}>{typeof item === 'object' ? JSON.stringify(item) : String(item)}</div>)}</div>;
}

function Kv({ pairs }: { pairs: [string, ReactNode][] }) {
  return <dl className="pd-kv">{pairs.filter(([, value]) => value !== undefined).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{isValidElement(value) ? value : text(value)}</dd></div>)}</dl>;
}

const KvObject = ({ value }: { value: D | null | undefined }) => (value ? <Kv pairs={Object.entries(value).map(([key, item]) => [key, text(item)])} /> : <Empty>없음</Empty>);

function DataTable({ columns, rows, highlight, rowClass }: { columns: unknown; rows: unknown[][]; highlight?: unknown; rowClass?: (index: number) => string }) {
  const heads = list(columns);
  if (heads.length === 0) return <Empty>표 없음</Empty>;
  const marked = new Set(list(highlight));
  const shown = rows.slice(0, MAX_TABLE_ROWS);
  return (
    <>
      <div className="pd-table" tabIndex={0}>
        <table>
          <thead><tr>{heads.map((head, index) => <th key={index}>{String(head)}</th>)}</tr></thead>
          <tbody>
            {shown.map((row, index) => (
              <tr key={index} className={`${marked.has(index) ? 'is-hl ' : ''}${rowClass?.(index) ?? ''}`}>
                {list(row).map((cell, cellIndex) => <td key={cellIndex}>{isValidElement(cell) ? cell : cell === null || cell === undefined ? '' : typeof cell === 'object' ? JSON.stringify(cell) : String(cell)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > shown.length && <p className="pd-small">앞 {shown.length}행만 표시 (전체 {rows.length}행)</p>}
    </>
  );
}

function ObjTable({ items, keys, rowClass }: { items: D[]; keys?: string[]; rowClass?: (item: D) => string }) {
  if (items.length === 0) return <Empty>없음</Empty>;
  const columns = keys ?? [...new Set(items.flatMap((item) => Object.keys(item)))];
  return <DataTable columns={columns} rows={items.map((item) => columns.map((key) => item[key]))} rowClass={rowClass ? (index) => rowClass(items[index]) : undefined} />;
}

const RecordTable = ({ record }: { record: D | null | undefined }) => <DataTable columns={record?.table?.columns} rows={list(record?.table?.rows)} />;

function Kosis({ tbl, label }: { tbl: string; label?: string }) {
  const info = useContext(TablesContext)[tbl];
  return info?.url ? <a href={info.url} target="_blank" rel="noreferrer" title="KOSIS에서 열기">{label ?? tbl} ↗</a> : <>{label ?? tbl}</>;
}

function TableCell({ tbl }: { tbl: string }) {
  const info = useContext(TablesContext)[tbl];
  return <><Kosis tbl={tbl} />{info?.name && <div className="pd-small">{info.name}</div>}</>;
}

const RecordIds = ({ ids }: { ids: unknown }) => <>{list(ids).map((id) => <div key={String(id)}><Kosis tbl={tblOf(id)} /> <span className="pd-small">{String(id).split('::')[3] ?? ''}</span></div>)}</>;

function SourceLine({ ids, label = '출처 표' }: { ids: unknown; label?: string }) {
  const tables = useContext(TablesContext);
  const tbls = [...new Set(list(ids).map(tblOf))];
  if (tbls.length === 0) return null;
  return <p className="pd-small">{label}: {tbls.map((tbl, index) => <span key={tbl}>{index > 0 ? ' · ' : ''}<Kosis tbl={tbl} /> {tables[tbl]?.name}</span>)}</p>;
}

function tablesOf(response: D) {
  const out: Record<string, { name?: string; survey?: string; url?: string }> = {};
  for (const unit of list(response.views?.units)) {
    for (const candidate of list(unit.candidates)) out[candidate.tbl_id] ??= { name: candidate.tbl_nm, survey: candidate.survey_nm };
    const stitched = Object.values(unit.stitched ?? {}).flatMap((parts) => list(parts));
    for (const view of [...list(unit.views), ...stitched]) {
      const source = view.record?.source;
      if (source?.tbl_id) {
        out[source.tbl_id] ??= {};
        out[source.tbl_id].url = source.kosis_url ?? out[source.tbl_id].url;
      }
    }
  }
  // 답변에 실제로 쓴 자료의 표 이름과 KOSIS 주소도 채웁니다.
  for (const record of [...list(response.views?.records), ...list(response.modules?.records)]) {
    const source = record.source;
    if (!source?.tbl_id) continue;
    const info = (out[source.tbl_id] ??= {});
    info.name ??= record.metadata?.tbl_nm;
    info.survey ??= record.metadata?.survey_nm;
    info.url ??= source.kosis_url ?? (source.org_id ? `https://kosis.kr/statHtml/statHtml.do?orgId=${encodeURIComponent(source.org_id)}&tblId=${encodeURIComponent(source.tbl_id)}` : undefined);
  }
  return out;
}

// ── QA 칸 ──
function Gate({ qa, point }: { qa: D | null | undefined; point: string }) {
  const expand = useContext(ExpandContext);
  const state = gateState(qa, point);
  const all = useMemo(() => groupIssues(list(qa?.issues).filter((issue) => issue.point === point)), [point, qa]);
  const main = all.filter((issue) => issue.severity !== 'info');
  const info = all.filter((issue) => issue.severity === 'info');
  const retries = list(qa?.retries).filter((item) => item.point === point);
  const dropped = list(qa?.dropped).filter((item) => item.point === point);
  const real = main.filter((issue) => issue.severity === 'error' || isSem(issue));
  const problem = Boolean(real.length || retries.length || dropped.length || qa?.stopped_at === point);
  const [open, setOpen] = useState(problem);
  useEffect(() => { if (expand.signal) setOpen(expand.stages && (expand.deep || problem)); }, [expand.deep, expand.signal, expand.stages, problem]);
  if (!state) return null;
  const [tone, label] = state;
  const [name, description] = GATE_INFO[point];
  const row = (issue: D) => [<span className={`pd-sev is-${issue.severity}`}>{sevLabel(issue)}</span>, KIND_KO[issue.kind] ?? issue.kind, issue.path || '-', issue.count, ACTION_KO[issue.action] ?? issue.action ?? '-', issue.message, issue.value ?? ''];
  const columns = ['심각도', '종류', '경로', '건수', '대응', '내용', '예시 값'];
  return (
    <details className={`pd-gate is-${tone}`} id={`pd-gate-${point}`} open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        <span className="pd-gate-tag">QA {point}</span><b>{name}</b><span className="pd-sub">{description}</span>
        <Chip tone={tone === 'na' ? '' : tone}>{label}{real.length || main.length ? ` ${real.length || main.length}줄` : ''}</Chip>
      </summary>
      {open && (
        <div className="pd-gate-body">
          {qa?.stopped_at === point && qa?.message && <div className="pd-box is-err">{qa.message}</div>}
          {retries.length > 0 && <p className="pd-small">재시도: {retries.map((item) => `${item.why} → ${item.result ?? '-'}${item.kept ? ` (${item.kept === 'retry' ? '재시도 결과 사용' : '처음 결과 사용'})` : ''}`).join(', ')}</p>}
          {dropped.length > 0 && <p className="pd-small">뺀 항목: {dropped.map((item) => item.path).join(', ')}</p>}
          {main.length > 0 && <DataTable columns={columns} rows={main.map(row)} />}
          {info.length > 0 && <Det title={`info ${info.length}줄 (알려진 새 필드 · 빠진 선택 필드)`}><DataTable columns={columns} rows={info.map(row)} /></Det>}
          {!main.length && !info.length && !retries.length && !dropped.length && <p className="pd-small">{tone === 'na' ? '이 지점까지 오지 않았거나 해당 없음' : '문제 없음'}</p>}
        </div>
      )}
    </details>
  );
}

// ── ① 질의 재작성 ──
function Rewrite({ r }: { r: D }) {
  const a = r.analysis;
  if (!a) return <Empty>질의 분석 결과 없음</Empty>;
  const bundle = a.bundle ?? {};
  const viewBundle = a.view_bundle ?? {};
  const subs = list(viewBundle.sub_questions ?? bundle.sub_questions);
  const filters = viewBundle.filters ?? bundle.filters;
  const slotRows = Object.entries(a.slots ?? {}).flatMap(([key, values]) => list(values).map((v) => (typeof v === 'object' && v ? [key, v.raw, v.value, v.source, v.match, v.grounded, v.n_tables, list(v.csv).slice(0, 8).join(', '), v.note] : [key, v])));
  const state = a.state ? Object.fromEntries(['raw_slots', 'sub_slots', 'intents', 'sub_intents', 'hcx_ok', 'hcx_error'].map((key) => [key, a.state[key]])) : null;
  return (
    <>
      <Kv pairs={[['원 질문', r.question], ['재작성', <b key="b">{text(bundle.rewritten ?? viewBundle.rewritten)}</b>], ['의도', text(bundle.intent ?? viewBundle.intent)], ['상태', STATUS_KO[a.status] ?? a.status], ['검색 문장', text(a.search_text ?? viewBundle.search_text)], ['하위 질문', subs.length ? <div key="s">{subs.map((sub, index) => <div key={index}>{index + 1}. {String(sub)}</div>)}</div> : '없음 (본 질문 하나)']]} />
      {filters && <><h4>슬롯 (view_bundle.filters)</h4><DataTable columns={['슬롯', '값']} rows={Object.entries(filters).filter(([, value]) => !isEmpty(value))} /></>}
      {list(viewBundle.sub_filters).length > 0 && <><h4>하위 질문 슬롯</h4><DataTable columns={['#', '하위 질문', '슬롯']} rows={list(viewBundle.sub_filters).map((item, index) => [index + 1, subs[index] ?? '', Object.fromEntries(Object.entries(item ?? {}).filter(([, value]) => value !== null && value !== undefined))])} /></>}
      {list(a.clarifications).length > 0 && <div className="pd-box is-info"><b>되묻기</b> {list(a.clarifications).map((item) => `${item.slot}: ${item.reason}`).join(' · ')}</div>}
      <Notes items={a.notes} />
      <Mid>
        {state && <Det title="HCX 재작성 원 슬롯 (raw_slots) · 의도"><KvObject value={state} /></Det>}
        {slotRows.length > 0 && <Det title="CSV 값 사전 접지 (원 표현 → 접지한 값)"><DataTable columns={['슬롯', '원 표현', '접지 값', '출처', '맞춘 방법', '접지됨', '표 수', 'CSV 값', 'note']} rows={slotRows} /></Det>}
        <Json title="하위 질문 분해 (sub_queries)" value={a.sub_queries} />
        <Json title="적용 규칙 · 분해 사유" value={{ applied_rules: a.applied_rules, decompose_reason: a.decompose_reason }} />
        {list(a.trace).length > 0 && (
          <Det title={`단계 기록 (trace ${list(a.trace).length}단계)`}>
            {list(a.trace).map((item, index) => (
              <Det key={index} title={`단계 ${item.step} — ${item.seconds ?? '-'}초${item.error ? ' · 오류' : ''}${list(item.notes).length ? ` · notes ${list(item.notes).length}` : ''}`}>
                {item.error && <div className="pd-box is-err">{item.error}</div>}
                <Notes items={item.notes} />
                {item.params && <p className="pd-small">params {JSON.stringify(item.params)}</p>}
                <JsonBody value={item.output ?? null} />
              </Det>
            ))}
          </Det>
        )}
        <Json title="재작성 결과 (bundle)" value={a.bundle} />
        <Json title="view_bundle (검색 · 모듈 2·3 입력)" value={a.view_bundle} />
      </Mid>
    </>
  );
}

// ── ② View 검색 ──
function ViewCard({ view, used }: { view: D; used: Set<string> }) {
  const tables = useContext(TablesContext);
  const record = view.record ?? {};
  const meta = record.metadata ?? {};
  const source = record.source ?? {};
  return (
    <Det title={`View #${view.rank} ${view.tbl_id}${tables[view.tbl_id]?.name ? ` ${tables[view.tbl_id].name}` : ''} — ${list(record.table?.rows).length}행${used.has(record.id) ? ' ✔ 고름' : ''}`}>
      <Notes items={view.notes} />
      <Kv pairs={[['record id', <code key="c">{record.id}</code>], ['표', <Kosis key="k" tbl={source.tbl_id ?? view.tbl_id} />], ['기간', text(meta.prd_from ? `${meta.prd_from}~${meta.prd_to}` : source.period)], ['단위', text(meta.unit)]]} />
      <RecordTable record={record} />
      <Json title="metadata" value={record.metadata} />
      <Json title="notes (구조화)" value={record.notes} />
      <Json title="match" value={record.match} />
    </Det>
  );
}

function Views({ r }: { r: D }) {
  const tables = useContext(TablesContext);
  const views = r.views;
  if (!views) return <Empty>{r.analysis && r.analysis.status !== 'ok' ? `①이 ${STATUS_KO[r.analysis.status] ?? r.analysis.status} → 검색 안 함` : '검색 결과 없음'}</Empty>;
  const units = list(views.units);
  const used = new Set<string>(list(views.records).map((item) => item.id));
  const usedTables = [...new Set([...used].map(tblOf))];
  return (
    <>
      <div className="pd-chips"><Chip>ViewSet <b>{STATUS_KO[views.status] ?? views.status}</b></Chip><Chip>검색 단위 <b>{units.length}</b></Chip><Chip>고른 View <b>{used.size}</b></Chip></div>
      <Notes items={views.notes} />
      <ObjTable items={units.map((unit) => {
        const first = list(unit.views).find((view) => used.has(view.record?.id)) ?? list(unit.views)[0];
        return { unit_id: unit.unit_id, '검색 문장': unit.search_query ?? unit.query, 후보: list(unit.candidates).length, '고른 표': first ? <TableCell tbl={first.tbl_id} /> : '-', 조사: first ? first.record?.metadata?.survey_nm ?? tables[first.tbl_id]?.survey ?? '-' : '-', '행 수': first ? list(first.record?.table?.rows).length : '-', '충돌 판정': unit.conflict?.status ?? '-' };
      })} />
      {usedTables.length > 0 && <><h4>근거 통계표 (KOSIS)</h4><ul className="pd-sources">{usedTables.map((tbl) => <li key={tbl}><Kosis tbl={tbl} /> <span className="pd-small">{tables[tbl]?.name}{tables[tbl]?.survey ? ` · ${tables[tbl].survey}` : ''}</span></li>)}</ul></>}
      <Mid>
        {units.map((unit) => {
          const conflict = unit.conflict ?? {};
          const stitched = Object.entries(unit.stitched ?? {});
          return (
            <Det key={unit.unit_id} title={`[${unit.unit_id}] ${unit.query}`}>
              <p className="pd-small">검색 문장: {unit.search_query ?? unit.query} · 충돌 판정 <b>{conflict.status ?? '-'}</b>{list(conflict.options).length ? ` · 선택지 ${list(conflict.options).length}개` : ''}</p>
              <Notes items={unit.notes} />
              <StepBox title={`① 검색 후보 (상위 ${Math.min(10, list(unit.candidates).length)}/${list(unit.candidates).length})`}>
                <ObjTable items={list(unit.candidates).slice(0, 10).map((c) => ({ rank: c.rank, 표: <TableCell tbl={c.tbl_id} />, survey_nm: c.survey_nm, score: c.score, dense: c.dense, bm25: c.bm25, bm25_rank: c.bm25_rank, cover: c.cover, cost: c.cost, unmet: c.unmet, 'View 있음': c.has_view }))} />
              </StepBox>
              <StepBox title={`② 만든 View ${list(unit.views).length}개`}>
                {list(unit.views).length ? list(unit.views).map((view, index) => <ViewCard key={`${view.tbl_id}-${index}`} view={view} used={used} />) : <Empty>없음</Empty>}
              </StepBox>
              {stitched.length > 0 && (
                <StepBox title="②-1 이어붙인 View (같은 통계의 다른 연도 표 · 비교 대상 아님)">
                  {stitched.map(([parent, parts]) => (
                    <div key={parent}>
                      <p className="pd-small"><Kosis tbl={parent} /> 에 이어붙임</p>
                      {list(parts).map((part, index) => <Det key={index} title={`${part.tbl_id} — ${list(part.years).join(', ')} · ${list(part.record?.table?.rows).length}행`}><Notes items={part.notes} /><RecordTable record={part.record} /></Det>)}
                    </div>
                  ))}
                </StepBox>
              )}
              <StepBox title="③ 충돌 판정 (표마다 값이 같은가)">
                <Kv pairs={[['판정', text(conflict.status)], ['비교한 키', text(conflict.n_compared_keys)], ['일치', text(conflict.n_agree)], ['고른 선택지', text(conflict.selected_option)]]} />
                <Notes items={conflict.notes} tone="info" />
                {list(conflict.differing_points).length > 0 && <Det title="값이 다른 지점"><ObjTable items={list(conflict.differing_points).slice(0, 10)} /></Det>}
              </StepBox>
              <Json title="이 단위의 filters" value={unit.filters} />
            </Det>
          );
        })}
      </Mid>
    </>
  );
}

// ── ③ 모듈 2 ──
function Module2({ r }: { r: D }) {
  const m = r.modules;
  if (!m) return <Empty>모듈이 돌지 않음</Empty>;
  const plan = m.chart_plan ?? {};
  const charts = list(plan.charts);
  return (
    <>
      {charts.length ? <ObjTable items={charts.map((c) => ({ chart_id: c.chart_id, '하위 질문': list(c.sub_question_ids).join(', '), View: <RecordIds ids={c.view_ids} />, 차트: c.chart_type ?? '(표만)', measure: c.measure, 조건: list(c.requirements).join(', '), '대체 후보': list(c.fallback_charts).join(', '), 이유: c.reason }))} /> : <Empty>차트 없음</Empty>}
      {charts.flatMap((c) => list(c.warnings).map((warning, index) => <div className="pd-box is-info" key={`${c.chart_id}-${index}`}><b>{c.chart_id}</b> {String(warning)}</div>))}
      {list(plan.overlays).length > 0 && <><h4>겹쳐 그리기</h4><ObjTable items={list(plan.overlays)} keys={['overlay_id', 'charts', 'mode', 'axes', 'reason']} /></>}
      {list(m.chart_errors).length > 0 && <><h4>모듈 2 · 연결 알림</h4><ObjTable items={list(m.chart_errors)} keys={['node', 'chart_id', 'level', 'reason']} rowClass={(e) => (e.level === 'info' ? 'is-drop' : '')} /></>}
      <Mid>
        <p className="pd-small">{NO_TRACE}</p>
        <Det title={`출력: 차트 요청 ChartRequest ${list(m.charts).length}개`}><ObjTable items={list(m.charts).map((c) => ({ chart_id: c.chart_id, sub_question_ids: c.sub_question_ids, chart_type: c.chart_type, fallback_chart: c.fallback_chart, measure: c.measure, requirements: c.requirements, view_ids: list(c.view_ids).map(shortId), reason: c.reason }))} /></Det>
        <Json title="모듈 2 출력 chart_plan" value={plan} />
      </Mid>
    </>
  );
}

// ── ④ 모듈 3 ──
function Module3({ r }: { r: D }) {
  const m = r.modules;
  if (!m) return <Empty>모듈이 돌지 않음</Empty>;
  const m3 = m.module3;
  if (!m3) return <Empty>모듈 3 출력 없음 (QA 중단 또는 실패)</Empty>;
  const plan = m3.chart_plan ?? {};
  const validation = m3.validation ?? {};
  const calcs = list(m3.calc_results);
  return (
    <>
      <h4>차트 계산 계획 · 검증</h4>
      {list(plan.plans).length ? <ObjTable items={list(plan.plans).map((p) => {
        const v = validation[p.chart_id];
        return { chart_id: p.chart_id, View: <RecordIds ids={[p.record_id]} />, measure: p.measure, '고른 행': p.select ?? '전체', '계산 단계': list(p.steps).map((s) => `${s.step_id}:${s.op}`).join(' → '), '원래 차트': p.chart_type, 검증: v ? (v.original?.passed ? '통과' : `실패 ${list(v.original?.failed).join(',')}${v.fallback ? ` → 대체 ${v.fallback.chart_type} ${v.fallback.passed ? '통과' : '실패'}` : ''}`) : '-', '최종 차트': v ? v.final_chart_type ?? '(차트 없음)' : '-', '차트 내용': v ? (v.content_built ? '만듦' : '못 만듦') : '-' };
      })} rowClass={(item) => (item['차트 내용'] === '만듦' ? 'is-keep' : '')} /> : <Empty>차트 계획 없음</Empty>}
      <h4>질문용 계산 결과</h4>
      {calcs.length ? <ObjTable items={calcs.map((c) => ({ step_id: c.step_id, op: c.op, 값: c.value, 단위: c.unit, 범위: c.scope_label, note: c.note }))} /> : <Empty>없음</Empty>}
      <Notes items={plan.warnings} />
      <Notes items={plan.notes} tone="info" />
      <Mid>
        <p className="pd-small">{NO_TRACE}</p>
        <Det title={`입력: 차트 요청 ChartRequest ${list(m.charts).length}개 (모듈 2 → 어댑터)`}><ObjTable items={list(m.charts).map((c) => ({ chart_id: c.chart_id, sub_question_ids: c.sub_question_ids, chart_type: c.chart_type, fallback_chart: c.fallback_chart, measure: c.measure, requirements: c.requirements, view_ids: list(c.view_ids).map(shortId), reason: c.reason }))} /></Det>
        <Det title={`입력: 통계 자료 records ${list(m.records).length}개`}>
          {list(m.records).length ? list(m.records).map((record) => <Det key={record.id} title={`${shortId(record.id)} — ${list(record.table?.rows).length}행`}><RecordTable record={record} /></Det>) : <Empty>없음</Empty>}
        </Det>
        {list(plan.plans).map((p) => (
          <Det key={p.chart_id} title={`차트 ${p.chart_id} 계산 계획 — ${validation[p.chart_id]?.final_chart_type ?? '(차트 없음)'}`}>
            <Kv pairs={[['View', shortId(p.record_id)], ['고른 행 (select)', text(p.select)], ['출력', text(p.output)], ['제목', text(p.title)]]} />
            <ObjTable items={list(p.steps).map((s) => ({ step_id: s.step_id, op: s.op, '입력 단계': s.input, 피연산자: s.operands, 기간: s.from_ || s.to ? `${s.from_ ?? ''}~${s.to ?? ''}` : '', base: s.base, agg: s.agg, top_n: s.top_n, display: s.display_ref }))} />
          </Det>
        ))}
        {calcs.length > 0 && (
          <Det title={`질문용 계산 입력 값 (${calcs.length}개)`}>
            {calcs.map((c) => (
              <StepBox key={c.step_id} title={`${c.step_id} · ${c.op} = ${JSON.stringify(c.value)}`}>
                <ObjTable items={list(c.inputs).map((i) => ({ role: i.role, View: shortId(i.record_id), item: i.item, key: i.key, value: i.value, unit: i.unit }))} />
                <Notes items={c.note ? [c.note] : []} />
              </StepBox>
            ))}
          </Det>
        )}
        <Det title={`최종 차트 데이터 ChartContent ${list(m3.chart_contents).length}개`}>
          {list(m3.chart_contents).length ? list(m3.chart_contents).map((c) => (
            <Det key={c.chart_id} title={`${c.chart_id} ${c.chart_type} · ${c.title ?? ''} — ${list(c.rows).length}행`}>
              <DataTable columns={c.columns} rows={list(c.rows)} />
              <Json title="encoding · axis · options" value={{ encoding: c.encoding, axis: c.axis, options: c.options, warnings: c.warnings }} />
            </Det>
          )) : <Empty>없음</Empty>}
        </Det>
        <Det title={`질문용 계산 단계 answer_steps ${list(plan.answer_steps).length}개`}><ObjTable items={list(plan.answer_steps).map((s) => ({ step_id: s.step_id, op: s.op, 피연산자: list(s.operands).map((o) => `${o.role ?? '-'}:${shortId(o.record_id)}·${o.item ?? ''}`), 기간: s.from_ || s.to ? `${s.from_ ?? ''}~${s.to ?? ''}` : '', base: s.base, agg: s.agg, top_n: s.top_n, display: s.display_ref }))} /></Det>
        <Det title="표시 설정 displays"><ObjTable items={Object.entries(m3.displays ?? {}).map(([key, value]) => ({ display_ref: key, ...(value as D) }))} /></Det>
        <Json title="검증 validation 전체" value={validation} />
        <Json title="질문용 계산 CalcResult 전체" value={calcs} />
      </Mid>
    </>
  );
}

// ── ⑤ 모듈 5 ──
function Module5({ r }: { r: D }) {
  const m = r.modules;
  if (!m) return <Empty>모듈이 돌지 않음</Empty>;
  const drawn = list(m.drawn);
  const contents: Record<string, D> = Object.fromEntries(list(m.module3?.chart_contents).map((c) => [c.chart_id, c]));
  const idsOf = (d: D) => (list(d.merged_from).length ? list(d.merged_from).flatMap((id) => list(contents[id]?.record_ids)) : list(contents[d.chart_id]?.record_ids));
  if (drawn.length === 0) return <Empty>{list(m.module3?.chart_contents).length ? '그림 없음 (모듈 5 실패 · 건너뜀)' : '그릴 차트 내용 없음 (모듈 3이 차트를 만들지 않음 → 표로 답변)'}</Empty>;
  return (
    <>
      <ObjTable items={drawn.map((d) => ({ chart_id: d.chart_id, 차트: d.chart_type, 상태: d.status, '출처 표': <RecordIds ids={[...new Set(idsOf(d))]} />, 겹침: list(d.merged_from).join(' + '), 이유: d.reason, 경고: list(d.warnings).join('\n') }))} rowClass={(item) => (item['상태'] === 'drawn' ? 'is-keep' : 'is-drop')} />
      {drawn.map((d) => (
        <div className="pd-chart" key={d.chart_id}>
          <div className="pd-chips"><Chip><b>{d.chart_id}</b></Chip><Chip>{d.chart_type ?? '-'}</Chip><Chip tone={d.status === 'drawn' ? 'ok' : 'bad'}>{d.status}</Chip>{list(d.merged_from).length > 0 && <Chip>겹침 {list(d.merged_from).join(' + ')}</Chip>}</div>
          {d.title && <b>{d.title}</b>}
          <SourceLine ids={[...new Set(idsOf(d))]} label="차트 데이터의 출처 표" />
          {d.reason && <div className="pd-box is-err">{d.reason}</div>}
          {d.figure && <div className="pd-plot"><PlotlyChart figure={d.figure as PlotlyFigure} width={720} height={360} chartType={d.chart_type} /></div>}
        </div>
      ))}
      <Mid>{drawn.filter((d) => d.figure).map((d) => <Json key={d.chart_id} title={`${d.chart_id} Plotly Figure (data · layout)`} value={d.figure} />)}</Mid>
    </>
  );
}

// ── ⑥ 모듈 6 ──
function Module6({ r }: { r: D }) {
  const m = r.modules;
  if (!m) return <Empty>모듈이 돌지 않음</Empty>;
  const answer = m.answer;
  const qa = m.qa ?? {};
  return (
    <>
      {qa.message && <div className="pd-box is-warn"><b>QA 안내</b> {qa.message}</div>}
      {!answer ? <Empty>답변 없음</Empty> : (
        <>
          <div className="pd-answer">{answer.answer}</div>
          <div className="pd-chips"><Chip>method <b>{answer.method}</b></Chip><Chip tone={answer.insufficient ? 'bad' : 'ok'}>{answer.insufficient ? '수치 답변 못 함' : '수치 답변'}</Chip><Chip>인용한 계산 <b>{list(answer.used_step_ids).join(', ') || '없음'}</b></Chip></div>
          {list(answer.caveats).length > 0 && <><h4>주의사항</h4>{list(answer.caveats).map((c, index) => <div className="pd-box is-info" key={index}>{typeof c === 'object' ? <><span className="pd-small">{c.source}</span> {c.text}</> : String(c)}</div>)}</>}
          {list(answer.tables).map((t, index) => (
            <div key={t.table_id ?? index}>
              <h4>{t.title} <span className="pd-small">{t.kind} · {t.table_id}{t.truncated ? ` · 행 ${list(t.rows).length}/${t.total_rows}` : ''}</span></h4>
              <SourceLine ids={t.record_ids} />
              <DataTable columns={t.columns} rows={list(t.rows)} highlight={t.highlight_rows} />
            </div>
          ))}
        </>
      )}
      <Mid>
        <p className="pd-small">{NO_TRACE}</p>
        {answer && <Json title="모듈 6 notes (HCX 실패 · 재시도 사유)" value={answer.notes} />}
        <Json title="에이전트 notes (보조 View · 그리기 실패)" value={m.notes} />
        <Json title="답변 전체" value={answer} />
      </Mid>
    </>
  );
}

// ── QA ──
function QaSection({ r }: { r: D }) {
  const qa = r.modules?.qa;
  if (!qa?.status) return <Empty>QA 결과 없음</Empty>;
  const byPoint: Record<string, D[]> = {};
  for (const issue of list(qa.issues)) (byPoint[issue.point] ??= []).push(issue);
  const grouped = groupIssues(qa.issues);
  const count = (pick: (issue: D) => boolean) => grouped.filter(pick).length;
  const rows = Object.keys(GATE_INFO).filter((point) => list(qa.checked).includes(point) || byPoint[point]).map((point) => {
    const issues = groupIssues(byPoint[point]);
    const errors = issues.filter((i) => i.severity === 'error').length;
    const semantic = issues.filter(isSem).length;
    const format = issues.filter((i) => i.severity === 'warning').length - semantic;
    return [point, GATE_INFO[point][0], gateState(qa, point)?.[1], `${errors} / ${semantic} / ${format} / ${issues.length - errors - semantic - format}`, issues.filter((i) => i.severity !== 'info').map((i) => `${sevLabel(i)} · ${KIND_KO[i.kind] ?? i.kind} ${i.path}${i.count > 1 ? ` (${i.count}건)` : ''}`).join('\n')];
  });
  return (
    <>
      <div className="pd-chips">
        <Chip tone={({ ok: 'ok', warned: 'warn', partial: 'part', stopped: 'bad' } as D)[qa.status]}>QA <b>{STATUS_KO[qa.status] ?? qa.status}</b></Chip>
        {qa.stopped_stage && <Chip tone="bad">멈춘 단계 {qa.stopped_stage}</Chip>}
        <Chip>오류 {count((i) => i.severity === 'error')} · 내용 경고 {count(isSem)} · 형식 경고 {count((i) => i.severity === 'warning' && !isSem(i))} · info {count((i) => i.severity === 'info')}</Chip>
      </div>
      {qa.message && <div className="pd-box is-warn">{qa.message}</div>}
      {list(qa.retries).length > 0 && <p className="pd-small">재시도: {list(qa.retries).map((x) => `${x.point}(${x.why} → ${x.result ?? '-'})`).join(', ')}</p>}
      {list(qa.dropped).length > 0 && <p className="pd-small">뺀 항목: {list(qa.dropped).map((x) => `${x.point} ${x.path}`).join(', ')}</p>}
      {list(qa.skipped).length > 0 && <p className="pd-small">건너뜀: {list(qa.skipped).join(', ')}</p>}
      <p className="pd-small">지점별 자세한 내용은 모듈 사이의 QA 칸에 있습니다.</p>
      <DataTable columns={['지점', '위치', '결과', '오류 / 내용 / 형식 / info 줄', '내용 (오류 · 경고)']} rows={rows} />
      <Mid><Json title="QA 전체" value={qa} /></Mid>
    </>
  );
}

// ── 최종 결과: 펼치면 결론부터 봅니다 ──
function FitPlot({ figure, chartType }: { figure: PlotlyFigure; chartType?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => setWidth(Math.max(260, Math.floor(element.clientWidth)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return <div className="pd-final-plot" ref={ref}>{width > 0 && <PlotlyChart figure={figure} width={width} height={300} chartType={chartType} />}</div>;
}

/** 답변 표와 차트에 실제로 쓴 통계표. 없으면 답변에 넘긴 자료 전체를 씁니다. */
function usedTables(r: D, charts: D[]) {
  const m = r.modules;
  const contents: Record<string, D> = Object.fromEntries(list(m?.module3?.chart_contents).map((c) => [c.chart_id, c]));
  const used = [
    ...list(m?.answer?.tables).flatMap((table) => list(table.record_ids)),
    ...charts.flatMap((d) => (list(d.merged_from).length ? list(d.merged_from) : [d.chart_id]).flatMap((id) => list(contents[id]?.record_ids))),
  ];
  const ids = used.length > 0 ? used : [...list(m?.records), ...list(r.views?.records)].map((record) => record.id);
  return [...new Set(ids.map(tblOf).filter(Boolean))];
}

function KosisSources({ tbls }: { tbls: string[] }) {
  const tables = useContext(TablesContext);
  if (tbls.length === 0) return null;
  return (
    <div className="pd-final-sources">
      <b>KOSIS 통계표</b>
      <ul>
        {tbls.map((tbl) => (
          <li key={tbl}>
            <Kosis tbl={tbl} label={tables[tbl]?.name ?? tbl} />
            <small>{[tables[tbl]?.survey, tbl].filter(Boolean).join(' · ')}</small>
          </li>
        ))}
      </ul>
    </div>
  );
}

function FinalResult({ r }: { r: D }) {
  const m = r.modules;
  const answer = m?.answer;
  const qa = m?.qa;
  const body = answer?.answer ?? r.result?.answer;
  const charts = list(m?.drawn).filter((d) => d.status === 'drawn' && d.figure);
  const table = charts.length === 0 ? list(answer?.tables)[0] : null;
  const caveats = [...new Set(list(answer?.caveats ?? r.result?.caveats).map((c) => (typeof c === 'object' && c ? c.text : c)).filter(Boolean).map(String))];
  const qaMessage = qa?.message && qa.message !== body ? qa.message : '';
  const hasVisual = charts.length > 0 || Boolean(table);
  return (
    <section className={`pd-final${hasVisual ? '' : ' is-single'}`} aria-label="최종 결과">
      <h3>최종 결과</h3>
      {hasVisual && (
        <div className="pd-final-visual">
          {charts.map((d) => (
            <figure key={d.chart_id}>
              {d.title && <figcaption>{d.title}</figcaption>}
              <FitPlot figure={d.figure as PlotlyFigure} chartType={d.chart_type} />
            </figure>
          ))}
          {table && (
            <div>
              <b>{table.title}</b>
              <DataTable columns={table.columns} rows={list(table.rows)} highlight={table.highlight_rows} />
            </div>
          )}
        </div>
      )}
      <div className="pd-final-answer">
        <b>답변</b>
        {body ? <div className="pd-answer">{body}</div> : <Empty>답변이 생성되지 않았습니다.</Empty>}
        <KosisSources tbls={usedTables(r, charts)} />
        {qaMessage && <div className={`pd-box ${qa?.status === 'stopped' ? 'is-err' : 'is-warn'}`}><b>QA 안내</b> {qaMessage}</div>}
        {caveats.length > 0 && <div className="pd-final-caveats"><b>주의사항</b><ul>{caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}</ul></div>}
      </div>
    </section>
  );
}

// ── 화면 ──
const SECTIONS: { key: string; no: string; title: string; Body: (props: { r: D }) => ReactNode; sub: (r: D) => string }[] = [
  { key: 'rewrite', no: '①', title: '질의 재작성', Body: Rewrite, sub: (r) => (r.analysis ? r.analysis.bundle?.rewritten ?? r.analysis.view_bundle?.rewritten ?? STATUS_KO[r.analysis.status] ?? r.analysis.status : '-') },
  { key: 'views', no: '②', title: 'View 검색', Body: Views, sub: (r) => (r.views ? `단위 ${list(r.views.units).length} · View ${list(r.views.records).length}개` : '-') },
  { key: 'm2', no: '③', title: '모듈 2 차트 유형 판단', Body: Module2, sub: (r) => { const charts = r.modules?.chart_plan?.charts; return charts ? list(charts).map((c) => `${c.chart_id} ${c.chart_type ?? '표만'}`).join(' · ') || '차트 없음' : '-'; } },
  { key: 'm3', no: '④', title: '모듈 3 계산·차트 구성', Body: Module3, sub: (r) => { const m3 = r.modules?.module3; return m3 ? `차트 내용 ${list(m3.chart_contents).length} · 계산 ${list(m3.calc_results).length}` : '-'; } },
  { key: 'm5', no: '⑤', title: '모듈 5 차트 그리기', Body: Module5, sub: (r) => { const drawn = r.modules?.drawn; return drawn ? (list(drawn).length ? `그림 ${list(drawn).filter((d) => d.status === 'drawn').length}/${list(drawn).length}` : '그림 없음') : '-'; } },
  { key: 'm6', no: '⑥', title: '모듈 6 답변 생성', Body: Module6, sub: (r) => (r.modules?.answer ? `method ${r.modules.answer.method}` : '답변 없음') },
  { key: 'qa', no: 'QA', title: 'QA 결과', Body: QaSection, sub: (r) => { const qa = r.modules?.qa; return qa ? STATUS_KO[qa.status] ?? qa.status : '-'; } },
];

function stageTone(r: D, key: string) {
  if (key === 'qa') return ({ ok: 'ok', warned: 'warn', partial: 'part', stopped: 'bad' } as D)[r.modules?.qa?.status] ?? '';
  if (key === 'rewrite') return r.analysis ? (r.analysis.status === 'ok' ? 'ok' : 'warn') : '';
  if (key === 'views') return r.views ? (r.views.status === 'ok' ? 'ok' : 'warn') : '';
  const m = r.modules ?? {};
  return ({ m2: m.chart_plan, m3: m.module3, m5: m.drawn, m6: m.answer } as D)[key] ? 'ok' : '';
}

// 결과가 없는 단계는 회색, QA는 경고·중단이면 주황·빨강으로 보여줍니다.
function flowClass(r: D, key: string) {
  const tone = stageTone(r, key);
  if (!tone) return 'is-empty';
  return key === 'qa' && tone !== 'ok' ? `is-${tone}` : '';
}

function Stage({ id, module, no, title, sub, children }: { id: string; module: ModuleKey; no: string; title: string; sub: string; children: ReactNode }) {
  const expand = useContext(ExpandContext);
  const [open, setOpen] = useState(true);
  useEffect(() => { if (expand.signal) setOpen(expand.stages); }, [expand.signal, expand.stages]);
  return (
    <details className="pd-stage" id={id} style={moduleStyle(module)} open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary><span className="pd-num">{no}</span><b>{title}</b><span className="pd-sub">{sub}</span></summary>
      {open && <div className="pd-stage-body">{children}</div>}
    </details>
  );
}

function Pipeline({ response }: { response: ChatResponse }) {
  const r = response as unknown as D;
  const root = useRef<HTMLDivElement>(null);
  const [expand, setExpand] = useState({ signal: 0, stages: true, deep: false });
  const tables = useMemo(() => tablesOf(r), [r]);
  const qa = r.modules?.qa;
  const go = (id: string) => {
    const element = root.current?.querySelector<HTMLDetailsElement>(`[id="${id}"]`);
    if (!element) return;
    element.open = true;
    element.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  const set = (stages: boolean, deep: boolean) => setExpand((current) => ({ signal: current.signal + 1, stages, deep }));

  return (
    <ExpandContext.Provider value={expand}>
      <TablesContext.Provider value={tables}>
        <div className="pd-root" ref={root}>
          <FinalResult r={r} />
          <h3 className="pd-section-title">중간 단계</h3>
          {Object.keys(r.timings ?? {}).length > 0 && <div className="pd-chips">{Object.entries(r.timings).map(([key, value]) => <Chip key={key}>{key} {Number(value).toFixed(1)}초</Chip>)}</div>}
          <nav className="pd-flow" aria-label="단계 바로가기">
            {SECTIONS.map(({ key, no, title, sub }) => (
              <span className="pd-flow-group" key={key}>
                <button type="button" className={`pd-flow-step ${flowClass(r, key)}`} style={moduleStyle(STAGE_MODULE[key])} onClick={() => go(`pd-sec-${key}`)}>
                  <b>{no === 'QA' ? '' : `${no} `}{title.replace(/^모듈 \d /, '')}</b><span>{sub(r)}</span>
                </button>
                {(GATES_AFTER[key] ?? []).map((point) => {
                  const state = gateState(qa, point);
                  return state && <button key={point} type="button" className={`pd-flow-gate is-${state[0]}`} title={`${GATE_INFO[point][0]}: ${state[1]}`} onClick={() => go(`pd-gate-${point}`)}>{point}</button>;
                })}
              </span>
            ))}
          </nav>
          <div className="pd-tools">
            <button type="button" onClick={() => set(true, true)}>중간 결과까지 모두 펼치기</button>
            <button type="button" onClick={() => set(true, false)}>단계만 펼치기</button>
            <button type="button" onClick={() => set(false, false)}>모두 접기</button>
          </div>
          {SECTIONS.map(({ key, no, title, Body, sub }) => (
            <div key={key}>
              <Stage id={`pd-sec-${key}`} module={STAGE_MODULE[key]} no={no} title={title} sub={sub(r)}><Body r={r} /></Stage>
              {(GATES_AFTER[key] ?? []).map((point) => <Gate key={point} qa={qa} point={point} />)}
            </div>
          ))}
        </div>
      </TablesContext.Provider>
    </ExpandContext.Provider>
  );
}

export function PipelineDashboard({ encoded, labels }: { encoded: string; labels?: string[] }) {
  const [responses, setResponses] = useState<ChatResponse[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setResponses(null);
    setFailed(false);
    setIndex(0);
    decodeResponses(encoded)
      .then((value) => { if (!cancelled) setResponses(value); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [encoded]);

  if (failed) return <p className="adm-error" role="alert">저장된 중간 결과를 열지 못했습니다.</p>;
  if (!responses) return <p className="pd-empty" role="status">중간 결과를 불러오는 중입니다.</p>;
  return (
    <>
      {responses.length > 1 && (
        <div className="adm-tabs is-views" role="tablist" aria-label="비교한 통계표">
          {responses.map((_, position) => <button key={position} type="button" role="tab" aria-selected={index === position} className={index === position ? 'is-on' : ''} onClick={() => setIndex(position)}>{labels?.[position] ?? `응답 ${position + 1}`}</button>)}
        </div>
      )}
      <Pipeline key={index} response={responses[index]} />
    </>
  );
}
