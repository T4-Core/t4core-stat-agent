// 모든 화면의 공통 틀: 1440x900 시안을 창 크기에 맞춰 비율 유지로 표시합니다.
import { useEffect, useState, type ReactNode } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';

const STAGE_WIDTH = 1440;
const STAGE_HEIGHT = 900;

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
      <header className={`app-header header-${variant}`}>
        <Link className="logo" to="/" aria-label="T4core 처음으로">
          <span className="logo-box"><span /></span>
          <span className="logo-text">T4core</span>
        </Link>
        <nav className={`nav-tab nav-${active}`} aria-label="주요 메뉴">
          <Link to="/" aria-current={active === 'agent' ? 'page' : undefined}>Agent</Link>
          <Link to="/history" aria-current={active === 'history' ? 'page' : undefined}>History</Link>
        </nav>
        <span className="header-spacer" aria-hidden="true" />
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
