import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist = pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST ?? 'apps/web/dist') + '/');
const {initialSceneState, reduceSceneEffect} = await import(new URL('features/presentation/scene-state.js', dist));
const effect = value => ({id:'e1',kind:'pose',value,digest:'a'.repeat(64),output_epoch:1,activity_seq:1});
test('code-native wardrobe is orthogonal to expression and speaking phase', () => {
  const previous = {...initialSceneState(), phase:'speaking', expression:'calm'};
  assert.equal(previous.outfit, 'outfit_black_jacket');
  const next = reduceSceneEffect(previous, effect('outfit_amber_raincoat'));
  assert.equal(next.outfit, 'outfit_amber_raincoat');
  assert.equal(next.phase, 'speaking');
  assert.equal(next.expression, 'calm');
  assert.equal(previous.outfit, 'outfit_black_jacket');
});
