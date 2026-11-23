// 캐릭터 담당자의 HTML(public/character)을 수정 없이 iframe 으로 띄웁니다.
// HTML 의 파일명이나 아래 클래스명이 바뀌면 이 파일도 함께 맞춰 주세요.
import { useState, type SyntheticEvent } from 'react';

const SRC = `${import.meta.env.BASE_URL}character/sloth-3d-glb.html`;

// 카드·문구·버튼을 숨기고 3D 캐릭터만 보이게 합니다.
const EMBED_CSS = `
  :root, body { background: transparent; }
  body { display: block; min-height: 0; padding: 0; overflow: hidden; }
  .card { width: 100%; height: 100vh; padding: 0; border: 0; border-radius: 0;
          background: transparent; box-shadow: none; }
  .stage { height: 100%; aspect-ratio: auto; }
  .label, .hint, .controls { display: none; }
`;

type Props = {
  motion: string;
  width: number;
  height: number;
  className?: string;
};

export function SlothFrame({ motion, width, height, className }: Props) {
  const [ready, setReady] = useState(false);

  function handleLoad(event: SyntheticEvent<HTMLIFrameElement>) {
    const doc = event.currentTarget.contentDocument;
    if (!doc) return;
    const style = doc.createElement('style');
    style.textContent = EMBED_CSS;
    doc.head.appendChild(style);
    setReady(true);
  }

  return (
    <iframe
      src={SRC}
      title="나무늘보 캐릭터"
      aria-hidden="true"
      tabIndex={-1}
      className={className}
      width={width}
      height={height}
      data-motion={motion}
      onLoad={handleLoad}
      style={{ border: 0, pointerEvents: 'none', visibility: ready ? 'visible' : 'hidden' }}
    />
  );
}
