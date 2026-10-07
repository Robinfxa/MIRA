import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';

const dist = process.env.MIRA_TEST_WEB_DIST ? resolve(process.env.MIRA_TEST_WEB_DIST) : resolve('apps/web/dist');
const {SceneEffectExecutor} = await import(new URL('features/presentation/scene-executor.js', `file://${dist}/`));
const css = await readFile(resolve('apps/web/public/app.css'), 'utf8');
const selector = phase => `.stage[data-phase="${phase}"] .character-anchor[data-renderer="pixi"] .mira-pixi-canvas`;
const rule = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const cssBlock = pattern => css.match(pattern)?.[1] ?? '';

test('each live Pixi phase selects only its own compositor motion', () => {
  const phases = {
    idle: 'pixi-character-idle-breath',
    listening: 'pixi-character-listen-lean',
    speaking: 'pixi-character-speaking-nod',
  };
  for (const [phase, animation] of Object.entries(phases)) {
    const block = cssBlock(new RegExp(`${rule(selector(phase))}\\s*\\{([^}]*)\\}`));
    assert.match(block, new RegExp(`animation:\\s*${animation}\\b`), `${phase} Pixi motion selector`);
    assert.match(css, new RegExp(`@keyframes\\s+${animation}\\s*\\{`), `${animation} keyframes`);
  }
  assert.doesNotMatch(css, /\.character-anchor\s*\{[^}]*animation:\s*pixi-character-/s,
    'the SVG/fallback anchor must not inherit Pixi-only motion');
});

test('motion stays within gentle translations/tilts and preserves full-frame contain layout', () => {
  for (const name of ['pixi-character-idle-breath', 'pixi-character-listen-lean', 'pixi-character-speaking-nod']) {
    const body = cssBlock(new RegExp(`@keyframes\\s+${name}\\s*\\{([^}]+)\\}`));
    assert.ok(body, `missing ${name}`);
    assert.doesNotMatch(body, /(?:width|height|clip|object-fit|background|filter)\s*:/);
  }
  assert.match(css, /\.character-anchor\[data-renderer="pixi"\] \.mira-pixi-canvas\s*\{[^}]*object-fit:\s*contain/s);
  assert.match(css, /\.character-anchor\[data-renderer="pixi"\] \.mira-pixi-canvas\s*\{[^}]*object-position:\s*center bottom/s);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)[^{]*\{[^}]*\.mira-pixi-canvas/s);
});

class Slot {
  constructor() { this.dataset = {}; this.style = {}; this.hidden = false; this.textContent = ''; }
}
function fakeStage() {
  const names = ['subtitle', 'photo', 'pose', 'scene-label', 'phase-label', 'character-description'];
  const elements = Object.fromEntries(names.map(name => [name, new Slot()]));
  const anchor = new Slot();
  const root = new Slot();
  root.querySelector = selector => selector.startsWith('[data-') ? elements[selector.slice(6, -1)] ?? null
    : selector === '.character-anchor' ? anchor : null;
  return {root, anchor, elements};
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test('real scene phase hooks drive Pixi CSS state, Stop returns to breath, close removes animation eligibility', async () => {
  const stage = fakeStage();
  const rendered = [];
  const executor = new SceneEffectExecutor(stage.root, {characterRendererFactory: async () => ({
    render(state) { rendered.push(state.phase); stage.anchor.dataset.renderer = 'pixi'; },
    destroy() { delete stage.anchor.dataset.renderer; },
  })});
  await tick();
  for (const phase of ['idle', 'listening', 'thinking', 'speaking']) {
    executor.setPhase(phase);
    assert.equal(stage.root.dataset.phase, phase);
    assert.equal(stage.anchor.dataset.renderer, 'pixi');
    if (phase === 'thinking') assert.doesNotMatch(css, new RegExp(rule(selector(phase))));
    else assert.match(css, new RegExp(rule(selector(phase))));
  }
  executor.stop();
  assert.equal(stage.root.dataset.phase, 'idle', 'Stop immediately restores the gentle idle state');
  assert.equal(rendered.at(-1), 'idle', 'no stale speaking phase is rendered after Stop');
  executor.close();
  assert.equal(stage.anchor.dataset.renderer, undefined, 'closed renderer falls back and stops Pixi motion');
});
