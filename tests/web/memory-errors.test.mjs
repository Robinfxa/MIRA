import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const dist = process.env.MIRA_TEST_WEB_DIST
  ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST) + '/').href
  : new URL('../../apps/web/dist/', import.meta.url).href;
const {safeSessionError} = await import(new URL('features/diagnostics/status.js', dist));
const id = 'h_' + 'a'.repeat(32);

for (const [code, words] of [
  ['memory_context_stale', /记忆.*变化.*重新/],
  ['memory_context_overflow', /记忆.*上限.*不会.*丢弃/],
  ['memory_timeout', /本地记忆.*超时/],
  ['memory_unavailable', /本地记忆.*不可用.*配置/],
]) {
  test(`memory failure ${code} has a specific action and validated locator`, () => {
    const text = safeSessionError(code, id);
    assert.match(text, words);
    assert.ok(text.includes(id));
    assert.equal(text.includes('本轮未呈现'), false, 'do not rewrite an already presented prefix');
    assert.equal(text.includes('私有记忆正文'), false);
  });
}

test('untrusted memory-shaped error text is never reflected', () => {
  const text = safeSessionError('memory_私有记忆正文', 'private-metadata');
  assert.equal(text.includes('私有记忆正文'), false);
  assert.equal(text.includes('private-metadata'), false);
});
