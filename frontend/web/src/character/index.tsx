// 캐릭터의 유일한 입구입니다. 캐릭터 담당자의 3D HTML(public/character)을 표시합니다.
// <Character motion size /> 사용법만 유지해 주세요.
import { SlothFrame } from './SlothFrame';

export type CharacterMotion = 'idle' | 'thinking' | 'success' | 'asking' | 'error';
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
  return <SlothFrame className={className} motion={motion} {...SIZES[size]} />;
}
