// 캐릭터의 유일한 입구입니다. 캐릭터 담당자의 3D 모션(public/character 의 HTML)을 React 로 옮겨 그립니다.
// <Character motion size /> 사용법만 유지해 주세요.
// wave 는 손 흔들며 인사, 나머지 모션은 모두 노트북 타이핑입니다.
import { SlothTyping } from './SlothTyping';
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
  return <SlothTyping className={className} {...SIZES[size]} />;
}
