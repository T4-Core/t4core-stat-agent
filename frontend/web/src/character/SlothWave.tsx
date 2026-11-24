// 손 흔들며 인사하는 나무늘보 3D (원본: public/character/sloth-wave.html)
// 공통 부분(모델·뼈대·장면·정리)은 slothRig.ts 에 있고, 여기에는 인사 동작만 있습니다.
import * as THREE from 'three';
import { useSloth, type ArmBone, type Rig, type SlothMotion } from './slothRig';

// ── 모션: 한 손 들고 흔들흔들 인사 ──────────────────────
// 한 루프(CYCLE초) = 들기 → 흔들기 → 내리기 → 잠깐 쉬기
const CYCLE = 4.6;
const RAISE_END = 0.7, WAVE_END = 3.4, LOWER_END = 4.0;
const WAVE_PERIOD = 0.8; // 손을 한 번 왔다 갔다 하는 시간(초)
const WAVE_ARM = 1; // 흔드는 팔: 1 = 캐릭터 왼팔(화면 오른쪽), -1 = 반대
const UPPER_UP = [0.65, 0.75, 0.2]; // 들었을 때 위팔: 옆 위로 들어 올림
const FORE_SWING = [0.3, 0.7]; // 아래팔 기울기(라디안): 가운데 값, 흔드는 폭
const RELAX = [0.5, -0.8, 0.35]; // 쉬는 팔: 편하게 아래로

const ease = (t: number) => t * t * (3 - 2 * t);
const clamp01 = (t: number) => Math.min(Math.max(t, 0), 1);
const qUpper = new THREE.Quaternion(), qA = new THREE.Quaternion(), qB = new THREE.Quaternion();
const qInv = new THREE.Quaternion();
const dir = new THREE.Vector3(), straight = new THREE.Vector3(), local = new THREE.Vector3();

// 아래팔이 월드 방향 target 을 가리키도록 팔꿈치 회전을 계산합니다.
function aimFore(arm: ArmBone, target: THREE.Vector3) {
  qInv.copy(arm.upper.quaternion).invert();
  local.copy(target).applyQuaternion(qInv);
  arm.fore.quaternion.setFromUnitVectors(arm.foreDir, local.normalize());
}

function pose(rig: Rig, time: number) {
  const t = time % CYCLE;
  const raise = t < RAISE_END ? ease(t / RAISE_END)
    : t < WAVE_END ? 1
      : ease(clamp01(1 - (t - WAVE_END) / (LOWER_END - WAVE_END)));
  const swing = Math.sin(time * 2 * Math.PI / WAVE_PERIOD);

  for (const arm of rig.armBones) {
    const s = arm.s;
    qA.setFromUnitVectors(arm.upperDir, dir.set(s * RELAX[0], RELAX[1], RELAX[2]).normalize());
    if (s !== WAVE_ARM) {
      // 반대 팔: 편하게 내리고 인사 박자에 맞춰 살짝 흔들림
      qB.setFromUnitVectors(arm.upperDir, dir.set(s * (RELAX[0] + 0.04 * swing * raise), RELAX[1], RELAX[2]).normalize());
      arm.upper.quaternion.copy(qB);
      arm.fore.quaternion.identity();
      continue;
    }
    // 흔드는 팔: 위팔을 옆으로 들고, 아래팔은 세워 시계추처럼 흔듭니다.
    qB.setFromUnitVectors(arm.upperDir, dir.set(s * UPPER_UP[0], UPPER_UP[1], UPPER_UP[2]).normalize());
    qUpper.slerpQuaternions(qA, qB, raise);
    arm.upper.quaternion.copy(qUpper);
    const angle = FORE_SWING[0] + FORE_SWING[1] * swing * 0.5;
    dir.set(s * Math.sin(angle), Math.cos(angle), 0.18).normalize();
    straight.copy(arm.foreDir).applyQuaternion(qUpper); // 팔꿈치를 안 굽혔을 때 방향
    aimFore(arm, straight.lerp(dir, raise).normalize());
  }

  // 고개: 손 반대쪽으로 살짝 갸웃하고 손 박자에 맞춰 까딱까딱
  const h = rig.headBone.rotation;
  h.z = WAVE_ARM * (0.08 * raise + 0.025 * swing * raise);
  h.x = 0.02 + 0.03 * Math.sin(time * 2 * Math.PI / (WAVE_PERIOD * 2)) * raise;
  h.y = 0.04 * Math.sin(time * 2 * Math.PI / 5);
  // 몸: 호흡 + 인사할 때 살짝 들썩
  const breath = Math.sin(time * 2 * Math.PI / 3.6) * 0.006;
  rig.root.scale.set(1 - breath * 0.5, 1 + breath + 0.01 * raise, 1);
}

const WAVE: SlothMotion = {
  camera: [0.1, 1.55, 4.7],
  target: [0, 0.9, 0],
  turnY: -0.15, // 흔드는 손이 카메라 쪽으로 살짝 오도록
  elbowBlend: 0.04, // 인사할 때 팔꿈치를 굽히므로 타이핑보다 넓게 섞어 주름을 줄입니다.
  speed: 0.65, // 원본의 "더 느리게"
  reducedTime: 1.0, // 동작 줄이기: 손을 든 정지 자세
  pose,
};

type Props = { width: number; height: number; className?: string };

export function SlothWave({ width, height, className }: Props) {
  const stageRef = useSloth(WAVE);
  return <div ref={stageRef} className={className} style={{ width, height }} aria-hidden="true" />;
}
