// 통계표를 찾는 동안 나무늘보 머리 옆에 뜨는 "계산 중" 생각 풍선입니다.
// 생성 중 화면(GeneratingPage)의 단계(step)에 맞춰 안쪽 그림이 바뀝니다.
//   0 질문 이해하기     → 물음표 갸웃 + 점
//   1 알맞은 통계표 찾기 → 표 줄을 훑는 형광펜
//   2 데이터 불러오기    → 숫자가 촤르륵 굴러감
//   3 차트와 답변 만들기 → 막대가 쑥쑥 자람
// 움직임은 CSS 애니메이션만 쓰고, 시스템의 '동작 줄이기'가 켜져 있으면 멈춥니다.
// 장식이라 화면 읽기 프로그램에서는 숨깁니다(진행 상황은 제목 문구가 알려 줌).
import './ThinkingBubble.css';

const DIGITS = '0123456789'.split('');

function Question() {
  return (
    <div className="tb-scene tb-question">
      <b>?</b>
      <span className="tb-dots"><i /><i /><i /></span>
    </div>
  );
}

function TableScan() {
  return (
    <div className="tb-scene tb-table">
      <div className="tb-scan" />
      {[0, 1, 2, 3].map((row) => <span key={row}><i /><i /><i /></span>)}
    </div>
  );
}

function RollingDigits() {
  // 네 자리 숫자 + 쉼표. 자리마다 굴러가는 속도를 다르게 해서 계산하는 느낌을 줍니다.
  const roll = (key: string) => (
    <span className="tb-digit" key={key}><span>{DIGITS.map((d) => <span key={d}>{d}</span>)}</span></span>
  );
  return (
    <div className="tb-scene tb-digits">
      {roll('a')}
      <span className="tb-digit tb-comma">,</span>
      {roll('b')}{roll('c')}{roll('d')}
    </div>
  );
}

function GrowingBars() {
  return <div className="tb-scene tb-bars"><i /><i /><i /><i /></div>;
}

const SCENES = [Question, TableScan, RollingDigits, GrowingBars];

type Props = { step: number; className?: string };

export function ThinkingBubble({ step, className }: Props) {
  const Scene = SCENES[Math.min(Math.max(step, 0), SCENES.length - 1)];
  return (
    <div className={`thinking-bubble${className ? ` ${className}` : ''}`} aria-hidden="true">
      {/* key 로 단계가 바뀔 때마다 새로 그려서 등장 애니메이션이 다시 재생되게 합니다. */}
      <Scene key={step} />
    </div>
  );
}
