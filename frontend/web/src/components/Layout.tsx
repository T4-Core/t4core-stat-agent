// 모든 화면의 공통 틀: 1440x900 시안을 창 크기에 맞춰 비율 유지로 표시합니다.
import { useEffect, useState, type ReactNode } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import settingsIcon from '../assets/figma/settings.svg';
import { useRuns } from '../store/history';

const STAGE_WIDTH = 1440;
const STAGE_HEIGHT = 900;

// 관리자 페이지 주소. 개발 중에는 같은 PC의 5174번 포트를 사용하고, 배포 시에는 VITE_ADMIN_URL 로 지정합니다.
const ADMIN_URL = import.meta.env.VITE_ADMIN_URL?.trim()
  || (import.meta.env.DEV ? `${window.location.protocol}//${window.location.hostname}:5174/` : '');

function AdminEntry() {
  // 답변을 기다리는 중이면 결과를 잃지 않도록 새 탭으로 엽니다.
  const waiting = useRuns().some((run) => run.status === 'pending');
  // 관리자 주소가 없으면(배포 설정 누락) 톱니바퀴 모양만 보여주고 누를 수 없게 둡니다.
  if (!ADMIN_URL) return <img className="admin-entry" src={settingsIcon} alt="" width={40} height={40} />;
  return (
    <a className="admin-entry" href={ADMIN_URL} target={waiting ? '_blank' : undefined} rel={waiting ? 'noreferrer' : undefined} aria-label="관리자 페이지로 이동" title="관리자 페이지">
      <img src={settingsIcon} alt="" width={40} height={40} />
    </a>
  );
}

function getScale() {
  return Math.min(window.innerWidth / STAGE_WIDTH, window.innerHeight / STAGE_HEIGHT);
}

export function StageLayout() {
  const [scale, setScale] = useState(getScale);
  const { pathname } = useLocation();

  useEffect(() => {
    const onResize = () => setScale(getScale());
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return (
    <div className="viewport">
      <div className="stage" style={{ transform: `translate(-50%, -50%) scale(${scale})` }}>
        <div className="page" key={pathname}>
          <Outlet />
        </div>
      </div>
    </div>
  );
}

export type FrameVariant = 'main' | 'generating' | 'select' | 'result' | 'wide' | 'detail' | 'history';

export function Frame({ variant, active = 'agent', children }: { variant: FrameVariant; active?: 'agent' | 'history'; children: ReactNode }) {
  return (
    <>
      <div className={`frame frame-${variant}`} />
      <header className="app-header">
        <Link className="logo" to="/" aria-label="T4core 처음으로">
          <span className="logo-box"><span /></span>
          <span className="logo-text">T4core</span>
        </Link>
        <nav className={`nav-tab nav-${active}`} aria-label="주요 메뉴">
          <Link to="/" aria-current={active === 'agent' ? 'page' : undefined}>Agent</Link>
          <Link to="/history" aria-current={active === 'history' ? 'page' : undefined}>History</Link>
        </nav>
        <AdminEntry />
      </header>
      {children}
    </>
  );
}

export function TagChip({ label, size = 'S' }: { label: string; size?: 'S' | 'M' }) {
  return <span className={`tag-chip tag-${size}`}>{label}</span>;
}

export function QueryPill({ question, tags, className = '' }: { question: string; tags?: string[]; className?: string }) {
  return (
    <div className={`query-pill ${className}`}>
      <span className="query-text">{question}</span>
      {tags?.map((tag) => <TagChip key={tag} label={tag} />)}
    </div>
  );
}
