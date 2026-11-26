// 되묻기 화면의 지역·시점·대상 고르기 칸입니다. (피그마 5-1 ~ 5-5)
// 빠진 조건이 하나면 넓게(one), 둘·셋이면 나란히 칸을 나눠(two·three) 그립니다.
import { useState, type ReactNode } from 'react';
import { DISTRICT_FIRST_COUNT, DISTRICTS } from '../data/districts';
import { SIDO, TARGET_GROUPS, YEARS } from '../data/examples';

export type ClarifyLayout = 'one' | 'two' | 'three';
export type RegionPick = { regions: string[]; district: string };
export type TimePick = { mode: 'year' | 'range'; years: number[] };
// 백엔드 후보에 없는 값은 흐리게 두고 누를 수 없게 합니다. (null = 모두 고를 수 있음)
export type CanPick<T> = ((value: T) => boolean) | null;

const PROVINCES = SIDO.filter((name) => name !== '전국');
// 세 칸 화면의 대상 목록 (피그마 5-5)
const COMPACT_TARGETS = ['전체 가구', '1인 가구', '다문화 가구', '한부모 가구', '남성', '여성', '청년', '고령', '외국인', '출생아', '혼인', '이혼'];
const COLUMNS = {
  region: { one: 6, two: 4, three: 3 },
  time: { one: 5, two: 3, three: 3 },
} as const;

const cls = (...names: (string | false | undefined)[]) => names.filter(Boolean).join(' ');

function Opt({ on, soft, off, onClick, children }: { on?: boolean; soft?: boolean; off?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" className={cls('clarify-opt', on && 'on', soft && 'soft')} aria-pressed={on || soft} disabled={off} onClick={onClick}>
      {children}
    </button>
  );
}

function Quick({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" className="clarify-quick-chip" onClick={onClick}>{label}</button>;
}

// 둘·셋 화면에서 한 칸의 머리 (제목 · 고른 시도 · 오른쪽 버튼)
function ColumnHead({ title, sub, action }: { title: string; sub?: string; action?: ReactNode }) {
  return (
    <div className="clarify-col-head">
      <h3>{title}{sub && <em> · {sub}</em>}</h3>
      {action}
    </div>
  );
}

// 하나 화면의 '빠른 선택' 줄
function QuickRow({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="clarify-quick">
      <span className="clarify-quick-label">빠른 선택</span>
      {children}
      {right && <span className="clarify-quick-right">{right}</span>}
    </div>
  );
}

type RegionProps = { layout: ClarifyLayout; value: RegionPick; onChange: (next: RegionPick) => void; canPick: CanPick<string>; question?: boolean };

export function RegionPicker({ layout, value, onChange, canPick, question }: RegionProps) {
  const [expanded, setExpanded] = useState(false);
  // 구 목록을 보고 있는 시 (예: 수원시)
  const [openCity, setOpenCity] = useState<string | null>(null);
  // 둘·셋 화면: 시도를 고르면 같은 칸이 시군구 목록으로 바뀝니다.
  const [view, setView] = useState<'sido' | 'district'>(value.regions.length === 1 && value.district !== '전체' ? 'district' : 'sido');
  const one = layout === 'one';
  const single = value.regions.length === 1 ? value.regions[0] : '';
  const nodes = single ? DISTRICTS[single] ?? [] : [];
  const city = openCity ? nodes.find((node) => node.name === openCity) : undefined;
  const hidden = Math.max(0, nodes.length - DISTRICT_FIRST_COUNT);
  const shown = expanded ? nodes : nodes.slice(0, DISTRICT_FIRST_COUNT);
  const usable = (name: string) => !canPick || canPick(name);

  const reset = () => {
    setExpanded(false);
    setOpenCity(null);
  };
  const pickSido = (name: string) => {
    reset();
    if (one) {
      const regions = value.regions.includes(name) ? value.regions.filter((item) => item !== name) : [...value.regions, name];
      onChange({ regions, district: '전체' });
      return;
    }
    onChange({ regions: [name], district: '전체' });
    if ((DISTRICTS[name] ?? []).length > 0) setView('district');
  };
  const pickDistrict = (district: string) => onChange({ regions: [single], district });
  const pickNode = (name: string, hasChildren: boolean) => {
    pickDistrict(name);
    if (hasChildren) setOpenCity(name);
  };
  const nationwide = () => {
    reset();
    setView('sido');
    onChange({ regions: ['전국'], district: '전체' });
  };
  const backToSido = () => {
    reset();
    setView('sido');
  };

  // 하나 화면은 고른 시군구를 옅게, 둘·셋 화면은 진하게 칠합니다. (피그마 5-1 · 5-4)
  const mark = (on: boolean) => (one ? { soft: on } : { on });
  const districtButtons = city?.children ? (
    <>
      <Opt {...mark(value.district === city.name)} onClick={() => pickDistrict(city.name)}>전체</Opt>
      {city.children.map((gu) => {
        const district = `${city.name} ${gu}`;
        return <Opt key={gu} {...mark(value.district === district)} onClick={() => pickDistrict(district)}>{gu}</Opt>;
      })}
      <Opt onClick={() => setOpenCity(null)}>← 시군구로</Opt>
    </>
  ) : (
    <>
      <Opt {...mark(Boolean(single) && value.district === '전체')} onClick={() => single && pickDistrict('전체')}>전체</Opt>
      {shown.map((node) => (
        <Opt key={node.name} {...mark(value.district === node.name || value.district.startsWith(`${node.name} `))} onClick={() => pickNode(node.name, Boolean(node.children))}>
          {node.name}{node.children ? ' ›' : ''}
        </Opt>
      ))}
      {hidden > 0 && !expanded && <Opt onClick={() => setExpanded(true)}>더보기 +{hidden}</Opt>}
    </>
  );
  const sidoButtons = SIDO.map((name) => (
    <Opt key={name} on={value.regions.includes(name)} off={!usable(name)} onClick={() => pickSido(name)}>{name}</Opt>
  ));
  const columns = COLUMNS.region[layout];

  if (one) {
    const label = city ? `${single} · ${city.name} · 구 (선택)` : single ? `${single} · 시군구 (선택)` : '시군구 (선택)';
    return (
      <div className="clarify-body">
        <QuickRow>
          <Quick label="전국으로 보기" onClick={nationwide} />
          <Quick label="시도별로 비교하기" onClick={() => { reset(); onChange({ regions: PROVINCES.filter(usable), district: '전체' }); }} />
        </QuickRow>
        <div className={`clarify-grid cols-${columns}`}>{sidoButtons}</div>
        <div className="clarify-label">{label}</div>
        <div className={cls(`clarify-grid cols-${columns} clarify-districts`, expanded && 'scroll')}>{districtButtons}</div>
      </div>
    );
  }

  const showDistricts = view === 'district' && nodes.length > 0;
  const title = question ? '어느 지역인가요?' : '지역';
  const sub = single ? [single, openCity].filter(Boolean).join(' ') : undefined;
  const action = showDistricts
    ? <button type="button" className="clarify-back" onClick={backToSido}>‹ 시도 변경</button>
    : <Quick label={layout === 'two' ? '전국으로 보기' : '전국'} onClick={nationwide} />;
  return (
    <section className="clarify-col" aria-label="지역 고르기">
      <ColumnHead title={title} sub={question ? undefined : sub} action={action} />
      <div className={cls(`clarify-grid cols-${columns}`, expanded && 'scroll')}>{showDistricts ? districtButtons : sidoButtons}</div>
    </section>
  );
}

type TimeProps = { layout: ClarifyLayout; value: TimePick; onChange: (next: TimePick) => void; canPick: CanPick<number>; latest: number; question?: boolean };

export function TimePicker({ layout, value, onChange, canPick, latest, question }: TimeProps) {
  const sorted = [...value.years].sort((a, b) => a - b);
  const start = sorted[0];
  const end = sorted.at(-1);
  const pick = (year: number) => {
    if (value.mode === 'year') return onChange({ ...value, years: [year] });
    // 기간: 처음 누른 해 = 시작, 다음에 누른 해 = 끝 (다시 누르면 새로 시작)
    const years = value.years.length === 1 && value.years[0] !== year ? [value.years[0], year].sort((a, b) => a - b) : [year];
    onChange({ ...value, years });
  };
  const recent = (count: number) => onChange({ mode: 'range', years: [latest - count + 1, latest] });
  const grid = (
    <div className={`clarify-grid cols-${COLUMNS.time[layout]}`}>
      {YEARS.map((year) => {
        const edge = year === start || year === end;
        const between = start !== undefined && end !== undefined && year > start && year < end;
        return <Opt key={year} on={edge} soft={between} off={canPick ? !canPick(year) : false} onClick={() => pick(year)}>{year}</Opt>;
      })}
    </div>
  );

  if (layout === 'one') {
    const changeMode = (mode: TimePick['mode']) => onChange({ mode, years: mode === 'year' ? value.years.slice(0, 1) : value.years });
    const toggle = (
      <span className="clarify-toggle" role="group" aria-label="시점 방식">
        <button type="button" className={value.mode === 'year' ? 'on' : ''} aria-pressed={value.mode === 'year'} onClick={() => changeMode('year')}>한 해</button>
        <button type="button" className={value.mode === 'range' ? 'on' : ''} aria-pressed={value.mode === 'range'} onClick={() => changeMode('range')}>기간</button>
      </span>
    );
    return (
      <div className="clarify-body">
        <QuickRow right={toggle}>
          <Quick label="가장 최신 연도" onClick={() => onChange({ ...value, years: [latest] })} />
          <Quick label="최근 5년" onClick={() => recent(5)} />
          <Quick label="최근 10년" onClick={() => recent(10)} />
        </QuickRow>
        {grid}
      </div>
    );
  }
  return (
    <section className="clarify-col" aria-label="시점 고르기">
      <ColumnHead title={question ? '언제인가요?' : '시점'} action={<Quick label="최근 5년" onClick={() => recent(5)} />} />
      {grid}
    </section>
  );
}

type TargetProps = { layout: ClarifyLayout; value: string; onChange: (next: string) => void; question?: boolean };

export function TargetPicker({ layout, value, onChange, question }: TargetProps) {
  if (layout === 'one') {
    return (
      <div className="clarify-body">
        {TARGET_GROUPS.map((group) => (
          <div className="clarify-target-group" key={group.label}>
            <div className="clarify-label">{group.label}</div>
            <div className="clarify-chips">
              {group.items.map((item) => (
                <button type="button" key={item} className={cls('clarify-chip', value === item && 'on')} aria-pressed={value === item} onClick={() => onChange(item)}>{item}</button>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }
  return (
    <section className="clarify-col" aria-label="대상 고르기">
      <ColumnHead title={question ? '누구에 대한 통계인가요?' : '대상'} action={<Quick label="전체 인구" onClick={() => onChange('전체 인구')} />} />
      <div className="clarify-grid cols-2">
        {COMPACT_TARGETS.map((item) => <Opt key={item} on={value === item} onClick={() => onChange(item)}>{item}</Opt>)}
      </div>
    </section>
  );
}
