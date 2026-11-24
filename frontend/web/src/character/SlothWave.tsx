// 손 흔들며 인사하는 나무늘보 3D (public/character/sloth-wave.html 을 React 로 옮긴 것)
// 원본에서 안내 문구·재생 버튼·속도 선택·마우스 회전·디버그 기능은 뺐습니다.
// 뼈대 좌표(RIG)와 모션 숫자는 원본과 같게 유지해야 모양이 깨지지 않습니다.
import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

const MODEL_URL = `${import.meta.env.BASE_URL}character/sloth-optimized.glb`;
// 모델이 Draco 로 압축되어 있어 해제 도구를 CDN 에서 받습니다. (three 버전과 맞춰야 함)
const DRACO_DECODER = 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/libs/draco/gltf/';
const SPEED = 0.65; // 원본의 "더 느리게" 재생 속도

// ── 뼈대 위치(모델 원본 좌표, 정면 = +Z) ────────────────
// GLB 에 뼈대가 없어서, 불러온 뒤 코드에서 뼈를 만들고 정점마다 따라갈 뼈를 위치로 계산합니다.
const RIG = {
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

type ArmBone = (typeof RIG.arms)[number] & {
  upper: THREE.Bone;
  fore: THREE.Bone;
  upperDir: THREE.Vector3;
  foreDir: THREE.Vector3;
};
type Rig = { skinned: THREE.SkinnedMesh; root: THREE.Bone; headBone: THREE.Bone; armBones: ArmBone[] };

// ── 가중치 계산 도우미 ─────────────────────────────────
const smooth = (a: number, b: number, x: number) => {
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
function computeWeights(geometry: THREE.BufferGeometry) {
  const pos = geometry.attributes.position;
  const count = pos.count;
  const skinIndex = new Uint16Array(count * 4);
  const skinWeight = new Float32Array(count * 4);
  const p = new THREE.Vector3();
  const pawTips = RIG.arms.map((a) => a.paw.clone().add(a.paw.clone().sub(a.elbow).setLength(0.06)));

  for (let i = 0; i < count; i++) {
    p.fromBufferAttribute(pos, i);
    const head = smooth(RIG.headStart, RIG.headFull, p.y);
    const legGuard = smooth(RIG.legGuard[0], RIG.legGuard[1], p.y);
    const w = [0, head, 0, 0, 0, 0];
    RIG.arms.forEach((a, k) => {
      if (Math.sign(p.x) !== a.s && Math.abs(p.x) > 0.02) return; // 반대쪽 팔은 무시
      const dUpper = segment(p, a.shoulder, a.elbow);
      const dFore = segment(p, a.elbow, pawTips[k]);
      // 아래팔은 팔꿈치(두꺼운 소매) → 손(작은 발)으로 갈수록 가늘어지는 원뿔 모양
      const foreR = THREE.MathUtils.lerp(a.foreR, a.pawR, smooth(0.45, 0.85, segmentT));
      const upper = 1 - smooth(a.upperR, a.upperR + a.fade, dUpper);
      const fore = 1 - smooth(foreR, foreR + a.fade * 0.6, dFore);
      const total = Math.max(upper, fore) * legGuard * (1 - head);
      if (total <= 0) return;
      // 더 가까운 뼈를 따르고, 팔꿈치 경계에서만 섞어 주름을 줄입니다.
      const foreShare = smooth(-0.04, 0.04, dUpper - dFore);
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

function buildSkin(mesh: THREE.Mesh): Rig {
  const geometry = mesh.geometry;
  computeWeights(geometry);

  // 뼈 만들기 (팔꿈치는 위팔의 자식)
  const root = new THREE.Bone();
  const headBone = new THREE.Bone();
  headBone.position.copy(RIG.neck);
  root.add(headBone);
  const bones = [root, headBone];
  const armBones = RIG.arms.map((a) => {
    const upper = new THREE.Bone();
    upper.position.copy(a.shoulder);
    root.add(upper);
    const fore = new THREE.Bone();
    fore.position.subVectors(a.elbow, a.shoulder);
    upper.add(fore);
    bones.push(upper, fore);
    return {
      ...a, upper, fore,
      upperDir: a.elbow.clone().sub(a.shoulder).normalize(), // 원래 자세의 위팔 방향
      foreDir: a.paw.clone().sub(a.elbow).normalize(), // 원래 자세의 아래팔 방향
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

type Props = { width: number; height: number; className?: string };

export function SlothWave({ width, height, className }: Props) {
  const stageRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    let disposed = false; // 화면을 떠난 뒤 모델 로딩이 끝나도 아무것도 하지 않게 막습니다.
    let rig: Rig | null = null;

    // ── 렌더러 · 장면 · 카메라 ─────────────────────────
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.style.cssText = 'display:block;width:100%;height:100%;visibility:hidden';
    stage.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.05, 50);
    camera.position.set(0.1, 1.55, 4.7);
    camera.lookAt(0, 0.9, 0); // 원본의 OrbitControls 기준점과 같은 곳을 봅니다.

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
    sloth.rotation.y = -0.15; // 흔드는 손이 카메라 쪽으로 살짝 오도록
    scene.add(sloth);
    const draco = new DRACOLoader().setDecoderPath(DRACO_DECODER);
    new GLTFLoader().setDRACOLoader(draco).loadAsync(MODEL_URL)
      .then((gltf) => {
        if (disposed) return;
        const source = gltf.scene.getObjectByProperty('isMesh', true) as THREE.Mesh | undefined;
        if (!source) throw new Error('GLB 안에 메시가 없어요.');
        source.geometry.computeBoundingBox();
        rig = buildSkin(source);
        const body = new THREE.Group();
        body.position.y = -source.geometry.boundingBox!.min.y; // 발바닥을 바닥(y=0)에 맞춤
        body.add(rig.skinned);
        sloth.add(body);
        renderer.domElement.style.visibility = 'visible';
      })
      .catch((error) => console.error('나무늘보 캐릭터를 불러오지 못했어요.', error))
      .finally(() => draco.dispose()); // 해제가 끝나면 작업 스레드 정리

    // ── 크기 맞추기 · 그리기 반복 ───────────────────────
    const resize = () => {
      const { width: w, height: h } = stage.getBoundingClientRect();
      if (!w) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(stage);
    resize();

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    let time = 0;
    let last: number | null = null;
    let frameId = 0;
    const frame = (now: number) => {
      if (last != null && !motionQuery.matches && !document.hidden) time += Math.min((now - last) / 1000, 0.1) * SPEED;
      last = now;
      // 동작 줄이기 설정이면 손을 든 정지 자세를 보여줍니다.
      if (rig) pose(rig, motionQuery.matches ? 1.0 : time);
      renderer.render(scene, camera);
      frameId = requestAnimationFrame(frame);
    };
    frameId = requestAnimationFrame(frame);

    // ── 화면을 떠날 때 정리 (없으면 캐릭터가 겹쳐 그려지고 메모리가 쌓입니다) ──
    return () => {
      disposed = true;
      cancelAnimationFrame(frameId);
      observer.disconnect();
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
  }, []);

  return <div ref={stageRef} className={className} style={{ width, height }} aria-hidden="true" />;
}
