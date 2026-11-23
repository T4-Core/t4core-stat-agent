// 3. 사용자 표 판정: 비슷한 통계표 중 하나를 고르거나 둘 다 비교합니다.
import { useEffect, useMemo, useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { toChoices } from '../api/adapters';
import { USE_MOCK } from '../api/client';
import cardCheck from '../assets/figma/card-check.svg';
import radio from '../assets/figma/radio.svg';
import { Character } from '../character';
import { Frame, QueryPill, TagChip } from '../components/Layout';
import { STAT_TABLES } from '../data/examples';
import type { ChoiceCard } from '../data/types';
import { compareTables, continueRun, usePayload } from '../store/agent';
import { completeRun, removeRun, routeForRun, useRun } from '../store/history';

const EXAMPLE_CARDS: ChoiceCard[][] = [STAT_TABLES.map((table) => ({
  token: 'example',
  optionId: table.id,
  badge: table.badge,
  name: table.name,
  org: table.org,
  rows: [['기준', table.basis], ['수록기간', table.period], ['지역', table.region]],
  value: table.value,
  valueLabel: '2020년 값 미리보기',
  unit: '만 가구',
  hint: table.hint,
  url: '',
}))];

export function SelectPage() {
  const { id } = useParams();
  const run = useRun(id);
  const navigate = useNavigate();
  const { payload, loading } = usePayload(id);
  const response = payload?.responses[0];
  const groups = useMemo(() => (USE_MOCK ? EXAMPLE_CARDS : response ? toChoices(response) : []), [response]);
  const [unit, setUnit] = useState(0);
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState(0);
  const [confirming, setConfirming] = useState(false);
  const cards = groups[unit] ?? [];

  useEffect(() => {
    if (run && run.status !== 'needs_selection' && !USE_MOCK) navigate(routeForRun(run), { replace: true });
  }, [navigate, run]);

  if (!run) return <Navigate to="/" replace />;
  if (loading) return <Frame variant="select"><span /></Frame>;
  if (!USE_MOCK && cards.length === 0) return <Navigate to="/history" replace />;

  const choose = (card: ChoiceCard) => {
    if (USE_MOCK) {
      completeRun(run.id, card.optionId as 'A' | 'B');
      navigate(`/result/${run.id}`, { replace: true });
      return;
    }
    const nextPicks = { ...picks, [card.token]: card.optionId };
    if (unit < groups.length - 1) {
      setPicks(nextPicks);
      setUnit(unit + 1);
      setSelected(0);
      return;
    }
    continueRun(run.id, response!, { view_selections: Object.entries(nextPicks).map(([selection_token, option_id]) => ({ selection_token, option_id })) });
    navigate(`/generating/${run.id}`, { replace: true });
  };

  const compare = () => {
    if (USE_MOCK) {
      completeRun(run.id, 'both');
      navigate(`/result/${run.id}`, { replace: true });
      return;
    }
    const pair = cards.slice(0, 2).map((card) => ({ selection: { selection_token: card.token, option_id: card.optionId }, label: card.name }));
    compareTables(run.id, response!, pair);
    navigate(`/generating/${run.id}`, { replace: true });
  };

  const rewrite = () => {
    navigate('/', { replace: true });
    removeRun(run.id);
  };

  const canCompare = groups.length === 1 && cards.length >= 2;

  return (
    <Frame variant="select">
      <QueryPill className="select-pill" question={run.question} />
      <Character className="select-sloth" size="S" motion="asking" />
      <div className="select-heading">
        <h1>비슷한 통계표가 {cards.length}개 있어요. 어떤 걸로 볼까요?{groups.length > 1 ? ` (${unit + 1}/${groups.length})` : ''}</h1>
        <p>{USE_MOCK ? "같은 '1인 가구'라도 조사 방식이 달라 숫자가 조금 달라요." : '같은 항목이라도 통계표마다 조사 방식이 달라 숫자가 다를 수 있어요.'}</p>
      </div>
      <div className={cards.length > 2 ? 'stat-cards many' : 'stat-cards'}>
        {cards.map((card, index) => {
          const isSelected = selected === index;
          return (
            <article className={isSelected ? 'stat-card selected' : 'stat-card'} key={card.optionId} onClick={() => setSelected(index)}>
              <div className="stat-top">
                <TagChip label={card.badge} size="M" />
                <button type="button" className="stat-radio" aria-label={`${card.badge} 선택`} aria-pressed={isSelected} onClick={() => setSelected(index)}>
                  {isSelected ? <span className="radio-on"><img src={cardCheck} alt="" width={14} height={14} /></span> : <img src={radio} alt="" width={24} height={24} />}
                </button>
              </div>
              <h2 title={card.name}>{card.name}</h2>
              <p className="stat-org">{card.org}</p>
              <dl className="stat-info">{card.rows.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
              <div className="stat-preview">
                <small>{card.valueLabel}</small>
                <p><b>{card.value}</b><span>{card.unit}</span></p>
              </div>
              {card.hint && <p className="stat-hint">{card.hint}</p>}
              <button type="button" className={isSelected ? 'stat-button primary' : 'stat-button'} onClick={(event) => { event.stopPropagation(); choose(card); }}>이 통계표로 보기</button>
            </article>
          );
        })}
      </div>
      <div className="select-actions">
        <span>잘 모르겠어요</span>
        {canCompare && <button type="button" onClick={() => (USE_MOCK ? compare() : setConfirming(true))}>둘 다 비교해서 보기</button>}
        <button type="button" onClick={rewrite}>질문 다시 쓰기</button>
      </div>

      {confirming && (
        <div className="confirm-backdrop">
          <section className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="compare-title">
            <h2 id="compare-title">두 통계표로 각각 답변을 만들까요?</h2>
            <p>답변을 2번 생성해서 HCX를 약 4~8회 호출합니다. 시간이 더 걸리고 비용도 더 듭니다.</p>
            <div>
              <button type="button" onClick={() => setConfirming(false)}>취소</button>
              <button type="button" className="primary" onClick={compare}>비교하기</button>
            </div>
          </section>
        </div>
      )}
    </Frame>
  );
}
