// 왼쪽 메뉴와 로그인한 팀원 정보 (Figma Admin Sidebar)
import { useState, type MouseEvent } from 'react';
import { NavLink } from 'react-router-dom';
import chartActive from '../assets/chart-active.svg';
import chart from '../assets/chart.svg';
import historyActive from '../assets/history-active.svg';
import history from '../assets/history.svg';
import logout from '../assets/logout.svg';
import searchActive from '../assets/search-active.svg';
import search from '../assets/search.svg';
import { isRunBusy, setRunBusy } from '../runner/guard';
import { useAuth } from '../supabase/auth';
import { PasswordDialog } from './PasswordDialog';

const MENU = [
  { to: '/query-test', label: '쿼리 테스트', icon: search, activeIcon: searchActive },
  { to: '/errors', label: '모듈별 에러 통계(QA)', icon: chart, activeIcon: chartActive },
  { to: '/history', label: 'History', icon: history, activeIcon: historyActive },
];

// 사용자 화면 주소. 개발 중에는 같은 PC의 5173번 포트를 쓰고, 배포 시에는 VITE_USER_URL 로 지정합니다.
const USER_URL = import.meta.env.VITE_USER_URL?.trim()
  || (import.meta.env.DEV ? `${window.location.protocol}//${window.location.hostname}:5173/` : '');

// 쿼리 실행 중이면 진행 상황을 잃지 않도록 새 탭으로 엽니다.
function openUserPage(event: MouseEvent<HTMLAnchorElement>) {
  if (!isRunBusy()) return;
  event.preventDefault();
  window.open(USER_URL, '_blank', 'noreferrer');
}

export function AdminSidebar() {
  const { displayName, signOut } = useAuth();
  const [changing, setChanging] = useState(false);
  const leave = () => {
    if (isRunBusy() && !window.confirm('쿼리가 실행 중이거나 저장되지 않았습니다. 로그아웃하면 결과가 팀 리포트에 저장되지 않아요. 계속할까요?')) return;
    setRunBusy(false);
    void signOut();
  };

  return (
    <aside className="adm-sidebar">
      <div className="adm-brand">
        {USER_URL ? (
          <a className="adm-logo" href={USER_URL} title="사용자 메인 페이지로 이동" onClick={openUserPage}><span className="adm-logo-box"><i /></span><strong>T4core</strong></a>
        ) : (
          <div className="adm-logo"><span className="adm-logo-box"><i /></span><strong>T4core</strong></div>
        )}
        <span>관리자 콘솔</span>
      </div>
      <nav className="adm-nav" aria-label="관리자 메뉴">
        {MENU.map((item) => (
          <NavLink key={item.to} to={item.to} className={({ isActive }) => `adm-nav-item${isActive ? ' is-active' : ''}`}>
            {({ isActive }) => (
              <>
                <img src={isActive ? item.activeIcon : item.icon} alt="" width={17} height={17} />
                {item.label}
              </>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="adm-user">
        <button className="adm-user-info" type="button" onClick={() => setChanging(true)} title="비밀번호 변경">
          <span className="adm-user-initial">{displayName.slice(0, 1).toUpperCase()}</span>
          <span className="adm-user-name"><strong>{displayName}</strong><small>비밀번호 변경</small></span>
        </button>
        <button className="adm-icon-button" type="button" onClick={leave} aria-label="로그아웃" title="로그아웃">
          <img src={logout} alt="" width={16} height={16} />
        </button>
      </div>
      {changing && <PasswordDialog onClose={() => setChanging(false)} />}
    </aside>
  );
}
