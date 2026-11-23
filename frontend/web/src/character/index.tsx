// 캐릭터의 유일한 입구입니다. 지금은 Figma 이미지를 쓰고,
// 캐릭터 담당자가 이 파일 내부를 R3F 로 교체합니다. <Character motion size /> 사용법만 유지해 주세요.
import sloth from '../assets/figma/sloth.png';

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
  return (
    <img
      className={className}
      src={sloth}
      alt="노트북을 든 나무늘보 캐릭터"
      data-motion={motion}
      width={SIZES[size].width}
      height={SIZES[size].height}
      draggable={false}
    />
  );
}
