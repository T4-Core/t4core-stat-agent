// 모듈별 에러 가로 막대그래프. 색은 모듈마다 고정되어 필터를 바꿔도 달라지지 않습니다.
import type { ModuleStat } from '../adapters/report';
import type { ModuleKey } from '../adapters/issues';
import { MODULE_COLORS } from '../adapters/moduleColors';

type Props = { modules: ModuleStat[]; selected: ModuleKey | null; backendFailures: number; onSelect: (key: ModuleKey) => void };

export function ModuleBars({ modules, selected, backendFailures, onSelect }: Props) {
  const max = Math.max(1, ...modules.map((item) => item.total));
  return (
    <section className="adm-chart" aria-label="모듈별 에러 통계(QA)">
      <header>
        <h2>모듈별 에러 통계(QA)</h2>
        {backendFailures > 0 && <span>모듈을 알 수 없는 백엔드 실패 {backendFailures}건 별도</span>}
      </header>
      <div className="adm-bars">
        {modules.map((item) => {
          const detail = `${item.label}: 전체 ${item.total.toLocaleString()}건, 오류 ${item.errors.toLocaleString()}, 경고 ${item.warnings.toLocaleString()}, 해결 ${item.resolved.toLocaleString()}`;
          return (
            <button key={item.key} type="button" className={selected === item.key ? 'is-on' : ''} aria-pressed={selected === item.key} aria-label={detail} onClick={() => onSelect(item.key)}>
              <span className="adm-bar-label">{item.label}</span>
              <span className="adm-bar-track">
                {item.total > 0 && <i style={{ width: `max(4px, ${(item.total / max) * 100}%)`, background: MODULE_COLORS[item.key] }} />}
              </span>
              <b>{item.total.toLocaleString()}건</b>
              <span className="adm-bar-tip" role="tooltip">오류 {item.errors.toLocaleString()} · 경고 {item.warnings.toLocaleString()} · 해결 {item.resolved.toLocaleString()}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
