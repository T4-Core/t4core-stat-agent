// Main 화면의 지역·시점·대상 선택 드롭다운입니다.
import { useMemo, useState } from 'react';
import search from '../assets/figma/search.svg';
import { SEOUL_MAIN, SEOUL_MORE, SIDO, TARGET_GROUPS, YEARS } from '../data/examples';
import type { Filters, TimeMode } from '../data/types';

type PanelProps = {
  filters: Filters;
  onCancel: () => void;
  onApply: (patch: Partial<Filters>) => void;
};

function PanelFooter({ label, canApply, onCancel, onApply }: { label: string; canApply: boolean; onCancel: () => void; onApply: () => void }) {
  return (
    <div className="panel-footer">
      <span className="panel-selected">선택됨 <em>{label}</em></span>
      <span className="panel-actions">
        <button type="button" className="panel-button" onClick={onCancel}>취소</button>
        <button type="button" className="panel-button primary" disabled={!canApply} onClick={onApply}>적용</button>
      </span>
    </div>
  );
}

export function RegionPanel({ filters, onCancel, onApply }: PanelProps) {
  const [regions, setRegions] = useState(filters.regions.length > 0 ? filters.regions : ['서울']);
  const [district, setDistrict] = useState(filters.district);
  const [expanded, setExpanded] = useState(false);
  const first = regions[0] ?? '';
  const districts = first === '서울' && regions.length === 1 ? (expanded ? [...SEOUL_MAIN, ...SEOUL_MORE] : SEOUL_MAIN) : ['전체'];

  const toggle = (name: string) => {
    setDistrict('전체');
    setRegions((current) => (current.includes(name) ? current.filter((item) => item !== name) : [...current, name]));
  };
  const label = regions.length > 1 ? `${first} 외 ${regions.length - 1}` : first ? `${first} ${district}` : '없음';

  return (
    <section className="panel region-panel" aria-label="지역 선택">
      <div className="panel-head">
        <h4>지역 선택</h4>
        <span>여러 곳을 고르면 비교해 드려요</span>
      </div>
      <div className="option-grid six">
        {SIDO.map((name) => (
          <button type="button" key={name} className={regions.includes(name) ? 'opt selected' : 'opt'} aria-pressed={regions.includes(name)} onClick={() => toggle(name)}>{name}</button>
        ))}
      </div>
      <div className="panel-label">{first || '지역'} · 시군구 (선택)</div>
      <div className={expanded ? 'option-grid six scroll' : 'option-grid six'}>
        {districts.map((name) => (
          <button type="button" key={name} className={district === name ? 'opt soft' : 'opt'} aria-pressed={district === name} onClick={() => setDistrict(name)}>{name}</button>
        ))}
        {first === '서울' && regions.length === 1 && !expanded && (
          <button type="button" className="opt" onClick={() => setExpanded(true)}>더보기 +15</button>
        )}
      </div>
      <PanelFooter label={label} canApply={regions.length > 0} onCancel={onCancel} onApply={() => onApply({ regions, district })} />
    </section>
  );
}

export function TimePanel({ filters, onCancel, onApply }: PanelProps) {
  const [mode, setMode] = useState<TimeMode>(filters.timeMode);
  const [years, setYears] = useState(filters.years);
  const sorted = useMemo(() => [...years].sort((a, b) => a - b), [years]);
  const start = sorted[0];
  const end = sorted.at(-1);

  const pick = (year: number) => {
    if (mode === 'year') {
      setYears([year]);
      return;
    }
    setYears((current) => (current.length === 1 && current[0] !== year ? [current[0], year] : [year]));
  };
  const changeMode = (next: TimeMode) => {
    setMode(next);
    setYears((current) => (next === 'year' ? current.slice(0, 1) : current));
  };
  const label = sorted.length === 0 ? '없음' : sorted.length === 1 ? String(start) : `${start} ~ ${end}`;
  const panelClass = mode === 'range' ? 'panel time-panel range' : 'panel time-panel';

  return (
    <section className={panelClass} aria-label="시점 선택">
      <div className="panel-head time-head">
        <h4>시점 선택</h4>
        <div className="time-toggle" role="group" aria-label="시점 방식">
          <button type="button" className={mode === 'year' ? 'on' : ''} aria-pressed={mode === 'year'} onClick={() => changeMode('year')}>연도</button>
          <button type="button" className={mode === 'range' ? 'on' : ''} aria-pressed={mode === 'range'} onClick={() => changeMode('range')}>기간</button>
        </div>
      </div>
      <div className="year-grid">
        {YEARS.map((year) => {
          const edge = year === start || year === end;
          const between = mode === 'range' && start !== undefined && end !== undefined && year > start && year < end;
          return (
            <button type="button" key={year} className={edge ? 'year selected' : between ? 'year between' : 'year'} aria-pressed={edge} onClick={() => pick(year)}>{year}</button>
          );
        })}
      </div>
      <div className="panel-footer time-footer">
        <span className="time-selected"><b>선택됨</b>{label}</span>
        <span className="panel-actions">
          <button type="button" className="panel-button" onClick={onCancel}>취소</button>
          <button type="button" className="panel-button primary" disabled={sorted.length === 0} onClick={() => onApply({ timeMode: mode, years: sorted })}>적용</button>
        </span>
      </div>
    </section>
  );
}

export function TargetPanel({ filters, onCancel, onApply }: PanelProps) {
  const [target, setTarget] = useState(filters.target || '1인 가구');
  const [keyword, setKeyword] = useState('');
  const groups = TARGET_GROUPS
    .map((group) => ({ ...group, items: group.items.filter((item) => item.includes(keyword.trim())) }))
    .filter((group) => group.items.length > 0);

  return (
    <section className="panel target-panel" aria-label="대상 선택">
      <div className="panel-head">
        <h4>대상 선택</h4>
        <span>누구(무엇)에 대한 통계인가요?</span>
      </div>
      <label className="target-search">
        <img src={search} alt="" width={13.68} height={13.68} />
        <input value={keyword} placeholder="대상 검색 예) 청년, 다문화" aria-label="대상 검색" onChange={(event) => setKeyword(event.target.value)} />
      </label>
      {groups.map((group) => (
        <div className="target-group" key={group.label}>
          <div className="target-label">{group.label}</div>
          <div className="target-items">
            {group.items.map((item) => (
              <button type="button" key={item} className={target === item ? 'target-chip selected' : 'target-chip'} aria-pressed={target === item} onClick={() => setTarget(item)}>{item}</button>
            ))}
          </div>
        </div>
      ))}
      {groups.length === 0 && <p className="target-empty">검색 결과가 없어요</p>}
      <PanelFooter label={target || '없음'} canApply={Boolean(target)} onCancel={onCancel} onApply={() => onApply({ target })} />
    </section>
  );
}
