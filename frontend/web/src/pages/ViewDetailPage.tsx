// 4-1. 사용한 통계표 자세히 보기
import { Link, Navigate, useParams } from 'react-router-dom';
import back from '../assets/figma/back.svg';
import checkDark from '../assets/figma/check-dark.svg';
import download from '../assets/figma/download.svg';
import external from '../assets/figma/external.svg';
import layers from '../assets/figma/layers.svg';
import miniBars from '../assets/figma/mini-bars.svg';
import miniLine from '../assets/figma/mini-line.svg';
import ok from '../assets/figma/ok.svg';
import tableBox from '../assets/figma/table-box.svg';
import { downloadText } from '../components/download';
import { USE_MOCK } from '../api/client';
import { Frame, QueryPill } from '../components/Layout';
import { LiveViewDetail } from './LiveViewDetail';
import { RATIO_ROWS, VIEW_ROWS } from '../data/examples';
import { useRun } from '../store/history';

const META = [['작성기관', '통계청'], ['조사명', '인구총조사'], ['표 이름', '가구원수별 가구'], ['주기', '연간'], ['표 전체 기간', '2000 ~ 2023년'], ['최종 갱신', '2024.07']];

export function ViewDetailPage() {
  return USE_MOCK ? <ExampleViewDetail /> : <LiveViewDetail />;
}

function ExampleViewDetail() {
  const { id, viewNo } = useParams();
  const run = useRun(id);
  if (!run) return <Navigate to="/" replace />;

  const second = viewNo === '2';
  const conditions = [
    ['지역', '질문: 전국', '전국'],
    ['시점', '질문: 2015~2020', '2015~2020 (6개 연도 모두)'],
    ['대상', '질문: 1인 가구', second ? '계 · 1인 가구로 비율 계산' : '가구원수별: 1인'],
  ];
  const chips = second
    ? ['비율 계산', '연간', '2015 ~ 2020년', '전국', '단위: 가구', '12행']
    : ['추세', '연간', '2015 ~ 2020년', '전국', '단위: 가구', '6행'];
  const csv = second
    ? ['시점,전체,1인,1인 비율', ...RATIO_ROWS.map((row) => row.map((cell) => `"${cell}"`).join(','))].join('\n')
    : ['시점,행정구역별,가구원수별,항목,값', ...VIEW_ROWS.map(([year, value]) => `${year},전국,1인,일반가구,"${value}"`)].join('\n');

  return (
    <Frame variant="detail">
      <Link className="back-button" to={`/result/${run.id}`}><img src={back} alt="" width={16} height={16} />결과로 돌아가기</Link>
      <QueryPill className="detail-pill" question={run.question} tags={run.tags.slice(0, 3)} />
      <button type="button" className="csv-button" onClick={() => downloadText(`kosis-view-${second ? 2 : 1}.csv`, `﻿${csv}`)}><img src={download} alt="" width={16} height={16} />CSV 내려받기</button>
      <a className="kosis-button" href="https://kosis.kr" target="_blank" rel="noreferrer">KOSIS 원본 열기<img src={external} alt="" width={15} height={15} /></a>

      <aside className="view-side">
        <header><img src={layers} alt="" width={34} height={34} /><h2>사용한 View</h2><span className="count-chip">2개</span></header>
        <p className="view-side-sub">차트 하나에 View 하나씩 썼어요</p>
        <Link className={second ? 'view-item' : 'view-item on'} to={`/result/${run.id}/tables/1`}>
          <span className="view-no">1</span>
          <span><b>1인 가구 수</b><small>막대 그래프 · 추세</small></span>
          <img src={miniBars} alt="" width={18} height={18} />
        </Link>
        <Link className={second ? 'view-item on' : 'view-item'} to={`/result/${run.id}/tables/2`}>
          <span className="view-no">2</span>
          <span><b>1인 가구 비율</b><small>꺾은선 그래프 · 비율 계산</small></span>
          <img src={miniLine} alt="" width={18} height={18} />
        </Link>
        <h3>질문 조건과 맞춰보기</h3>
        {conditions.map(([key, asked, used]) => (
          <div className="condition" key={key}>
            <span>{key}</span>
            <p><small>{asked}</small><b>{used}</b></p>
            <img src={ok} alt="충족" width={18} height={18} />
          </div>
        ))}
        <div className="condition-ok"><img src={checkDark} alt="" width={16} height={16} />조건 3개를 모두 맞췄어요</div>
      </aside>

      <section className="view-main">
        <h1><span className="view-title-no">{second ? 2 : 1}</span>{second ? '인구총조사 · 가구원수별 가구 (전체 · 1인)' : '인구총조사 · 가구원수별 가구 (1인 가구)'}</h1>
        <div className="view-chips">{chips.map((chip, index) => <span key={chip} className={index === 0 ? 'on' : ''}>{chip}</span>)}</div>
        <div className="view-columns">
          <div className="view-table-wrap">
            {second ? (
              <table className="view-table ratio">
                <thead><tr><th scope="col">시점</th><th scope="col">가구원수별</th><th scope="col" className="right">값</th><th scope="col" className="right">1인 비율</th></tr></thead>
                <tbody>
                  {RATIO_ROWS.flatMap(([year, total, single, rate]) => [
                    <tr key={`${year}-t`}><td>{year}</td><td>계(전체)</td><td className="right">{total}</td><td /></tr>,
                    <tr key={`${year}-s`} className="hl"><td>{year}</td><td>1인</td><td className="right">{single}</td><td className="right">{rate}</td></tr>,
                  ])}
                </tbody>
              </table>
            ) : (
              <table className="view-table">
                <thead><tr><th scope="col">시점</th><th scope="col">행정구역별</th><th scope="col">가구원수별</th><th scope="col">항목</th><th scope="col" className="right">값</th></tr></thead>
                <tbody>
                  {VIEW_ROWS.map(([year, value], index) => (
                    <tr key={year} className={index === 0 || index === VIEW_ROWS.length - 1 ? 'hl' : ''}><td>{year}</td><td>전국</td><td>1인</td><td>일반가구</td><td className="right">{value}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <aside className="view-meta">
            <h2><img src={tableBox} alt="" width={34} height={34} />원본 통계표</h2>
            <dl>{META.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
          </aside>
        </div>
        <footer className="view-foot">
          <span><i />답변·차트에 직접 쓴 행</span>
          <span>{second ? '1인 비율 = 1인 가구 ÷ 전체 가구 × 100' : '답변에서는 만 가구로 바꿔 표시 (5,203,440 → 520.3만)'}</span>
        </footer>
      </section>
    </Frame>
  );
}
