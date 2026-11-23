// 1. Main: 질문 입력, 지역·시점·대상 선택, 최근 질문, 추천 통계
import { useEffect, useState, type CSSProperties, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { checkHealth, USE_MOCK } from '../api/client';
import bars from '../assets/figma/bars.svg';
import bubbleMark from '../assets/figma/bubble-mark.svg';
import bubble from '../assets/figma/bubble.svg';
import calendarActive from '../assets/figma/calendar-active.svg';
import calendar from '../assets/figma/calendar.svg';
import chevron from '../assets/figma/chevron-down.svg';
import clock from '../assets/figma/clock.svg';
import pinActive from '../assets/figma/pin-active.svg';
import pin from '../assets/figma/pin.svg';
import send from '../assets/figma/send-button.svg';
import userActive from '../assets/figma/user-active.svg';
import user from '../assets/figma/user.svg';
import { Character } from '../character';
import { RegionPanel, TargetPanel, TimePanel } from '../components/FilterPanels';
import { TagChip, Frame } from '../components/Layout';
import { composeQuestion, EMPTY_FILTERS, formatRegion, formatTime, mergeConditions, tagsFromFilters } from '../data/examples';
import type { Filters } from '../data/types';
import { createRun, useRuns } from '../store/history';

type PanelName = 'region' | 'time' | 'target' | null;

const RECOMMENDS = [
  { title: '1인 가구 수', desc: '인구총조사 · 가구원수별 가구', chartCount: 2 },
  { title: '1인 가구 비율', desc: '인구총조사 · 전체 일반가구 대비', chartCount: 3 },
  { title: '연령대별 1인 가구', desc: '인구총조사 · 성·연령별 1인 가구', chartCount: 4 },
];

type ChipProps = {
  label: string;
  value: string;
  icon: string;
  activeIcon: string;
  onOpen: () => void;
  onClear: () => void;
};

function FilterChip({ label, value, icon, activeIcon, onOpen, onClear }: ChipProps) {
  if (value) {
    return (
      <span className="filter-chip active">
        <button type="button" className="chip-main" onClick={onOpen}>
          <img src={activeIcon} alt="" width={16} height={16} />
          <span>{value}</span>
        </button>
        <button type="button" className="chip-clear" aria-label={`${label} 선택 해제`} onClick={onClear}>×</button>
      </span>
    );
  }
  return (
    <button type="button" className="filter-chip" onClick={onOpen}>
      <img src={icon} alt="" width={16} height={16} />
      <b>{label}</b>
      <span>선택</span>
      <img src={chevron} alt="" width={13} height={13.5} />
    </button>
  );
}

export function MainPage() {
  const navigate = useNavigate();
  const runs = useRuns();
  const [question, setQuestion] = useState('');
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [panel, setPanel] = useState<PanelName>(null);
  const [backendDown, setBackendDown] = useState(false);

  useEffect(() => {
    if (USE_MOCK) return;
    let cancelled = false;
    void checkHealth().then((ok) => { if (!cancelled) setBackendDown(!ok); });
    return () => { cancelled = true; };
  }, []);

  const regionText = formatRegion(filters);
  const timeText = formatTime(filters);
  const allSelected = Boolean(regionText && timeText && filters.target);
  const showRecommend = allSelected && panel === null;
  const doneRuns = runs.filter((run) => run.status === 'done');
  const recent = [
    ...doneRuns.filter((run) => run.createdAt),
    ...['seed-2', 'seed-4'].flatMap((seedId) => doneRuns.filter((run) => run.id === seedId)),
  ].slice(0, 2);
  const layout = showRecommend ? 'layout-recommend' : '';

  const start = (text: string, chartCount = 2) => {
    const finalQuestion = text.trim() || composeQuestion(filters);
    if (!finalQuestion) return;
    const run = createRun({
      question: finalQuestion,
      requestQuestion: mergeConditions(finalQuestion, filters),
      tags: tagsFromFilters(filters),
      chartCount,
      needsSelection: finalQuestion.includes('1인 가구'),
    });
    navigate(`/generating/${run.id}`);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    start(question);
  };

  const applyRegion = (patch: Partial<Filters>) => {
    setFilters((current) => ({ ...current, ...patch }));
    setPanel(filters.years.length > 0 ? null : 'time');
  };
  const applyTime = (patch: Partial<Filters>) => {
    setFilters((current) => ({ ...current, ...patch }));
    setPanel(filters.target ? null : 'target');
  };
  const applyTarget = (patch: Partial<Filters>) => {
    setFilters((current) => ({ ...current, ...patch }));
    setPanel(null);
  };

  const cancel = () => setPanel(null);
  const toggle = (name: Exclude<PanelName, null>) => setPanel((current) => (current === name ? null : name));
  const timeTag = timeText.replace('년', '');
  const recommends = USE_MOCK ? RECOMMENDS : [
    { title: `${filters.target} 수`, desc: '이 조건으로 바로 질문하기', chartCount: 2 },
    { title: `${filters.target} 비율`, desc: '이 조건으로 바로 질문하기', chartCount: 2 },
    { title: `연령대별 ${filters.target}`, desc: '이 조건으로 바로 질문하기', chartCount: 2 },
  ];

  return (
    <Frame variant="main">
      <Character className="main-sloth" size="M" motion="idle" />
      <div className="main-bubble">
        <img className="bubble-shape" src={bubble} alt="" />
        <img className="bubble-tail" src={bubbleMark} alt="" />
        <p>안녕하세요!<br />무엇을 도와드릴까요?</p>
      </div>

      {backendDown && <p className="backend-alert" role="alert">백엔드에 연결하지 못했어요. FastAPI 서버가 켜져 있는지 확인해 주세요.</p>}
      <div className={`main-content ${layout}`} style={{ '--recent-display': showRecommend ? 'none' : 'block' } as CSSProperties}>
        <h1 className="main-title">어떤 통계가 궁금하세요?</h1>
        <p className="main-sub">질문을 직접 적거나, 아래에서 지역·시점·대상을 골라 찾아보세요.</p>

        <form className="composer" onSubmit={submit}>
          <div className="composer-input">
            <input value={question} placeholder="무엇이든 물어보세요 예) 2020년 서울 1인 가구는 몇 가구야?" aria-label="통계 질문" onChange={(event) => setQuestion(event.target.value)} />
            <button type="submit" aria-label="질문 보내기"><img src={send} alt="" width={44} height={44} /></button>
          </div>
          <div className="composer-filters">
            <span className="filter-label">조건으로 찾기</span>
            <FilterChip label="지역" value={regionText} icon={pin} activeIcon={pinActive} onOpen={() => toggle('region')} onClear={() => setFilters((c) => ({ ...c, regions: [], district: '전체' }))} />
            <FilterChip label="시점" value={timeText} icon={calendar} activeIcon={calendarActive} onOpen={() => toggle('time')} onClear={() => setFilters((c) => ({ ...c, years: [] }))} />
            <FilterChip label="대상" value={filters.target} icon={user} activeIcon={userActive} onOpen={() => toggle('target')} onClear={() => setFilters((c) => ({ ...c, target: '' }))} />
            <span className="filter-spacer" />
            {allSelected && (
              <button type="button" className="filter-reset" onClick={() => { setFilters(EMPTY_FILTERS); setPanel(null); }}>초기화</button>
            )}
          </div>
        </form>

        {showRecommend ? (
          <section className="recommend" aria-label="추천 통계">
            <div className="recommend-head">
              <span>이 조건으로 볼 수 있는 통계 3개</span>
              <span className="medium">하나를 고르거나, 위에 질문을 더 적어도 돼요</span>
            </div>
            {recommends.map((item, index) => (
              <button type="button" key={item.title} className={index === 0 ? 'recommend-row first' : 'recommend-row'} onClick={() => start(composeQuestion(filters, item.title), item.chartCount)}>
                <span className="icon-box"><img src={bars} alt="" width={18} height={18} /></span>
                <span className="recommend-text"><b>{item.title}</b><small>{item.desc}</small></span>
                <TagChip label={regionText} size="M" />
                <TagChip label={timeTag} size="M" />
                <span className="row-arrow large">›</span>
              </button>
            ))}
          </section>
        ) : (
          <section className="recent" aria-label="최근 질문">
            <div className="recent-head">
              <span>최근에 물어본 질문</span>
              <Link to="/history">히스토리 전체 보기 ›</Link>
            </div>
            {recent.map((run) => (
              <Link className="recent-row" key={run.id} to={`/result/${run.id}`}>
                <img src={clock} alt="" width={18} height={18} />
                <span>{run.question}</span>
                <span className="row-arrow">›</span>
              </Link>
            ))}
          </section>
        )}
      </div>

      {panel === 'region' && <RegionPanel filters={filters} onCancel={cancel} onApply={applyRegion} />}
      {panel === 'time' && <TimePanel filters={filters} onCancel={cancel} onApply={applyTime} />}
      {panel === 'target' && <TargetPanel filters={filters} onCancel={cancel} onApply={applyTarget} />}
    </Frame>
  );
}
