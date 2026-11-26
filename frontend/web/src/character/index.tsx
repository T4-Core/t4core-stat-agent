// 캐릭터의 유일한 입구입니다. 캐릭터 담당자의 3D 모션(public/character 의 HTML)을 React 로 옮겨 그립니다.
// <Character motion size /> 사용법만 유지해 주세요.
// - wave: 손 흔들며 인사 (3D)
// - judging(사용자 표 판정 화면)·asking(되묻기 화면): 움직이지 않는 이미지 (시안 그대로)
// - 나머지: 노트북 타이핑 (3D)
import slothImage from '../assets/figma/sloth.png';
import { SlothTyping } from './SlothTyping';
import { SlothWave } from './SlothWave';

export type CharacterMotion = 'idle' | 'wave' | 'thinking' | 'judging' | 'success' | 'asking' | 'error';
export type CharacterSize = 'S' | 'M' | 'L';

const SIZES: Record<CharacterSize, { width: number; height: number }> = {
  S: { width: 127, height: 141 },
  M: { width: 224, height: 241 },
  L: { width: 331, height: 367 },
};

type Props = {
  motion?: CharacterMotion;
  size?: CharacterSize;
  className?: string;
};

export function Character({ motion = 'idle', size = 'L', className }: Props) {
  if (motion === 'wave') return <SlothWave className={className} {...SIZES[size]} />;
  if (motion === 'judging' || motion === 'asking') {
    // 상자 안에 비율을 유지한 채 맞춰 넣습니다.
    return <img src={slothImage} className={className} {...SIZES[size]} style={{ objectFit: 'contain' }} alt="" aria-hidden="true" />;
  }
  return <SlothTyping className={className} {...SIZES[size]} />;
}
