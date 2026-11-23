// npm run dev: 관리자 페이지(5174)를 먼저 켜고 사용자 화면(5173)을 켭니다. Ctrl+C 를 누르면 함께 꺼집니다.
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import net from 'node:net';
import { dirname, join } from 'node:path';
import readline from 'node:readline';
import { fileURLToPath } from 'node:url';

const ADMIN_PORT = 5174;
const ADMIN_WAIT_MS = 10_000;
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const viteBin = join(root, 'node_modules', 'vite', 'bin', 'vite.js');
const adminConfig = join(root, 'admin', 'vite.config.ts');

let admin = null;
let web = null;
let stopping = false;

const log = (message) => console.log(`[admin] ${message}`);

function canConnect(host) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port: ADMIN_PORT });
    const finish = (result) => { socket.destroy(); resolve(result); };
    socket.setTimeout(300, () => finish(false));
    socket.once('connect', () => finish(true));
    socket.once('error', () => finish(false));
  });
}

async function isPortInUse() {
  const results = await Promise.all([canConnect('127.0.0.1'), canConnect('::1')]);
  return results.some(Boolean);
}

async function isAdminServer() {
  try {
    const response = await fetch(`http://localhost:${ADMIN_PORT}/`, { signal: AbortSignal.timeout(1500) });
    return (await response.text()).includes('T4core 관리자 콘솔');
  } catch {
    return false;
  }
}

async function startAdmin() {
  if (!existsSync(adminConfig)) return;
  if (await isPortInUse()) {
    if (await isAdminServer()) log(`이미 켜져 있는 관리자 서버를 사용합니다: http://localhost:${ADMIN_PORT}/`);
    else log(`${ADMIN_PORT}번 포트를 다른 프로그램이 사용 중이라 관리자 페이지를 켜지 않았습니다.`);
    return;
  }

  const child = spawn(process.execPath, [viteBin, '--config', adminConfig], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  admin = child;
  for (const stream of [child.stdout, child.stderr]) {
    readline.createInterface({ input: stream }).on('line', (line) => { if (line.trim()) log(line.trim()); });
  }
  let exited = false;
  child.once('error', (error) => {
    exited = true;
    admin = null;
    log(`관리자 페이지를 켜지 못했습니다: ${error.message}`);
  });
  child.once('exit', () => {
    exited = true;
    admin = null;
    if (!stopping) log('관리자 서버가 종료되었습니다. 사용자 화면은 계속 동작합니다.');
  });

  // 사용자 화면이 5174번을 먼저 차지하지 않도록 관리자 서버가 뜰 때까지 기다립니다.
  const deadline = Date.now() + ADMIN_WAIT_MS;
  while (!exited && Date.now() < deadline) {
    if (await isPortInUse()) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  if (!exited) log('관리자 서버 시작이 늦어지고 있습니다. 사용자 화면을 먼저 켭니다.');
}

function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  const children = [admin, web].filter(Boolean);
  if (children.length === 0) process.exit(code);
  let left = children.length;
  for (const child of children) {
    child.once('exit', () => {
      left -= 1;
      if (left === 0) process.exit(code);
    });
    child.kill();
  }
  setTimeout(() => process.exit(code), 2000).unref();
}

for (const signal of ['SIGINT', 'SIGTERM', 'SIGBREAK', 'SIGHUP']) process.on(signal, () => stop(0));

if (!existsSync(viteBin)) {
  console.error('vite 를 찾지 못했습니다. 이 폴더에서 npm install 을 먼저 실행해 주세요.');
  process.exit(1);
}

await startAdmin();
if (!stopping) {
  web = spawn(process.execPath, [viteBin, ...process.argv.slice(2)], { cwd: root, stdio: 'inherit' });
  web.once('error', (error) => {
    console.error(`사용자 화면을 켜지 못했습니다: ${error.message}`);
    web = null;
    stop(1);
  });
  web.once('exit', (code) => {
    web = null;
    stop(code ?? 0);
  });
}
