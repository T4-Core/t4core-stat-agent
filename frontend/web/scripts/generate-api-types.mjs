// 실행 중인 FastAPI 의 /openapi.json 을 읽어 src/api/openapi.d.ts 를 만듭니다.
// 스키마만 읽으므로 HCX 비용이 발생하지 않습니다.  사용법: npm run gen:api
import { mkdir, writeFile } from 'node:fs/promises';
import openapiTS, { astToString } from 'openapi-typescript';
import { loadEnv } from 'vite';

const env = { ...loadEnv('development', process.cwd(), ''), ...process.env };
const backendUrl = (env.BACKEND_URL || 'http://localhost:8000').replace(/\/$/, '');
const schemaUrl = new URL(`${backendUrl}/openapi.json`);
const output = new URL('../src/api/openapi.d.ts', import.meta.url);

try {
  const ast = await openapiTS(schemaUrl, { defaultNonNullable: false });
  const header = '// 자동 생성 파일입니다. 직접 수정하지 말고 npm run gen:api 로 다시 만드세요.\n';
  await mkdir(new URL('.', output), { recursive: true });
  await writeFile(output, header + astToString(ast), 'utf8');
  console.log('API 타입을 생성했습니다: src/api/openapi.d.ts');
} catch (error) {
  console.error(`백엔드 스키마를 읽지 못했습니다. ${schemaUrl} 가 켜져 있는지 확인하세요.`);
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
}
