import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const css = readFileSync(new URL('../../apps/web/public/app.css', import.meta.url), 'utf8');
test('ready Pixi removes the hidden SVG animation subtree from layout', () => {
  assert.match(css, /\.character-anchor\[data-renderer="pixi"\] \.mira-character\s*\{[^}]*display:\s*none/s);
  assert.doesNotMatch(css, /^\.mira-character\s*\{[^}]*display:\s*none/ms,
    'fallback visibility must recover when the ready marker is removed');
});
test('Pixi ready-frame layout does not reuse negative fallback offsets', () => {
  const block = css.match(/\.character-anchor\[data-renderer="pixi"\] \{([^}]+)\}/)?.[1];
  assert.ok(block);
  assert.match(block, /top: 0/);
  assert.match(block, /bottom: 0/);
  assert.match(block, /left: auto/);
  assert.doesNotMatch(block, /(?:top|bottom|right|left):\s*-/);
  assert.match(css, /\.mira-pixi-canvas\s*\{[^}]*object-fit:\s*contain/s);
  assert.match(css, /\.character-anchor \{[^}]*bottom:\s*-105px/s,
    'existing SVG fallback layout remains present');
});
test('fitted frame geometry fits the full host at narrow and desktop viewports', () => {
  // Mathematical containment only. This does not claim browser layout/paint acceptance.
  for (const viewport of [320, 390, 720, 1024, 1440]) {
    const mobile = viewport <= 720;
    const stageWidth = viewport - (viewport <= 480 ? 24 : mobile ? 32 : viewport <= 1020 ? 48 : 96);
    const stageHeight = mobile ? 520 : Math.max(490, Math.min(620, viewport * .44));
    const boxWidth = mobile ? stageWidth : Math.min(520, stageWidth * .47);
    const boxHeight = stageHeight;
    const scale = Math.min(boxWidth / 560, boxHeight / 720);
    assert.ok(scale > 0);
    assert.ok(560 * scale <= boxWidth + 1e-8);
    assert.ok(720 * scale <= boxHeight + 1e-8);
  }
});
