// Main 화면의 지역·시점·대상 선택 드롭다운입니다.
import { useMemo, useState } from 'react';
import search from '../assets/figma/search.svg';
import { DISTRICT_FIRST_COUNT, DISTRICTS } from '../data/districts';
import { SIDO, TARGET_GROUPS, YEARS } from '../data/examples';
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

// 지역 팝업의 기본값 (시안: 처음 열면 '선택됨 서울 전체')
const DEFAULT_REGIONS = ['서울'];

export function RegionPanel({ filters, onCancel, onApply }: PanelProps) {
  // regions 는 사용자가 직접 누른 지역입니다.
  // - 한 번도 안 눌렀으면 기본값 '서울 전체'를 쓰되 버튼은 칠하지 않습니다.
  // - 눌렀다가 모두 빼면 '선택됨 없음'이 되고 적용할 수 없습니다.
  // (이미 적용한 지역이 있으면 그 지역이 칠해진 채로 열림)
  const [regions, setRegions] = useState(filters.regions);
  const [touched, setTouched] = useState(filters.regions.length > 0);
  // district 값: '전체' | 시군구('수원시', '종로구') | 시+구('수원시 장안구')
  const [district, setDistrict] = useState(filters.district);
  const [expanded, setExpanded] = useState(false);
  // 구 목록을 보고 있는 시. 이미 '수원시 장안구'를 적용했다면 수원시의 구 목록으로 바로 열립니다.
  const [openCity, setOpenCity] = useState<string | null>(filters.district.includes(' ') ? filters.district.split(' ')[0] : null);
  const picked = regions.length > 0;
  const effective = picked ? regions : touched ? [] : DEFAULT_REGIONS;
  const first = effective[0] ?? '';
  // 시도를 하나만 골랐을 때만 시군구를 보여줍니다. (여러 곳·전국·세종은 '전체'만)
  const nodes = effective.length === 1 ? DISTRICTS[first] ?? [] : [];
  const city = openCity ? nodes.find((node) => node.name === openCity) : undefined;
  const hidden = Math.max(0, nodes.length - DISTRICT_FIRST_COUNT);
  const shown = expanded ? nodes : nodes.slice(0, DISTRICT_FIRST_COUNT);

  // 지역을 누르면 시군구는 '전체'로 돌아가고, 펼침·구 목록도 닫습니다.
  const toggle = (name: string) => {
    setTouched(true);
    setDistrict('전체');
    setExpanded(false);
    setOpenCity(null);
    setRegions((current) => (current.includes(name) ? current.filter((item) => item !== name) : [...current, name]));
  };
  // 기본값 상태에서 시군구를 바로 누르면 서울도 함께 고른 것으로 칩니다.
  const pickDistrict = (value: string) => {
    if (!picked) setRegions(DEFAULT_REGIONS);
    setTouched(true);
    setDistrict(value);
  };
  // 시군구를 누를 때: 구가 있는 시면 그 시를 고르고 구 목록으로 바꿉니다.
  const pickNode = (name: string, hasChildren: boolean) => {
    pickDistrict(name);
    if (hasChildren) setOpenCity(name);
  };
  // 시군구 버튼이 칠해지는 조건: 그 시군구 자체 또는 그 아래 구를 고른 경우
  const nodeOn = (name: string) => picked && (district === name || district.startsWith(`${name} `));
  const label = effective.length > 1 ? `${first} 외 ${effective.length - 1}` : first ? `${first} ${district}` : '없음';

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
      {city?.children ? (
        // 구 목록: 시를 고른 뒤 그 시의 구를 고릅니다.
        <>
          <div className="panel-label">{first} · {city.name} · 구 (선택)</div>
          <div className="option-grid six">
            <button type="button" className={picked && district === city.name ? 'opt soft' : 'opt'} aria-pressed={picked && district === city.name} onClick={() => pickDistrict(city.name)}>전체</button>
            {city.children.map((gu) => {
              const value = `${city.name} ${gu}`;
              return <button type="button" key={gu} className={picked && district === value ? 'opt soft' : 'opt'} aria-pressed={picked && district === value} onClick={() => pickDistrict(value)}>{gu}</button>;
            })}
            <button type="button" className="opt" onClick={() => setOpenCity(null)}>← 시군구로</button>
          </div>
        </>
      ) : (
        <>
          <div className="panel-label">{first || '지역'} · 시군구 (선택)</div>
          <div className={expanded ? 'option-grid six scroll' : 'option-grid six'}>
            {/* 지역을 모두 뺀 상태에서는 시군구를 누를 수 없습니다. */}
            <button type="button" className={picked && district === '전체' ? 'opt soft' : 'opt'} aria-pressed={picked && district === '전체'} disabled={!first} onClick={() => pickDistrict('전체')}>전체</button>
            {shown.map((node) => (
              <button type="button" key={node.name} className={nodeOn(node.name) ? 'opt soft' : 'opt'} aria-pressed={nodeOn(node.name)} onClick={() => pickNode(node.name, Boolean(node.children))}>{node.name}{node.children ? ' ›' : ''}</button>
            ))}
            {hidden > 0 && !expanded && (
              <button type="button" className="opt" onClick={() => setExpanded(true)}>더보기 +{hidden}</button>
            )}
          </div>
        </>
      )}
      <PanelFooter label={label} canApply={effective.length > 0} onCancel={onCancel} onApply={() => onApply({ regions: effective, district })} />
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

  return (
    <section className="panel time-panel" aria-label="시점 선택">
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
  const [target, setTarget] = useState(filters.target);
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
