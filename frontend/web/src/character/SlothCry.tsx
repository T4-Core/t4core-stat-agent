// 흐느끼며 볼의 눈물을 훔치는 나무늘보 3D (원본: public/character/sloth-cry.html)
// 오류·범위 밖 안내 화면에서 씁니다. 우는 표정 모델(sloth-sad-optimized.glb)을 따로 불러옵니다.
// 공통 부분(모델·뼈대·장면·정리)은 slothRig.ts 에 있고, 여기에는 우는 동작만 있습니다.
import * as THREE from 'three';
import { useSloth, type ArmBone, type Rig, type SlothMotion } from './slothRig';

// ── 모션: 흐느끼기 → 오른손으로 볼 닦기 → 흐느끼며 고개 젓기 → 왼손으로 볼 닦기 ──
// 팔이 짧아 손이 눈까지 닿지 않으므로, 볼 옆으로 손을 올리고 고개를 그쪽으로 기울여 닦는 느낌을 냅니다.
const CYCLE = 6.4;
const WIPES: [side: number, start: number, end: number][] = [ // 팔(1 = 화면 오른쪽, -1 = 왼쪽), 시작·끝(초)
  [1, 1.4, 3.0],
  [-1, 4.6, 6.2],
];
const WIPE_IN = 0.4, WIPE_OUT = 0.4; // 손을 올리고 내리는 시간(초)
const SOB_PERIOD = 1.5; // "흑, 흑" 한 묶음 간격(초)
const CHEEK = [0.46, -0.02, 0.36]; // 손이 닿을 볼 옆 위치(모델 좌표, x 부호는 팔마다 자동)
const RELAX = [0.7, -0.62, 0.36]; // 쉬는 팔: 옆 아래로 늘어뜨림(더 내리면 손이 허벅지에 파묻힘)
const POLE = [1, -0.6, -0.4]; // 팔꿈치가 향할 방향(바깥 아래 뒤)

const ease = (t: number) => t * t * (3 - 2 * t);
const clamp01 = (t: number) => Math.min(Math.max(t, 0), 1);
const qInv = new THREE.Quaternion();
const dir = new THREE.Vector3(), local = new THREE.Vector3();
const target = new THREE.Vector3(), pole = new THREE.Vector3(), elbow = new THREE.Vector3();
const n = new THREE.Vector3(), b = new THREE.Vector3(), goal = new THREE.Vector3();

// 아래팔이 월드 방향 world 를 가리키도록 팔꿈치 회전을 계산합니다.
function aimFore(arm: ArmBone, world: THREE.Vector3) {
  qInv.copy(arm.upper.quaternion).invert();
  local.copy(world).applyQuaternion(qInv);
  arm.fore.quaternion.setFromUnitVectors(arm.foreDir, local.normalize());
}

// 손이 목표 위치에 오도록 위팔·아래팔 각도를 정합니다(두 관절 IK). 닿지 않으면 그 방향으로 쭉 뻗습니다.
function reach(arm: ArmBone, to: THREE.Vector3) {
  const L1 = arm.elbow.distanceTo(arm.shoulder);
  const L2 = arm.paw.distanceTo(arm.elbow);
  n.subVectors(to, arm.shoulder);
  const d = Math.min(Math.max(n.length(), Math.abs(L1 - L2) + 1e-3), L1 + L2 - 1e-3);
  n.normalize();
  // 팔꿈치가 굽는 방향: POLE 에서 팔 방향 성분을 뺀 것
  pole.set(arm.s * POLE[0], POLE[1], POLE[2]);
  b.copy(pole).addScaledVector(n, -pole.dot(n)).normalize();
  const a = Math.acos(Math.min(Math.max((L1 * L1 + d * d - L2 * L2) / (2 * L1 * d), -1), 1));
  elbow.copy(arm.shoulder).addScaledVector(n, L1 * Math.cos(a)).addScaledVector(b, L1 * Math.sin(a));
  arm.upper.quaternion.setFromUnitVectors(arm.upperDir, dir.subVectors(elbow, arm.shoulder).normalize());
  target.copy(arm.shoulder).addScaledVector(n, d);
  aimFore(arm, dir.subVectors(target, elbow).normalize());
}

// "흑, 흑": 짧은 들썩임 두 번이 SOB_PERIOD 마다 반복
function sob(time: number) {
  const ph = time % SOB_PERIOD;
  const bump = (c: number, w: number) => Math.exp(-(((ph - c) / w) ** 2));
  return bump(0.08, 0.06) + 0.7 * bump(0.32, 0.06);
}

// 지금 닦는 팔과 그 정도(0~1)
function wiping(t: number) {
  for (const [side, start, end] of WIPES) {
    if (t < start || t > end) continue;
    const k = Math.min(ease(clamp01((t - start) / WIPE_IN)), ease(clamp01((end - t) / WIPE_OUT)));
    return { side, k, local: t - start };
  }
  return { side: 0, k: 0, local: 0 };
}

function pose(rig: Rig, time: number) {
  const t = time % CYCLE;
  const s = sob(time);
  const w = wiping(t);

  for (const arm of rig.armBones) {
    // 쉬는 자세: 옆 아래로 늘어뜨린 손, 흐느낄 때 어깨와 함께 살짝 들림
    goal.set(arm.s * RELAX[0], RELAX[1] + 0.12 * s, RELAX[2]).normalize()
      .multiplyScalar(arm.elbow.distanceTo(arm.shoulder) + arm.paw.distanceTo(arm.elbow) - 0.02)
      .add(arm.shoulder);
    if (arm.s === w.side && w.k > 0) {
      // 볼 옆으로 손을 올려 위아래로 쓱쓱(작은 타원) 문지름
      const rub = w.local * 2 * Math.PI / 0.45;
      target.set(arm.s * CHEEK[0], CHEEK[1] + 0.035 * Math.sin(rub), CHEEK[2] + 0.015 * Math.cos(rub));
      goal.lerp(target, w.k);
    }
    reach(arm, goal);
  }

  // 고개: 기본으로 푹 숙이고, 흐느낄 때 까딱, 닦는 손 쪽으로 기울이기,
  //       닦지 않을 때는 가끔 천천히 좌우로 젓기
  const h = rig.headBone.rotation;
  const shake = (1 - w.k) * clamp01(Math.sin(t * Math.PI / CYCLE * 2) ** 2);
  h.x = 0.14 - 0.05 * s;
  h.z = -w.side * 0.16 * w.k;
  h.y = 0.14 * Math.sin(time * 2 * Math.PI / 2.4) * shake;
  // 몸: 흐느낄 때 들썩, 느린 호흡
  const breath = Math.sin(time * 2 * Math.PI / 4.2) * 0.006;
  rig.root.scale.set(1 - breath * 0.5 - 0.006 * s, 1 + breath + 0.016 * s, 1);
}

const CRY: SlothMotion = {
  model: 'sloth-sad-optimized.glb',
  arm: { paw: [0.78, -0.58, 0.18], pawR: 0.15 }, // 이 모델은 손이 조금 아래에 달려 있음
  camera: [0.1, 1.55, 4.7],
  target: [0, 0.9, 0],
  turnY: 0, // 우는 표정이 잘 보이도록 정면
  elbowBlend: 0.04, // 볼을 닦을 때 팔꿈치를 굽히므로 넓게 섞어 주름을 줄입니다.
  speed: 0.65, // 원본의 "더 느리게"
  reducedTime: 0.8, // 동작 줄이기: 고개 숙인 정지 자세
  pose,
};

type Props = { width: number; height: number; className?: string };

export function SlothCry({ width, height, className }: Props) {
  const stageRef = useSloth(CRY);
  return <div ref={stageRef} className={className} style={{ width, height }} aria-hidden="true" />;
}
