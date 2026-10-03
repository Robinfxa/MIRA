import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const dist = process.env.MIRA_TEST_WEB_DIST
  ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST) + '/').href
  : new URL('../../apps/web/dist/', import.meta.url).href;
const { initialSceneState, reduceSceneEffect } = await import(new URL('features/presentation/scene-state.js', dist));
const { SceneEffectExecutor } = await import(new URL('features/presentation/scene-executor.js', dist));
const effect = (kind, value) => ({ id: 'e1', kind, value, digest: 'a'.repeat(64), output_epoch: 1, activity_seq: 1 });
function root() {
  const slots = new Map(['subtitle', 'photo', 'pose', 'scene-label', 'phase-label', 'character-description'].map(name => [name, { textContent: '', hidden: name === 'photo', dataset: {}, setAttribute(name, value) { this[name] = value; } }]));
  return { dataset: {}, slots, querySelector(selector) { return slots.get(selector.replace(/^\[data-|\]$/g, '')) ?? null; }, setAttribute(name, value) { this[name] = value; } };
}

test('scene state applies structured camera and facial actions immutably', () => {
  const original = initialSceneState();
  const lowered = reduceSceneEffect(original, effect('pose', 'camera_lowered'));
  assert.equal(lowered.action, 'camera_lowered');
  assert.equal(original.action, 'camera_ready');
  for (const expression of ['calm', 'warm', 'curious', 'reflective']) {
    assert.equal(reduceSceneEffect(lowered, effect('pose', `face_${expression}`)).expression, expression);
  }
});
test('rain changes environment and turns the character toward the window', () => {
  const state = reduceSceneEffect(initialSceneState(), effect('scene', 'rain_window'));
  assert.equal(state.environment, 'rain_window');
  assert.equal(state.action, 'look_at_rain');
  assert.equal(state.expression, 'reflective');
});
test('photo is a conversation effect and unrelated input never reveals it', () => {
  let state = initialSceneState();
  state = reduceSceneEffect(state, effect('subtitle', '你好'));
  assert.equal(state.photoVisible, false);
  for (const value of ['trip_photo', 'trip_photo_placeholder']) {
    assert.equal(reduceSceneEffect(state, effect('media', value)).photoVisible, true);
  }
});
test('unknown assets and pose values fail closed instead of receiving a false receipt', () => {
  for (const [kind, value] of [['media', 'https://example.org/untrusted.svg'], ['scene', '../private'], ['pose', 'not_a_pose']]) {
    assert.throws(() => reduceSceneEffect(initialSceneState(), effect(kind, value)), /Unsupported scene/);
  }
});
test('explicit phase hooks render all four visible phases and accessible labels', () => {
  const stage = root(); const executor = new SceneEffectExecutor(stage);
  const labels = new Set();
  for (const phase of ['idle', 'listening', 'thinking', 'speaking']) {
    executor.setPhase(phase);
    assert.equal(stage.dataset.phase, phase);
    labels.add(stage.slots.get('phase-label').textContent);
  }
  assert.equal(labels.size, 4);
  assert.ok([...labels].every(Boolean));
});
test('subtitle is literal text and does not falsely start speech', () => {
  const stage = root(); const executor = new SceneEffectExecutor(stage);
  const text = '<img src=x onerror=alert(1)>';
  executor.apply(effect('subtitle', text));
  assert.equal(stage.slots.get('subtitle').textContent, text);
  assert.equal(stage.dataset.phase, 'idle');
});
test('stop exits speech immediately and preserves revealed media, scene and action', () => {
  const stage = root(); const executor = new SceneEffectExecutor(stage);
  executor.apply(effect('media', 'trip_photo'));
  executor.apply(effect('scene', 'rain_window'));
  executor.setPhase('speaking'); executor.stop();
  assert.equal(stage.dataset.phase, 'idle');
  assert.equal(stage.dataset.scene, 'rain_window');
  assert.equal(stage.dataset.action, 'look_at_rain');
  assert.equal(stage.slots.get('photo').hidden, false);
  assert.match(stage.slots.get('subtitle').textContent, /停/);
});
test('new input clears subtitle, starts thinking and preserves displayed facts', () => {
  const stage = root(); const executor = new SceneEffectExecutor(stage);
  executor.apply(effect('pose', 'camera_lowered'));
  executor.apply(effect('media', 'trip_photo_placeholder'));
  executor.apply(effect('subtitle', 'old words'));
  executor.prepareInput();
  assert.equal(stage.dataset.phase, 'thinking');
  assert.equal(stage.slots.get('subtitle').textContent, '');
  assert.equal(stage.dataset.action, 'camera_lowered');
  assert.equal(stage.slots.get('photo').hidden, false);
});
test('an unsupported effect does not mutate an already displayed scene', () => {
  const stage = root(); const executor = new SceneEffectExecutor(stage);
  executor.apply(effect('scene', 'rain_window'));
  assert.throws(() => executor.apply(effect('scene', 'invalid')));
  assert.equal(stage.dataset.scene, 'rain_window');
});
test('expression hook updates the character and descriptive text', () => {
  const stage = root(); const executor = new SceneEffectExecutor(stage);
  executor.setExpression('curious');
  assert.equal(stage.dataset.expression, 'curious');
  assert.match(stage.slots.get('character-description').textContent, /好奇/);
});

test('speech effects fail closed and cannot create a second voice authority', () => {
  const stage = root(); const executor = new SceneEffectExecutor(stage);
  assert.throws(() => executor.apply(effect('speech', 'This belongs to the audio coordinator')), /Unsupported scene/);
  assert.equal(stage.dataset.phase, 'idle');
});
test('stop copy does not invent a previously unseen photo', () => {
  const stage = root(); const executor = new SceneEffectExecutor(stage);
  executor.stop();
  assert.doesNotMatch(stage.slots.get('subtitle').textContent, /照片|插画/);
  assert.equal(stage.slots.get('photo').hidden, true);
});
