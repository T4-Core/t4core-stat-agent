// 확성기를 들고 "알려주세요!" 외치는 나무늘보 3D (원본: public/character/sloth-megaphone.html)
// 되묻기 화면에서 씁니다. 외치는 표정 모델(sloth-shout-optimized.glb)을 따로 불러옵니다.
// 공통 부분(모델·뼈대·장면·정리)은 slothRig.ts 에 있고, 여기에는 확성기 소품과 외치는 동작만 있습니다.
import * as THREE from 'three';
import { useSloth, type ArmBone, type Rig, type SlothMotion } from './slothRig';

// 팔이 짧고 얼굴이 앞으로 나와 있어 손이 입 앞까지 오지 못합니다.
// 그래서 확성기를 볼 옆에서 바깥 앞쪽으로 들고, 고개를 그쪽으로 돌려 외치는 모습으로 만듭니다.
const MEGA_ARM = 1; // 확성기를 드는 팔: 1 = 화면 오른쪽, -1 = 반대
const SHOUT_PERIOD = 2.0; // "알려-주세요!" 한 번 외치는 간격(초): 톡톡 두 번 → 쉼
const HOLD = [0.62, -0.08, 0.32]; // 확성기 손잡이를 쥔 손 위치(모델 좌표, x 부호는 팔마다 자동)
const MEGA_DIR = [0.7, 0.12, 0.7]; // 확성기가 향하는 방향(바깥 앞쪽, 살짝 위)
const WAVE_PERIOD = 1.2; // 반대 손 "여기요" 흔드는 간격(초)
const POLE = [1, -0.7, -0.4]; // 팔꿈치가 향할 방향(바깥 아래 뒤)

const qInv = new THREE.Quaternion();
const dir = new THREE.Vector3(), local = new THREE.Vector3();
const target = new THREE.Vector3(), pole = new THREE.Vector3(), elbow = new THREE.Vector3();
const n = new THREE.Vector3(), b = new THREE.Vector3(), goal = new THREE.Vector3();
const megaDir = new THREE.Vector3(), pawPoint = new THREE.Vector3(), aim = new THREE.Vector3();

// 확성기: 손잡이 아래쪽이 원점, 나팔은 +Z 방향(좁은 쪽 → 넓은 쪽)
function buildMegaphone() {
  const group = new THREE.Group();
  const shell = new THREE.MeshStandardMaterial({ color: '#f6f4ee', roughness: 0.45 });
  const inner = new THREE.MeshStandardMaterial({ color: '#a9d8c8', roughness: 0.6, side: THREE.BackSide });
  const accent = new THREE.MeshStandardMaterial({ color: '#6b998d', roughness: 0.5 });
  const coneGeometry = new THREE.CylinderGeometry(0.12, 0.035, 0.34, 32, 1, true);
  const cone = new THREE.Mesh(coneGeometry, shell);
  cone.rotation.x = Math.PI / 2; // 원기둥 축(Y)을 +Z 로
  cone.position.set(0, 0.075, 0.07);
  const coneInside = new THREE.Mesh(coneGeometry.clone(), inner);
  coneInside.rotation.copy(cone.rotation);
  coneInside.position.copy(cone.position);
  const rim = new THREE.Mesh(new THREE.TorusGeometry(0.12, 0.012, 10, 40), accent);
  rim.position.set(0, 0.075, 0.24);
  const mouth = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.05, 20), accent);
  mouth.rotation.x = Math.PI / 2;
  mouth.position.set(0, 0.075, -0.12);
  const handle = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.08, 16), accent);
  handle.position.set(0, 0.035, -0.02);
  group.add(cone, coneInside, rim, mouth, handle);
  group.traverse((o) => { if (o instanceof THREE.Mesh) o.castShadow = true; });
  // 소리 고리: 외칠 때 나팔 앞으로 퍼져 나감
  const rings = [0, 1, 2].map(() => {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.12, 0.008, 8, 40),
      new THREE.MeshBasicMaterial({ color: '#7ba39d', transparent: true, opacity: 0, depthWrite: false }));
    ring.position.set(0, 0.075, 0.26);
    group.add(ring);
    return ring;
  });
  group.userData.rings = rings;
  return group;
}

// 아래팔이 방향 world 를 가리키도록 팔꿈치 회전을 계산합니다.
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
  pole.set(arm.s * POLE[0], POLE[1], POLE[2]);
  b.copy(pole).addScaledVector(n, -pole.dot(n)).normalize();
  const a = Math.acos(Math.min(Math.max((L1 * L1 + d * d - L2 * L2) / (2 * L1 * d), -1), 1));
  elbow.copy(arm.shoulder).addScaledVector(n, L1 * Math.cos(a)).addScaledVector(b, L1 * Math.sin(a));
  arm.upper.quaternion.setFromUnitVectors(arm.upperDir, dir.subVectors(elbow, arm.shoulder).normalize());
  target.copy(arm.shoulder).addScaledVector(n, d);
  aimFore(arm, dir.subVectors(target, elbow).normalize());
}

// "알려-주세요!": 짧게 톡톡 두 번 내밀고 쉼 (0~1)
function shout(time: number) {
  const ph = time % SHOUT_PERIOD;
  const bump = (c: number, w: number) => Math.exp(-(((ph - c) / w) ** 2));
  return bump(0.15, 0.09) + bump(0.5, 0.11);
}

function pose(rig: Rig, time: number) {
  const s = shout(time);
  megaDir.set(MEGA_ARM * MEGA_DIR[0], MEGA_DIR[1], MEGA_DIR[2]).normalize();

  for (const arm of rig.armBones) {
    if (arm.s === MEGA_ARM) {
      // 확성기 든 손: 외칠 때마다 앞으로 살짝 내밂
      goal.set(arm.s * HOLD[0], HOLD[1] + 0.015 * s, HOLD[2]).addScaledVector(megaDir, 0.035 * s);
    } else {
      // 반대 손: 옆에서 살랑살랑 "여기요!"
      const wave = Math.sin(time * 2 * Math.PI / WAVE_PERIOD);
      goal.set(arm.s * 0.74, -0.2 + 0.05 * wave, 0.22);
    }
    reach(arm, goal);
  }

  // 고개: 확성기 쪽으로 돌리고, 외칠 때 앞으로 까딱
  const h = rig.headBone.rotation;
  h.y = MEGA_ARM * 0.3;
  h.x = 0.03 + 0.06 * s;
  h.z = -MEGA_ARM * 0.04 * Math.sin(time * 2 * Math.PI / 3);
  // 몸: 외칠 때 들썩 + 호흡
  const breath = Math.sin(time * 2 * Math.PI / 3.6) * 0.006;
  rig.root.scale.set(1 - breath * 0.5, 1 + breath + 0.02 * s, 1);

  // 확성기를 손 위치·방향에 맞춤 (뼈를 움직인 뒤 위치를 다시 계산해야 정확합니다)
  const body = rig.skinned.parent;
  const mega = body?.userData.megaphone as THREE.Group | undefined;
  if (!body || !mega) return;
  body.updateMatrixWorld(true);
  const arm = rig.armBones.find((a) => a.s === MEGA_ARM)!;
  pawPoint.copy(arm.paw).sub(arm.elbow); // 손 = 팔꿈치 뼈 기준 위치
  arm.fore.localToWorld(pawPoint);
  body.worldToLocal(pawPoint);
  mega.position.copy(pawPoint).y += 0.02;
  aim.copy(mega.position).add(megaDir);
  mega.lookAt(body.localToWorld(aim));

  // 소리 고리: 외칠 때마다 차례로 커지며 사라짐
  const ph = (time % SHOUT_PERIOD) / 0.9;
  (mega.userData.rings as THREE.Mesh<THREE.BufferGeometry, THREE.MeshBasicMaterial>[]).forEach((ring, i) => {
    const k = Math.max(0, Math.min(ph - i * 0.18, 1));
    const on = ph - i * 0.18 > 0 && ph - i * 0.18 < 1;
    ring.material.opacity = on ? 0.7 * (1 - k) : 0;
    const sc = 1 + 1.4 * k;
    ring.scale.set(sc, sc, 1);
    ring.position.z = 0.26 + 0.18 * k;
  });
}

const MEGAPHONE: SlothMotion = {
  model: 'sloth-shout-optimized.glb',
  // 이 모델은 팔이 옆으로 뻗고 높이 달려 있음. 손 반지름이 작으면 손 아래에 뾰족한 막이 생깁니다.
  arm: { shoulder: [0.45, -0.3, 0.08], elbow: [0.63, -0.34, 0.13], paw: [0.8, -0.38, 0.18], pawR: 0.16 },
  // 확성기가 오른쪽으로 나와 있어 화면 안에 들어오도록 카메라를 오른쪽으로 옮기고 조금 뒤로 뺐습니다.
  camera: [0.28, 1.55, 5.1],
  target: [0.18, 0.88, 0],
  turnY: -0.25, // 확성기 쪽 얼굴이 카메라를 보도록 살짝 돌림
  elbowBlend: 0.04, // 팔꿈치를 굽히므로 넓게 섞어 주름을 줄입니다.
  speed: 0.65, // 원본의 "더 느리게"
  reducedTime: 1.0, // 동작 줄이기: 확성기를 든 정지 자세
  decorate: (body) => {
    const mega = buildMegaphone();
    body.userData.megaphone = mega;
    body.add(mega);
  },
  pose,
};

type Props = { width: number; height: number; className?: string };

export function SlothMegaphone({ width, height, className }: Props) {
  const stageRef = useSloth(MEGAPHONE);
  return <div ref={stageRef} className={className} style={{ width, height }} aria-hidden="true" />;
}
