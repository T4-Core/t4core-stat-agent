// 나무늘보 3D 공통 부품: 모델 불러오기 · 뼈대 만들기 · 장면/조명 · 그리기 반복 · 정리
// 원본: public/character/sloth-3d-glb.html(타이핑), sloth-wave.html(손 흔들기), sloth-cry.html(울기)
// 모션마다 다른 것(모델·카메라·몸 방향·소품·동작)은 SlothMotion 으로 넘겨받습니다.
// 뼈대 좌표(RIG)는 원본과 같게 유지해야 모양이 깨지지 않습니다.
import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

const DEFAULT_MODEL = 'sloth-optimized.glb'; // public/character 안의 파일 이름
const modelUrl = (file: string) => `${import.meta.env.BASE_URL}character/${file}`;
// 모델이 Draco 로 압축되어 있어 해제 도구를 CDN 에서 받습니다. (three 버전과 맞춰야 함)
const DRACO_DECODER = 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/libs/draco/gltf/';

// ── 뼈대 위치(모델 원본 좌표, 정면 = +Z) ────────────────
// GLB 에 뼈대가 없어서, 불러온 뒤 코드에서 뼈를 만들고 정점마다 따라갈 뼈를 위치로 계산합니다.
export const RIG = {
  neck: new THREE.Vector3(0, -0.1, 0.02),
  headStart: -0.13, headFull: 0.0, // 이 높이 사이에서 머리 가중치가 0→1
  arms: [-1, 1].map((s) => ({
    s,
    shoulder: new THREE.Vector3(s * 0.42, -0.3, 0.05),
    elbow: new THREE.Vector3(s * 0.62, -0.43, 0.1),
    paw: new THREE.Vector3(s * 0.78, -0.55, 0.18),
    upperR: 0.17, foreR: 0.17, pawR: 0.12, fade: 0.05, // 소매·손 두께(반지름)와 경계 부드러움
  })),
  legGuard: [-0.75, -0.7], // 이 높이 아래(다리·발)는 팔에서 제외
};

type RigSpec = typeof RIG;

// 모델마다 손이 달린 높이가 조금 달라 손 위치·반지름만 바꿔 씁니다.
// (손 아랫부분이 손 영역에서 빠지면 손을 들 때 그 부분이 막처럼 늘어납니다)
function rigFor(paw?: SlothMotion['paw']): RigSpec {
  if (!paw) return RIG;
  return {
    ...RIG,
    arms: RIG.arms.map((a) => ({ ...a, paw: new THREE.Vector3(a.paw.x, paw.y, a.paw.z), pawR: paw.r })),
  };
}

export type ArmBone = (typeof RIG.arms)[number] & {
  upper: THREE.Bone;
  fore: THREE.Bone;
  upperDir: THREE.Vector3; // 원래 자세의 위팔 방향
  foreDir: THREE.Vector3; // 원래 자세의 아래팔 방향
};
export type Rig = { skinned: THREE.SkinnedMesh; root: THREE.Bone; headBone: THREE.Bone; armBones: ArmBone[] };

// 모션마다 다른 설정
export type SlothMotion = {
  model?: string; // public/character 안의 GLB 파일 이름 (없으면 기본 나무늘보)
  paw?: { y: number; r: number }; // 손 위치 높이·반지름 보정 (모델이 다를 때만)
  camera: [number, number, number]; // 카메라 위치
  target: [number, number, number]; // 카메라가 바라보는 곳
  turnY: number; // 몸을 돌리는 각도(라디안)
  elbowBlend: number; // 팔꿈치 경계에서 위팔·아래팔을 섞는 폭 (넓을수록 굽힐 때 주름이 적음)
  speed: number; // 재생 속도 (1 = 원본 기본 속도)
  reducedTime: number; // '동작 줄이기' 설정일 때 보여줄 정지 자세의 시각
  decorate?: (body: THREE.Group) => void; // 소품 추가 (예: 노트북)
  pose: (rig: Rig, time: number) => void; // 시각(초)에 맞춰 뼈를 움직임
};

// ── 가중치 계산 도우미 ─────────────────────────────────
export const smooth = (a: number, b: number, x: number) => {
  const t = Math.min(Math.max((x - a) / (b - a), 0), 1);
  return t * t * (3 - 2 * t);
};
const _ab = new THREE.Vector3();
const _ap = new THREE.Vector3();
let segmentT = 0; // 마지막으로 계산한 선분 위 위치(0=a, 1=b)
function segment(p: THREE.Vector3, a: THREE.Vector3, b: THREE.Vector3) { // 점 p와 선분 ab 사이의 거리
  _ab.subVectors(b, a);
  _ap.subVectors(p, a);
  const t = Math.min(Math.max(_ap.dot(_ab) / _ab.lengthSq(), 0), 1);
  segmentT = t;
  return _ap.sub(_ab.multiplyScalar(t)).length();
}

// 뼈 번호: 0 몸, 1 머리, 2·3 왼팔(위·아래), 4·5 오른팔(위·아래)
function computeWeights(geometry: THREE.BufferGeometry, elbowBlend: number, spec: RigSpec) {
  const pos = geometry.attributes.position;
  const count = pos.count;
  const skinIndex = new Uint16Array(count * 4);
  const skinWeight = new Float32Array(count * 4);
  const p = new THREE.Vector3();
  const pawTips = spec.arms.map((a) => a.paw.clone().add(a.paw.clone().sub(a.elbow).setLength(0.06)));

  for (let i = 0; i < count; i++) {
    p.fromBufferAttribute(pos, i);
    const head = smooth(spec.headStart, spec.headFull, p.y);
    const legGuard = smooth(spec.legGuard[0], spec.legGuard[1], p.y);
    const w = [0, head, 0, 0, 0, 0];
    spec.arms.forEach((a, k) => {
      if (Math.sign(p.x) !== a.s && Math.abs(p.x) > 0.02) return; // 반대쪽 팔은 무시
      const dUpper = segment(p, a.shoulder, a.elbow);
      const dFore = segment(p, a.elbow, pawTips[k]);
      // 아래팔은 팔꿈치(두꺼운 소매) → 손(작은 발)으로 갈수록 가늘어지는 원뿔 모양
      const foreR = THREE.MathUtils.lerp(a.foreR, a.pawR, smooth(0.45, 0.85, segmentT));
      const upper = 1 - smooth(a.upperR, a.upperR + a.fade, dUpper);
      const fore = 1 - smooth(foreR, foreR + a.fade * 0.6, dFore);
      const total = Math.max(upper, fore) * legGuard * (1 - head);
      if (total <= 0) return;
      // 더 가까운 뼈를 따르고, 팔꿈치 경계에서만 섞습니다.
      const foreShare = smooth(-elbowBlend, elbowBlend, dUpper - dFore);
      w[2 + k * 2] = total * (1 - foreShare);
      w[3 + k * 2] = total * foreShare;
    });
    w[0] = Math.max(0, 1 - w.slice(1).reduce((x, y) => x + y, 0));
    // 가장 큰 4개만 사용하고 합이 1이 되도록 정규화
    const order = w.map((v, j) => [v, j] as const).sort((x, y) => y[0] - x[0]).slice(0, 4);
    const sum = order.reduce((x, y) => x + y[0], 0) || 1;
    order.forEach(([v, j], n) => { skinIndex[i * 4 + n] = j; skinWeight[i * 4 + n] = v / sum; });
  }
  geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(skinIndex, 4));
  geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute(skinWeight, 4));
}

function buildSkin(mesh: THREE.Mesh, elbowBlend: number, spec: RigSpec): Rig {
  const geometry = mesh.geometry;
  computeWeights(geometry, elbowBlend, spec);

  // 뼈 만들기 (팔꿈치는 위팔의 자식)
  const root = new THREE.Bone();
  const headBone = new THREE.Bone();
  headBone.position.copy(spec.neck);
  root.add(headBone);
  const bones = [root, headBone];
  const armBones = spec.arms.map((a) => {
    const upper = new THREE.Bone();
    upper.position.copy(a.shoulder);
    root.add(upper);
    const fore = new THREE.Bone();
    fore.position.subVectors(a.elbow, a.shoulder);
    upper.add(fore);
    bones.push(upper, fore);
    return {
      ...a, upper, fore,
      upperDir: a.elbow.clone().sub(a.shoulder).normalize(),
      foreDir: a.paw.clone().sub(a.elbow).normalize(),
    };
  });

  const skinned = new THREE.SkinnedMesh(geometry, mesh.material);
  skinned.add(root);
  skinned.updateMatrixWorld(true);
  skinned.bind(new THREE.Skeleton(bones));
  skinned.castShadow = true;
  skinned.receiveShadow = true;
  skinned.frustumCulled = false; // 팔을 들면 원래 경계 상자를 벗어나므로
  return { skinned, root, headBone, armBones };
}

// stage(빈 상자) 안에 3D 나무늘보를 그리고, 정리 함수를 돌려줍니다.
function mountSloth(stage: HTMLElement, motion: SlothMotion) {
  let disposed = false; // 화면을 떠난 뒤 모델 로딩이 끝나도 아무것도 하지 않게 막습니다.
  let rig: Rig | null = null;

  // ── 렌더러 · 장면 · 카메라 ─────────────────────────
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.style.cssText = 'display:block;width:100%;height:100%;visibility:hidden';
  stage.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.05, 50);
  camera.position.set(...motion.camera);
  camera.lookAt(...motion.target); // 원본의 OrbitControls 기준점과 같은 곳을 봅니다.

  scene.add(new THREE.HemisphereLight('#ffffff', '#d5ddd3', 2.2));
  const key = new THREE.DirectionalLight('#fff8ef', 1.6);
  key.position.set(2, 4, 3.5);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, { left: -1.5, right: 1.5, top: 2.2, bottom: -0.5 });
  key.shadow.radius = 6;
  key.shadow.bias = -0.0008;
  scene.add(key);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(8, 8), new THREE.ShadowMaterial({ opacity: 0.12 }));
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);

  // ── 모델 불러오기 ──────────────────────────────────
  const sloth = new THREE.Group();
  sloth.rotation.y = motion.turnY;
  scene.add(sloth);
  const draco = new DRACOLoader().setDecoderPath(DRACO_DECODER);
  new GLTFLoader().setDRACOLoader(draco).loadAsync(modelUrl(motion.model ?? DEFAULT_MODEL))
    .then((gltf) => {
      if (disposed) return;
      const source = gltf.scene.getObjectByProperty('isMesh', true) as THREE.Mesh | undefined;
      if (!source) throw new Error('GLB 안에 메시가 없어요.');
      source.geometry.computeBoundingBox();
      rig = buildSkin(source, motion.elbowBlend, rigFor(motion.paw));
      const body = new THREE.Group();
      body.position.y = -source.geometry.boundingBox!.min.y; // 발바닥을 바닥(y=0)에 맞춤
      body.add(rig.skinned);
      motion.decorate?.(body);
      sloth.add(body);
      renderer.domElement.style.visibility = 'visible';
    })
    .catch((error) => console.error('나무늘보 캐릭터를 불러오지 못했어요.', error))
    .finally(() => draco.dispose()); // 해제가 끝나면 작업 스레드 정리

  // ── 크기 맞추기 · 그리기 반복 ───────────────────────
  // 화면 전체 확대·축소(StageLayout)와 CSS 축소까지 반영된 "실제로 보이는 크기"로 그려서 선명하게 유지합니다.
  // 고해상도 화면에서는 더 촘촘하게 그리되 최대 2배로 제한합니다.
  // 창 크기·화면 해상도가 바뀌어도 따라가도록 매 프레임 확인하고, 바뀌었을 때만 다시 맞춥니다.
  let fitted = '';
  const fit = () => {
    const { width, height } = stage.getBoundingClientRect();
    if (!width) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const key = `${width}x${height}@${ratio}`;
    if (key === fitted) return;
    fitted = key;
    renderer.setPixelRatio(ratio);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };

  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  let time = 0;
  let last: number | null = null;
  let frameId = 0;
  const frame = (now: number) => {
    if (last != null && !motionQuery.matches && !document.hidden) time += Math.min((now - last) / 1000, 0.1) * motion.speed;
    last = now;
    // 동작 줄이기 설정이면 정지 자세를 보여줍니다.
    if (rig) motion.pose(rig, motionQuery.matches ? motion.reducedTime : time);
    fit();
    renderer.render(scene, camera);
    frameId = requestAnimationFrame(frame);
  };
  frameId = requestAnimationFrame(frame);

  // ── 화면을 떠날 때 정리 (없으면 캐릭터가 겹쳐 그려지고 메모리가 쌓입니다) ──
  return () => {
    disposed = true;
    cancelAnimationFrame(frameId);
    scene.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      object.geometry.dispose();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach((material: THREE.Material) => {
        Object.values(material).forEach((value) => { if (value instanceof THREE.Texture) value.dispose(); });
        material.dispose();
      });
    });
    renderer.dispose();
    renderer.domElement.remove();
  };
}

// 상자(div)에 붙일 ref 를 돌려줍니다. 상자가 화면에 나타나면 3D 를 시작하고, 사라지면 정리합니다.
export function useSloth(motion: SlothMotion) {
  const stageRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!stageRef.current) return;
    return mountSloth(stageRef.current, motion);
  }, [motion]);
  return stageRef;
}
