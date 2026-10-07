import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

const read = path => readFileSync(new URL(`../../${path}`, import.meta.url));
const html = read('apps/web/index.html').toString('utf8');
const css = read('apps/web/public/app.css').toString('utf8');
const main = read('apps/web/src/app/main.ts').toString('utf8');

test('background choice starts on the original SVG and is a reversible visual-only selector', () => {
  assert.match(html, /data-background-version="classic"/);
  const selector = html.match(/<select[^>]*data-background-choice[^>]*>([\s\S]*?)<\/select>/)?.[1];
  assert.ok(selector, 'the preview selector is present');
  assert.match(selector, /<option value="classic" selected>原版 SVG（默认）<\/option>/);
  assert.match(selector, /<option value="painterly-v3">绘制背景 V3（预览）<\/option>/);
  assert.match(html, /<label for="background-choice">背景预览<\/label>/);
  assert.match(html, /aria-describedby="background-choice-help"/);

  const choice = main.match(/const stage = element<HTMLElement>\('\[data-stage\]'\);([\s\S]*?)const systemNoticeRegion/)
    ?.[1] ?? '';
  assert.match(choice, /document\.querySelector<HTMLSelectElement>\('\[data-background-choice\]'\)/);
  assert.match(choice, /backgroundChoice\.addEventListener\('change', applyBackgroundChoice\)/);
  assert.match(choice, /stage\.dataset\['backgroundVersion'\] = backgroundChoice\.value === 'painterly-v3' \? 'painterly-v3' : 'classic'/);
  assert.doesNotMatch(choice, /controller|data-scene|present|receipt|SceneEffectExecutor/,
    'changing the background does not enter the scene/receipt path');
});

test('classic SVG remains the fallback behind the optional V3 plate', () => {
  assert.match(css, /\.scene-environment\s*\{[^}]*background:\s*url\("\/assets\/scene\/cafe-night\.svg"\) center 49% \/ cover no-repeat/s);
  const v3Rule = css.match(/\.stage\[data-background-version="painterly-v3"\] \.scene-environment\s*\{([^}]+)\}/)?.[1];
  assert.ok(v3Rule, 'the optional plate has an isolated background rule');
  assert.match(v3Rule, /background-image:\s*url\("\/assets\/scene\/cafe-painterly-lighting-v3-table-free\.png"\),\s*url\("\/assets\/scene\/cafe-night\.svg"\)/);
  assert.match(v3Rule, /filter:\s*none/);
  assert.doesNotMatch(css, /\.stage\[data-background-version="painterly-v3"\][^{]*\.character-anchor\s*\{[^}]*filter:/s,
    'no character-layer grading is added for V3');
});

test('the crop contract uses the real Pixi full-height host at desktop and mobile sizes', () => {
  const desktop = css.match(/\.character-anchor\[data-renderer="pixi"\]\s*\{([^}]+)\}/)?.[1];
  const mobile = css.match(/@media \(max-width: 720px\)\s*\{\s*\.character-anchor\[data-renderer="pixi"\]\s*\{([^}]+)\}/)?.[1];
  assert.ok(desktop && mobile);
  assert.match(desktop, /top:\s*0/);
  assert.match(desktop, /right:\s*5%/);
  assert.match(desktop, /bottom:\s*0/);
  assert.match(desktop, /width:\s*47%/);
  assert.match(desktop, /max-width:\s*520px/);
  assert.match(mobile, /top:\s*0/);
  assert.match(mobile, /right:\s*0/);
  assert.match(mobile, /bottom:\s*0/);
  assert.match(mobile, /left:\s*0/);
  assert.match(mobile, /width:\s*auto/);
  assert.match(css, /\.character-anchor\[data-renderer="pixi"\] \.mira-pixi-canvas\s*\{[^}]*object-fit:\s*contain/s);
});

test('rain-window and warm-light remain distinct in V3 using bounded background-only treatment', () => {
  const rain = css.match(/\.stage\[data-background-version="painterly-v3"\]\[data-scene="rain_window"\] \.scene-environment\s*\{([^}]+)\}/)?.[1];
  const warm = css.match(/\.stage\[data-background-version="painterly-v3"\]\[data-scene="cafe_warm"\] \.scene-warmth\s*\{([^}]+)\}/)?.[1];
  const light = css.match(/\.stage\[data-background-version="painterly-v3"\] \.scene-warmth\s*\{([^}]+)\}/)?.[1];
  assert.ok(rain && warm && light);
  assert.match(rain, /background-position:\s*72% 53%/);
  assert.match(rain, /background-size:\s*cover,\s*cover/);
  assert.match(rain, /transform:\s*scale\(1\.08\)/);
  assert.match(warm, /opacity:\s*\.62/);
  assert.match(light, /radial-gradient\(ellipse at 18% 32%/,
    'V3 warmth is a restrained left-anchored environment grade');
  const painterlyRainLayers = css.match(/\.stage\[data-background-version="painterly-v3"\] \.rain-layer\s*\{([^}]+)\}/)?.[1];
  assert.ok(painterlyRainLayers, 'painterly V3 takes ownership of its already-painted raindrops');
  assert.match(painterlyRainLayers, /opacity:\s*0\b/,
    'the animated foreground streaks are suppressed over the painterly glass');
  assert.match(css, /\.rain-near\s*\{[^}]*animation:\s*rain-drift/s,
    'the classic SVG rain overlay remains available when the selector returns to classic');
  assert.match(css, /\.rain-far\s*\{[^}]*animation:\s*rain-drift/s,
    'the classic far-rain overlay also remains available as the fallback');
  assert.doesNotMatch(css, /\.stage\[data-background-version="painterly-v3"\]\[data-scene="rain_window"\] \.rain-near/,
    'scene rain styling cannot re-enable the duplicate V3 foreground streaks');
  assert.match(css, /@media \(max-width: 720px\)[\s\S]*?\.stage\[data-background-version="painterly-v3"\] \.scene-environment\s*\{[^}]*background-position:\s*57% 50%/s);
  assert.match(css, /\.stage\[data-background-version="painterly-v3"\] \.scene-environment\s*\{[^}]*transition:[^;]*transform 1400ms/s);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.stage\[data-background-version="painterly-v3"\] \.scene-environment\s*\{[^}]*transition:\s*none !important/s);
  assert.doesNotMatch(css, /\.stage\[data-background-version="painterly-v3"\]\[data-scene="rain_window"\] \.character-anchor/,
    'the rain zoom is applied to the background element only');
});

test('rain background cover cannot expose an SVG strip around the 721–780px breakpoint', () => {
  const aspect = 1586 / 992;
  const oldSizingCoverThreshold = 50 + 500 * aspect / 1.12;
  assert.ok(oldSizingCoverThreshold > 763 && oldSizingCoverThreshold < 764,
    `expected the old percentage width to begin covering just above ${oldSizingCoverThreshold.toFixed(2)}px`);
  for (const viewportWidth of [721, 740, 760, 763]) {
    // At 721–1020px, app-shell is viewport minus 48px; the stage has 1px borders.
    const stageWidth = viewportWidth - 50;
    const stageHeight = 500;
    const oldRainHeight = stageWidth * 1.12 / aspect;
    assert.ok(oldRainHeight < stageHeight,
      `the former 112% width sizing was too short at ${viewportWidth}px (${oldRainHeight.toFixed(1)}px)`);
    const coverScale = Math.max(stageWidth / 1586, stageHeight / 992);
    assert.ok(1586 * coverScale >= stageWidth);
    assert.ok(992 * coverScale >= stageHeight);
  }
  const at764px = (764 - 50) * 1.12 / aspect;
  assert.ok(at764px >= 500, 'the old 112% width first covered this 500px-tall stage around 764px viewport width');
  const rain = css.match(/\.stage\[data-background-version="painterly-v3"\]\[data-scene="rain_window"\] \.scene-environment\s*\{([^}]+)\}/)?.[1];
  assert.ok(rain);
  assert.match(rain, /background-size:\s*cover,\s*cover/);
  assert.doesNotMatch(rain, /background-size:\s*112%/);
});

test('V3 asset is hash-pinned and all 12 character PNGs remain the original manifest assets', () => {
  const background = read('apps/web/public/scene/cafe-painterly-lighting-v3-table-free.png');
  assert.equal(createHash('sha256').update(background).digest('hex'),
    '4bd221f284181946d9427fd7fab042fba7e56ff8014046c577f0d60fea389fb3');
  assert.equal(background.readUInt32BE(16), 1586);
  assert.equal(background.readUInt32BE(20), 992);
  assert.equal(background[25], 2, 'the environment plate is RGB and has no character alpha mask');

  const manifest = JSON.parse(read('apps/web/public/scene/mira_manifest.json'));
  const frames = [manifest.base, ...Object.values(manifest.expressionVariants),
    ...Object.values(manifest.actionVariants).flatMap(Object.values)];
  assert.equal(frames.length, 12);
  for (const frame of frames) {
    const bytes = read(`apps/web/public/scene/${frame.src}`);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), frame.sha256, frame.src);
  }
});
