// 5. History: 브라우저에 저장된 질문 기록
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import arrowWhite from '../assets/figma/arrow-right-white.svg';
import downloadButton from '../assets/figma/download-button.svg';
import barsActive from '../assets/figma/h-bars-active.svg';
import chevron from '../assets/figma/h-chevron.svg';
import search from '../assets/figma/h-search.svg';
import starChip from '../assets/figma/h-star-chip.svg';
import moreActive from '../assets/figma/more-active.svg';
import more from '../assets/figma/more.svg';
import starOff from '../assets/figma/star-off.svg';
import starOn from '../assets/figma/star-on.svg';
import thumbBars from '../assets/figma/thumb-bars.svg';
import thumbLine from '../assets/figma/thumb-line.svg';
import { Character } from '../character';
import { downloadText } from '../components/download';
import { Frame, TagChip } from '../components/Layout';
import { StatChart } from '../components/StatChart';
import { toCsv } from '../data/examples';
import type { RunRecord } from '../data/types';
import { useRunView } from '../store/agent';
import { getRunGroup, getRunTime, removeRun, toggleFavorite, useRuns } from '../store/history';

const GROUPS = ['오늘', '어제', '지난 7일', '이전'] as const;
type FilterKey = 'region' | 'time' | 'target';
const FILTER_LABEL: Record<FilterKey, string> = { region: '지역', time: '시점', target: '대상' };
const TAG_INDEX: Record<FilterKey, number> = { region: 0, time: 1, target: 2 };

export function HistoryPage() {
  const navigate = useNavigate();
  const runs = useRuns();
  const done = useMemo(() => runs.filter((run) => run.status === 'done'), [runs]);
  const [keyword, setKeyword] = useState('');
  const [favoriteOnly, setFavoriteOnly] = useState(false);
  const [filters, setFilters] = useState<Partial<Record<FilterKey, string>>>({});
  const [openFilter, setOpenFilter] = useState<FilterKey | null>(null);
  const [menuId, setMenuId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const visible = done.filter((run) => {
    const text = `${run.question} ${run.tags.join(' ')}`;
    if (keyword.trim() && !text.includes(keyword.trim())) return false;
    if (favoriteOnly && !run.favorite) return false;
    return (Object.keys(filters) as FilterKey[]).every((key) => !filters[key] || run.tags[TAG_INDEX[key]] === filters[key]);
  });
  const selected = visible.find((run) => run.id === selectedId) ?? visible[0];
  const noFilter = !favoriteOnly && Object.keys(filters).length === 0;
  const { view: preview } = useRunView(selected);

  if (done.length === 0) {
    return (
      <Frame variant="history" active="history">
        <h1 className="history-title">히스토리</h1>
        <p className="history-sub">지금까지 물어본 질문 0개</p>
        <Character className="empty-sloth" size="L" motion="idle" />
        <h2 className="empty-title">아직 물어본 질문이 없어요</h2>
        <p className="empty-sub">첫 질문을 하면 여기에 차곡차곡 쌓여요.</p>
        <Link className="empty-button" to="/">첫 질문 하러 가기<img src={arrowWhite} alt="" width={16} height={16} /></Link>
      </Frame>
    );
  }

  const options = (key: FilterKey) => [...new Set(done.map((run) => run.tags[TAG_INDEX[key]]).filter(Boolean))];
  const pickFilter = (key: FilterKey, value?: string) => {
    setFilters((current) => {
      const next = { ...current };
      if (value) next[key] = value;
      else delete next[key];
      return next;
    });
    setOpenFilter(null);
  };
  const reset = () => {
    setFavoriteOnly(false);
    setFilters({});
    setOpenFilter(null);
  };

  const renderRow = (run: RunRecord) => {
    const isSelected = run.id === selected?.id;
    return (
      <div key={run.id} className={isSelected ? 'history-row selected' : 'history-row'} onClick={() => setSelectedId(run.id)}>
        <span className="history-thumb">{isSelected && run.thumb === 'bars' ? <img src={barsActive} alt="" width={26} height={22} /> : <img src={run.thumb === 'bars' ? thumbBars : thumbLine} alt="" width={58} height={44} />}</span>
        <span className="history-text">
          <button type="button" onClick={(event) => { event.stopPropagation(); navigate(`/result/${run.id}`); }}>{run.question}</button>
          <span className="history-tags">{run.tags.map((tag) => <TagChip key={tag} label={tag} />)}</span>
        </span>
        <span className="history-time">{getRunTime(run)}</span>
        <button type="button" className="history-icon" aria-label={run.favorite ? '즐겨찾기 해제' : '즐겨찾기'} aria-pressed={run.favorite} onClick={(event) => { event.stopPropagation(); toggleFavorite(run.id); }}>
          <img src={run.favorite ? starOn : starOff} alt="" width={17} height={17} />
        </button>
        <span className="history-menu-wrap">
          <button type="button" className="history-icon" aria-label="더보기" aria-expanded={menuId === run.id} onClick={(event) => { event.stopPropagation(); setMenuId(menuId === run.id ? null : run.id); }}>
            <img src={isSelected ? moreActive : more} alt="" width={17} height={17} />
          </button>
          {menuId === run.id && (
            <span className="history-menu">
              <button type="button" onClick={(event) => { event.stopPropagation(); setMenuId(null); removeRun(run.id); }}>삭제</button>
            </span>
          )}
        </span>
      </div>
    );
  };


  return (
    <Frame variant="history" active="history">
      <h1 className="history-title">히스토리</h1>
      <p className="history-sub">지금까지 물어본 질문 {done.length}개</p>
      <label className="history-search">
        <img src={search} alt="" width={16} height={16} />
        <input value={keyword} placeholder="질문·지역·대상으로 검색" aria-label="히스토리 검색" onChange={(event) => setKeyword(event.target.value)} />
      </label>
      <div className="history-filters">
        <button type="button" className={noFilter ? 'chip on' : 'chip'} aria-pressed={noFilter} onClick={reset}>전체</button>
        <button type="button" className={favoriteOnly ? 'chip selected' : 'chip'} aria-pressed={favoriteOnly} onClick={() => setFavoriteOnly(!favoriteOnly)}><img src={starChip} alt="" width={13} height={13} />즐겨찾기</button>
        {(Object.keys(FILTER_LABEL) as FilterKey[]).map((key) => (
          <span className="filter-wrap" key={key}>
            <button type="button" className={filters[key] ? 'chip selected' : 'chip'} aria-expanded={openFilter === key} onClick={() => setOpenFilter(openFilter === key ? null : key)}>
              {filters[key] ?? FILTER_LABEL[key]}<img src={chevron} alt="" width={13} height={13} />
            </button>
            {openFilter === key && (
              <span className="filter-menu">
                <button type="button" onClick={() => pickFilter(key)}>전체</button>
                {options(key).map((value) => <button type="button" key={value} onClick={() => pickFilter(key, value)}>{value}</button>)}
              </span>
            )}
          </span>
        ))}
      </div>

      <div className="history-list">
        {GROUPS.map((group) => {
          const items = visible.filter((run) => getRunGroup(run) === group);
          if (items.length === 0) return null;
          return <section key={group}><h2>{group}</h2>{items.map(renderRow)}</section>;
        })}
        {visible.length === 0 && <p className="history-none">조건에 맞는 질문이 없어요.</p>}
      </div>

      {selected && preview && (
        <aside className="history-preview">
          <div className="preview-top"><span>미리보기</span><span>{getRunGroup(selected)} {getRunTime(selected)}</span></div>
          <h2>{selected.question}</h2>
          <div className="preview-chips">{selected.tags.map((tag) => <span key={tag}>{tag.replace('·', ' · ')}</span>)}</div>
          <div className="preview-chart">{preview.charts[0] ? <StatChart chart={preview.charts[0]} width={390} height={250} /> : <p className="preview-empty">차트 없이 표로 정리한 답변이에요.</p>}</div>
          <p className="preview-answer">{preview.previewAnswer.map((part, index) => <span key={index} className={part.tone}>{part.text}</span>)}</p>
          <p className="preview-source">{preview.source}</p>
          <div className="preview-actions">
            <Link className="primary" to={`/result/${selected.id}`}>결과 다시 열기</Link>
            <Link to={`/result/${selected.id}?focus=1`}>이어서 질문</Link>
            <button type="button" aria-label="CSV 내려받기" onClick={() => downloadText('kosis-history.csv', toCsv(preview))}><img src={downloadButton} alt="" width={46} height={46} /></button>
          </div>
        </aside>
      )}
    </Frame>
  );
}
