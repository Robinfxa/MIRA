import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';

const page = await readFile(new URL('../../apps/web/local-memory.html', import.meta.url), 'utf8');
const entry = await readFile(new URL('../../apps/web/src/local-memory/main.ts', import.meta.url), 'utf8');
const css = await readFile(new URL('../../apps/web/public/local-memory.css', import.meta.url), 'utf8');
const source = await readFile(new URL('../../apps/web/src/features/session/memory-management.ts', import.meta.url), 'utf8');
const dist = process.env.MIRA_TEST_WEB_DIST ? resolve(process.env.MIRA_TEST_WEB_DIST) : resolve('apps/web/dist');

test('dedicated page and mount bundle stay local-only', async () => {
  const bundle = await readFile(resolve(dist, 'local-memory/main.js'), 'utf8');
  assert.match(page, /data-local-only-notice/);
  assert.match(page, /不会向外部服务传送记忆内容/);
  assert.match(page, /不含对话页面、模型、语音或媒体功能/);
  assert.doesNotMatch(page, /name="message"|data-ptt|data-stage|\/api\/v1\/sessions/);
  assert.doesNotMatch(page, /dist\/app\/main\.js|src\/app\/main/);
  assert.match(entry, /mountOperatorPairing\(document, \{/);
  assert.match(entry, /mountMemoryManagement\(document, \{localOnly: true\}\)/);
  assert.doesNotMatch(entry, /Actor|provider|Codex|TypeSafe|audio|fetch\(/i);
  assert.match(source, /localOnly\?: boolean/);
  assert.match(source, /此工具没有模型或提供方路由/);
  assert.match(css, /\.memory-management-panel/);
  assert.match(bundle, /api\/v1\/operator\/status/);
  assert.match(bundle, /api\/v1\/memory-management\/operations/);
  assert.doesNotMatch(bundle, /api\/v1\/sessions|api\/v1\/voice|api\/v1\/diagnostics/);
});
