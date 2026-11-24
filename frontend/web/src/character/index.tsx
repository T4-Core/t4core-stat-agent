// 캐릭터의 유일한 입구입니다. 캐릭터 담당자의 3D HTML(public/character)을 표시합니다.
// <Character motion size /> 사용법만 유지해 주세요.
// wave(손 흔들며 인사)만 React 로 직접 그리고, 나머지 모션은 iframe 으로 띄웁니다.
import { SlothFrame } from './SlothFrame';
import { SlothWave } from './SlothWave';

export type CharacterMotion = 'idle' | 'wave' | 'thinking' | 'success' | 'asking' | 'error';
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
  return <SlothFrame className={className} motion={motion} {...SIZES[size]} />;
}
