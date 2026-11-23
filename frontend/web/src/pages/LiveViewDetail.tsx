// 4-1. 사용한 통계표 상세 (실제 백엔드 응답)
import { useEffect, useMemo, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { toConditions, toResultView } from '../api/adapters';
import { judgeChat } from '../api/chat';
import type { ChatResponse, JudgeResult } from '../api/types';
import back from '../assets/figma/back.svg';
import checkDark from '../assets/figma/check-dark.svg';
import download from '../assets/figma/download.svg';
import external from '../assets/figma/external.svg';
import layers from '../assets/figma/layers.svg';
import miniBars from '../assets/figma/mini-bars.svg';
import ok from '../assets/figma/ok.svg';
import tableBox from '../assets/figma/table-box.svg';
import { downloadText } from '../components/download';
import { EvidenceTable } from '../components/EvidenceTable';
import { Frame, QueryPill } from '../components/Layout';
import { usePayload } from '../store/agent';
import { useRun } from '../store/history';

const judgeCache = new Map<string, JudgeResult>();
const judgeRequests = new Map<string, Promise<JudgeResult>>();

function requestJudge(key: string, response: ChatResponse) {
  const running = judgeRequests.get(key);
  if (running) return running;
  const request = judgeChat(response)
    .then((result) => {
      judgeCache.set(key, result);
      return result;
    })
    .finally(() => judgeRequests.delete(key));
  judgeRequests.set(key, request);
  return request;
}

export function LiveViewDetail() {
  const { id, viewNo } = useParams();
  const run = useRun(id);
  const { payload, loading } = usePayload(id);
  const view = useMemo(() => (payload ? toResultView(payload.responses, payload.labels) : null), [payload]);
  const details = view?.details ?? [];
  const current = details[Math.max(0, Number(viewNo) - 1)] ?? details[0];
  const response = current ? payload?.responses[current.responseIndex] : undefined;
  const cacheKey = `${id}:${current?.responseIndex ?? 0}`;
  const [judge, setJudge] = useState<JudgeResult | null>(judgeCache.get(cacheKey) ?? null);
  const [judgeFailed, setJudgeFailed] = useState(false);

  useEffect(() => {
    if (!response) return;
    const cached = judgeCache.get(cacheKey);
    if (cached) {
      setJudge(cached);
      return;
    }
    let cancelled = false;
    setJudge(null);
    setJudgeFailed(false);
    requestJudge(cacheKey, response)
      .then((result) => { if (!cancelled) setJudge(result); })
      .catch(() => { if (!cancelled) setJudgeFailed(true); });
    return () => { cancelled = true; };
  }, [cacheKey, response]);

  if (!run) return <Navigate to="/" replace />;
  if (loading) return <Frame variant="detail"><span /></Frame>;
  if (!current) return <Navigate to={`/result/${run.id}`} replace />;

  const conditions = judge ? toConditions(judge, current.recordId) : [];
  const allOk = conditions.length > 0 && conditions.every((item) => item.ok);
  const csv = [current.table.columns, ...current.table.rows].map((row) => row.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(',')).join('\n');

  return (
    <Frame variant="detail">
      <Link className="back-button" to={`/result/${run.id}`}><img src={back} alt="" width={16} height={16} />결과로 돌아가기</Link>
      <QueryPill className="detail-pill live-detail-pill" question={run.question} tags={run.tags.slice(0, 3)} />
      <button type="button" className="csv-button" onClick={() => downloadText(`kosis-view-${current.no}.csv`, `﻿${csv}`)}><img src={download} alt="" width={16} height={16} />CSV 내려받기</button>
      <a className="kosis-button" href={current.url || 'https://kosis.kr'} target="_blank" rel="noreferrer">KOSIS 원본 열기<img src={external} alt="" width={15} height={15} /></a>

      <aside className="view-side live-side">
        <header><img src={layers} alt="" width={34} height={34} /><h2>사용한 View</h2><span className="count-chip">{details.length}개</span></header>
        <p className="view-side-sub">답변에 사용한 통계표예요</p>
        <div className="live-view-list">
          {details.map((item) => (
            <Link key={`${item.no}-${item.recordId}`} className={item.no === current.no ? 'view-item on' : 'view-item'} to={`/result/${run.id}/tables/${item.no}`}>
              <span className="view-no">{item.no}</span>
              <span><b title={item.shortTitle}>{item.shortTitle}</b><small>{item.subtitle}</small></span>
              <img src={miniBars} alt="" width={18} height={18} />
            </Link>
          ))}
        </div>
        <h3>질문 조건과 맞춰보기</h3>
        <div className="live-conditions">
          {conditions.map((item) => (
            <div className="condition" key={item.key}>
              <span>{item.key}</span>
              <p><small>질문: {item.asked}</small><b title={item.note || item.used}>{item.used}</b></p>
              {item.ok ? <img src={ok} alt="충족" width={18} height={18} /> : <em className="condition-warn">확인</em>}
            </div>
          ))}
          {!judge && !judgeFailed && <p className="condition-state">조건을 확인하고 있어요…</p>}
          {judgeFailed && <p className="condition-state">조건 판정을 불러오지 못했어요.</p>}
        </div>
        {judge && conditions.length > 0 && (
          <div className={allOk ? 'condition-ok' : 'condition-ok partial'}>
            {allOk && <img src={checkDark} alt="" width={16} height={16} />}
            {allOk ? `조건 ${conditions.length}개를 모두 맞췄어요` : `${conditions.filter((item) => !item.ok).length}개 조건은 확인이 필요해요`}
          </div>
        )}
      </aside>

      <section className="view-main">
        <h1><span className="view-title-no">{current.no}</span><span className="live-title" title={current.title}>{current.title}</span></h1>
        <div className="view-chips">{current.chips.map((chip, index) => <span key={chip} className={index === 0 ? 'on' : ''}>{chip}</span>)}</div>
        <div className="view-columns">
          <div className="view-table-wrap"><EvidenceTable table={current.table} /></div>
          <aside className="view-meta">
            <h2><img src={tableBox} alt="" width={34} height={34} />원본 통계표</h2>
            <dl>{current.meta.map(([key, value]) => <div key={key}><dt>{key}</dt><dd title={value}>{value}</dd></div>)}</dl>
          </aside>
        </div>
        <footer className="view-foot"><span><i />답변·차트에 직접 쓴 행</span><span>{current.table.totalRows.toLocaleString('ko-KR')}행</span></footer>
      </section>
    </Frame>
  );
}
