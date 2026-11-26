// 되묻기: 시점·지역·대상 중 빠진 조건을 고릅니다. (피그마 5-1 ~ 5-5)
// 선택지는 프론트 목록으로 그리고, 백엔드 후보에 없는 시도·연도는 흐리게 막습니다.
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { toClarifications, toKnownSlots } from '../api/adapters';
import send from '../assets/figma/send-button.svg';
import { Character } from '../character';
import { RegionPicker, TargetPicker, TimePicker, type CanPick, type ClarifyLayout, type RegionPick, type TimePick } from '../components/ClarifyPickers';
import { Frame } from '../components/Layout';
import { DISTRICTS } from '../data/districts';
import { SIDO, YEARS } from '../data/examples';
import type { ClarificationGroup } from '../data/types';
import { continueRun, usePayload } from '../store/agent';
import { createRun, removeRun, routeForRun, useRun } from '../store/history';

const SLOTS = ['지역', '시점', '대상'] as const;
type Slot = (typeof SLOTS)[number];

// 백엔드 되묻기 후보 수 (configs/pipeline.yaml n_options). 이만큼 왔으면 뒤쪽이 잘렸을 수 있습니다.
const OPTION_LIMIT = 20;
// 백엔드는 시도를 정식 이름(서울특별시)으로 보냅니다. 줄임말과 맞춰 볼 앞부분
const SIDO_PREFIX: Record<string, string[]> = {
  광주: ['광주광역'], 충북: ['충청북', '충북'], 충남: ['충청남', '충남'], 전북: ['전라북', '전북'], 전남: ['전라남', '전남'], 경북: ['경상북', '경북'], 경남: ['경상남', '경남'],
};
const LAYOUTS: Record<number, ClarifyLayout> = { 1: 'one', 2: 'two', 3: 'three' };
const LAYOUT_LIMIT = 3;
const ONE_TITLE: Record<Slot, string> = { 지역: '어느 지역의 통계를 볼까요?', 시점: '언제의 통계를 볼까요?', 대상: '누구(무엇)에 대한 통계를 볼까요?' };
const EXAMPLE: Record<Slot, string> = { 지역: '서울', 시점: '최근 5년', 대상: '1인 가구' };
const ONE_EXAMPLE: Record<Slot, string> = { 지역: '서울, 부산 해운대구', 시점: '2020년, 최근 5년', 대상: '1인 가구, 65세 이상' };
const ICONS: Record<Slot, string[]> = {
  지역: [
    'M8 14C8 14 12.67 10 12.67 6.67A4.67 4.67 0 0 0 3.33 6.67C3.33 10 8 14 8 14Z',
    'M9.67 6.67A1.67 1.67 0 1 1 6.33 6.67A1.67 1.67 0 0 1 9.67 6.67Z',
  ],
  시점: [
    'M4.67 3.33H11.33C12.44 3.33 13.33 4.23 13.33 5.33V11.33C13.33 12.44 12.44 13.33 11.33 13.33H4.67C3.56 13.33 2.67 12.44 2.67 11.33V5.33C2.67 4.23 3.56 3.33 4.67 3.33Z',
    'M2.67 6.67H13.33M5.33 2V4.67M10.67 2V4.67',
  ],
  대상: [
    'M10.67 5.33A2.67 2.67 0 1 1 5.33 5.33A2.67 2.67 0 0 1 10.67 5.33Z',
    'M2.67 13.33C3.33 10.67 5.33 9.33 8 9.33C10.67 9.33 12.67 10.67 13.33 13.33',
  ],
};

const joinAnd = (items: string[]) => items.join('과 ');
const sidoMatch = (name: string, value: string) => value === name || (SIDO_PREFIX[name] ?? [name]).some((prefix) => value.startsWith(prefix));

function sidoFilter(group?: ClarificationGroup): CanPick<string> {
  if (!group) return null;
  const found = new Set(SIDO.filter((name) => group.options.some((option) => sidoMatch(name, option.value))));
  return found.size > 0 ? (name) => found.has(name) : null;
}

function yearFilter(group?: ClarificationGroup): CanPick<number> {
  const years = (group?.options ?? []).map((option) => /^(\d{4})년$/.exec(option.value)?.[1]).filter(Boolean).map(Number);
  if (years.length === 0) return null;
  const found = new Set(years);
  const oldest = Math.min(...years);
  // 후보가 가득 찼으면 가장 오래된 해보다 앞은 잘린 것일 수 있어 막지 않습니다.
  const cut = (group?.options.length ?? 0) >= OPTION_LIMIT;
  return (year) => found.has(year) || (cut && year < oldest);
}

function regionLabel({ regions, district }: RegionPick) {
  const [first, ...rest] = regions;
  if (!first) return '';
  if (rest.length > 0) return `${first} 외 ${rest.length}`;
  return (DISTRICTS[first] ?? []).length > 0 ? `${first} ${district}` : first;
}

function timeLabel(years: number[]) {
  const sorted = [...years].sort((a, b) => a - b);
  if (sorted.length === 0) return '';
  return sorted.length === 1 ? String(sorted[0]) : `${sorted[0]}~${sorted.at(-1)}`;
}

function SlotIcon({ slot }: { slot: Slot }) {
  return (
    <svg className="clarify-slot-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      {ICONS[slot].map((d) => <path key={d} d={d} stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" strokeLinejoin="round" />)}
    </svg>
  );
}

export function ClarifyPage() {
  const { id } = useParams();
  const run = useRun(id);
  const navigate = useNavigate();
  const { payload, loading } = usePayload(id);
  const response = payload?.responses[0];
  const groups = useMemo(() => (response ? toClarifications(response) : []), [response]);
  const known = useMemo(() => (response ? toKnownSlots(response) : {}), [response]);
  const [region, setRegion] = useState<RegionPick>({ regions: [], district: '전체' });
  const [time, setTime] = useState<TimePick>({ mode: 'range', years: [] });
  const [target, setTarget] = useState('');
  const [typed, setTyped] = useState('');
  // 직접 입력으로 새 질문을 보낸 뒤: 기록을 지우면 화면이 바로 다시 그려지므로 '처음으로' 이동을 막습니다.
  const leaving = useRef(false);

  useEffect(() => {
    if (run && run.status !== 'needs_clarification') navigate(routeForRun(run), { replace: true });
  }, [navigate, run]);

  const missing = SLOTS.filter((slot) => groups.some((group) => group.slot === slot));
  if (!run) return leaving.current ? null : <Navigate to="/" replace />;
  if (loading) return <Frame variant="main"><span /></Frame>;
  if (!response || missing.length === 0) return <Navigate to="/" replace />;

  const layout = LAYOUTS[Math.min(missing.length, LAYOUT_LIMIT)];
  const groupOf = (slot: Slot) => groups.find((group) => group.slot === slot);
  const canYear = yearFilter(groupOf('시점'));
  const latest = Math.max(...YEARS.filter((year) => !canYear || canYear(year)));
  const picked: Record<Slot, string> = { 지역: regionLabel(region), 시점: timeLabel(time.years), 대상: target };
  const done = missing.filter((slot) => picked[slot]);
  const rest = missing.filter((slot) => !picked[slot]);
  const complete = rest.length === 0;
  // 둘 화면은 아무것도 안 골랐을 때 칸 제목을 질문으로 보여줍니다. (피그마 5-4)
  const question = layout === 'two' && done.length === 0;
  const others = SLOTS.filter((slot) => !missing.includes(slot));

  const title = layout === 'one' ? ONE_TITLE[missing[0]] : layout === 'two' ? `${joinAnd(missing)}을 알려주세요` : '어떤 통계를 볼까요?';
  const subtitle = layout === 'one'
    ? `${joinAnd(others)}은 확인했어요. ${missing[0]}만 알려주시면 바로 찾아드릴게요.`
    : layout === 'two'
      ? `${others[0]}은 확인했어요. 두 가지만 더 알려주시면 바로 찾아드릴게요.`
      : '지역·시점·대상을 알려주시면 바로 찾아드릴게요.';

  const hint = () => {
    const pickedText = done.map((slot) => picked[slot]).join(', ');
    if (done.length === 0) {
      if (layout !== 'one') return <>{layout === 'two' ? joinAnd(missing) : missing.join('·')}을 모두 골라주세요.</>;
      if (missing[0] === '시점') return time.mode === 'range' ? '시작 연도와 끝 연도를 골라주세요.' : '연도를 하나 골라주세요.';
      if (missing[0] === '대상') return '대상을 하나 골라주세요.';
      return '지역을 골라주세요. 여러 곳을 고르면 비교해 드려요.';
    }
    const tail = rest.length > 0 ? ` · ${joinAnd(rest)}을 골라주세요.` : missing[0] === '지역' && layout === 'one' ? ' · 여러 곳을 고르면 비교해 드려요.' : '';
    return <>선택됨 <em>{pickedText}</em>{tail}</>;
  };

  const submit = () => {
    const values: Record<Slot, string[]> = {
      지역: region.regions.length === 1 && region.district !== '전체' ? [`${region.regions[0]} ${region.district}`] : region.regions,
      시점: time.years.length === 0 ? [] : [`${timeLabel(time.years)}년`],
      대상: target ? [target] : [],
    };
    const selections = Object.fromEntries(missing.map((slot) => [groupOf(slot)!.slot, values[slot]]));
    continueRun(run.id, response, { selections });
    navigate(`/generating/${run.id}`, { replace: true });
  };
  const rewrite = () => {
    navigate('/', { replace: true });
    removeRun(run.id);
  };
  // 직접 입력: 원래 질문 뒤에 붙여 새로 검색합니다.
  const ask = (event: FormEvent) => {
    event.preventDefault();
    const text = typed.trim();
    if (!text) return;
    const next = createRun({ question: `${run.question} ${text}`, requestQuestion: `${run.requestQuestion ?? run.question} ${text}`, tags: run.tags ?? [] });
    leaving.current = true;
    navigate(`/generating/${next.id}`, { replace: true });
    removeRun(run.id);
  };

  const placeholder = `직접 입력해도 돼요 예) ${layout === 'one' ? ONE_EXAMPLE[missing[0]] : missing.map((slot) => EXAMPLE[slot]).join(', ')}`;

  return (
    <Frame variant="main">
      <div className="query-pill clarify-pill">
        <span className="query-text">{run.question}</span>
        {SLOTS.map((slot) => {
          if (missing.includes(slot)) return <span key={slot} className="clarify-tag ask">{slot} ?</span>;
          return known[slot] ? <span key={slot} className="clarify-tag">{known[slot]}</span> : null;
        })}
      </div>
      <Character className="clarify-sloth" size="M" motion="asking" />
      <div className="clarify-heading">
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>

      <section className={`clarify-card layout-${layout}`} aria-label="추가 조건 선택">
        <div className="clarify-slots">
          {SLOTS.map((slot) => {
            const asking = missing.includes(slot);
            return (
              <div key={slot} className={asking ? 'clarify-slot ask' : 'clarify-slot'}>
                <SlotIcon slot={slot} />
                <span className="clarify-slot-text"><small>{slot}</small><b>{asking ? '알려주세요' : known[slot] || '확인했어요'}</b></span>
                <span className="clarify-badge" aria-label={asking ? '선택 필요' : '확인됨'}>
                  {asking ? '?' : <svg width="10" height="8" viewBox="0 0 10 8" fill="none" aria-hidden="true"><path d="M1.2 4.1L3.8 6.6L8.8 1.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                </span>
              </div>
            );
          })}
        </div>

        <div className="clarify-columns">
          {missing.includes('지역') && <RegionPicker layout={layout} value={region} onChange={setRegion} canPick={sidoFilter(groupOf('지역'))} question={question} />}
          {missing.includes('시점') && <TimePicker layout={layout} value={time} onChange={setTime} canPick={canYear} latest={latest} question={question} />}
          {missing.includes('대상') && <TargetPicker layout={layout} value={target} onChange={setTarget} question={question} />}
        </div>

        <footer className="clarify-footer">
          <span className="clarify-hint">{hint()}</span>
          <button type="button" className="clarify-button" onClick={rewrite}>질문 다시 쓰기</button>
          <button type="button" className="clarify-button primary" disabled={!complete} onClick={submit}>이 조건으로 검색</button>
        </footer>
      </section>

      <form className="clarify-composer" onSubmit={ask}>
        <input value={typed} placeholder={placeholder} aria-label="조건 직접 입력" onChange={(event) => setTyped(event.target.value)} />
        <button type="submit" aria-label="입력한 조건으로 검색" disabled={!typed.trim()}><img src={send} alt="" width={44} height={44} /></button>
      </form>
    </Frame>
  );
}
