// 노트북으로 타이핑하는 나무늘보 3D (원본: public/character/sloth-3d-glb.html)
// 공통 부분(모델·뼈대·장면·정리)은 slothRig.ts 에 있고, 여기에는 노트북과 타이핑 동작만 있습니다.
import * as THREE from 'three';
import { useSloth, type Rig, type SlothMotion } from './slothRig';
import { TAP_PERIOD, TYPING_SPEED } from './typingTiming';

// ── 노트북(모델 좌표 기준, 무릎 위) ─────────────────────
function buildLaptop() {
  const metal = new THREE.MeshStandardMaterial({ color: '#dfe1e5', roughness: 0.4, metalness: 0.12 });
  const laptop = new THREE.Group();
  laptop.position.set(0, -0.545, 0.63);
  const base = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.022, 0.44), metal);
  base.castShadow = base.receiveShadow = true;
  laptop.add(base);
  // 키보드 무늬는 캔버스에 그려서 그림(텍스처)으로 붙입니다.
  const kc = document.createElement('canvas');
  kc.width = 520;
  kc.height = 200;
  const kx = kc.getContext('2d')!;
  kx.fillStyle = '#c9ccd1';
  kx.fillRect(0, 0, 520, 200);
  kx.fillStyle = '#55595f';
  for (let r = 0; r < 5; r++) for (let i = 0; i < 13; i++) { kx.beginPath(); kx.roundRect(8 + i * 39, 8 + r * 38, 33, 32, 5); kx.fill(); }
  const tex = new THREE.CanvasTexture(kc);
  tex.colorSpace = THREE.SRGBColorSpace;
  const keyboard = new THREE.Mesh(new THREE.PlaneGeometry(0.7, 0.25), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.6 }));
  keyboard.rotation.x = -Math.PI / 2;
  keyboard.position.set(0, 0.0115, 0.04);
  laptop.add(keyboard);
  const hinge = new THREE.Group();
  hinge.position.set(0, 0.011, 0.215);
  hinge.rotation.x = 0.24;
  laptop.add(hinge);
  const lid = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.5, 0.022), metal);
  lid.position.y = 0.25;
  lid.castShadow = true;
  hinge.add(lid);
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.72, 0.42),
    new THREE.MeshStandardMaterial({ color: '#eef6f2', emissive: '#d9efe6', emissiveIntensity: 0.5 }));
  screen.position.set(0, 0.25, -0.012);
  screen.rotation.y = Math.PI;
  hinge.add(screen);
  const leafShape = new THREE.Shape();
  leafShape.moveTo(0, -0.065);
  leafShape.quadraticCurveTo(0.06, 0, 0, 0.065);
  leafShape.quadraticCurveTo(-0.06, 0, 0, -0.065);
  const leaf = new THREE.Mesh(new THREE.ShapeGeometry(leafShape, 16), new THREE.MeshStandardMaterial({ color: '#a3dccb', roughness: 0.5 }));
  leaf.position.set(0, 0.24, 0.012);
  leaf.rotation.z = -0.7;
  hinge.add(leaf);
  return laptop;
}

// ── 모션: 두 손 번갈아 키보드 톡톡 ──────────────────────
// TAP_PERIOD: 한 손이 키를 한 번 누르는 간격(초). 두 손이 번갈아 치므로 이 시간의 절반마다 한 번씩 톡.
// 값은 typingTiming.ts 에 있습니다. (답변 생성 중 화면이 같은 박자로 단계를 넘깁니다)
const qType = new THREE.Quaternion();
const v1 = new THREE.Vector3(), v2 = new THREE.Vector3();

function pose(rig: Rig, time: number) {
  const beat = time * 2 * Math.PI / TAP_PERIOD;

  for (const arm of rig.armBones) {
    // 손을 키보드 위에 두고, 두 손이 번갈아 천천히 톡톡
    const wave = Math.sin(beat + (arm.s > 0 ? Math.PI : 0));
    const tap = Math.max(0, wave) ** 1.5;
    v2.set(arm.s * 0.2 + Math.sin(time * 0.9 + arm.s) * 0.02, // 다른 키로 조금씩 이동
      -0.47 + tap * 0.07, 0.56 - tap * 0.015);
    v1.subVectors(arm.paw, arm.shoulder).normalize();
    qType.setFromUnitVectors(v1, v2.sub(arm.shoulder).normalize());
    arm.upper.quaternion.copy(qType);
  }

  // 고개: 타이핑 박자에 맞춰 천천히 끄덕이고, 아주 살짝 기울임
  const h = rig.headBone.rotation;
  h.x = 0.02 + 0.045 * Math.sin(beat * 2);
  h.z = 0.04 * Math.sin(time * 2 * Math.PI / 6);
  h.y = 0.03 * Math.sin(time * 2 * Math.PI / 8);
  // 몸: 호흡
  const breath = Math.sin(time * 2 * Math.PI / 3.6) * 0.006;
  rig.root.scale.set(1 - breath * 0.5, 1 + breath, 1);
}

const TYPING: SlothMotion = {
  camera: [0.25, 1.95, 4.6],
  target: [0, 0.85, 0.15],
  turnY: 0.3, // 원본처럼 살짝 옆을 보도록
  elbowBlend: 0.025, // 50:50 으로 섞이면 팔꿈치를 펼 때 소매가 납작하게 찌그러지므로 좁게
  speed: TYPING_SPEED, // 원본 기본 속도의 0.6배
  reducedTime: 3, // 동작 줄이기: 키보드 위 정지 자세
  decorate: (body) => body.add(buildLaptop()),
  pose,
};

type Props = { width: number; height: number; className?: string };

export function SlothTyping({ width, height, className }: Props) {
  const stageRef = useSloth(TYPING);
  return <div ref={stageRef} className={className} style={{ width, height }} aria-hidden="true" />;
}
