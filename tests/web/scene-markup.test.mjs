import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
const read = path => readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8');
const html = read('apps/web/index.html');
const css = read('apps/web/public/app.css');

test('scene preserves integration selectors and adds explicit voice and phase hooks', () => {
  for (const name of ['stage', 'scene-label', 'status', 'pose', 'photo', 'subtitle', 'diagnostic', 'stop', 'close', 'error', 'ptt', 'phase-label', 'mode-label', 'voice-hint', 'character-description']) {
    assert.match(html, new RegExp(`data-${name}(?:[\\s=>])`), name);
  }
  assert.match(html, /name="message"/);
  assert.doesNotMatch(html, /<fieldset[^>]*disabled/);
  assert.match(html, /data-send-message[^>]*disabled/);
  assert.match(html, /data-connect-retry/);
});
test('art identifies an original adult and contains real independently animated character layers', () => {
  assert.match(html, /26 岁/);
  for (const layer of ['mira-breath', 'mira-head', 'mira-eyes', 'mira-camera', 'mouth-speaking', 'expression-warm', 'expression-curious', 'expression-reflective']) {
    assert.match(html, new RegExp(`class="[^"]*${layer}`), layer);
  }
  assert.match(css, /@keyframes\s+mira-breathe/);
  assert.match(css, /@keyframes\s+mira-blink/);
  assert.match(css, /@keyframes\s+mira-talk/);
});
test('all four phases and persistent character actions have visual styles', () => {
  for (const phase of ['idle', 'listening', 'thinking', 'speaking']) assert.ok(css.includes(`[data-phase="${phase}"]`), phase);
  for (const action of ['camera_lowered', 'look_at_rain']) assert.ok(css.includes(`[data-action="${action}"]`), action);
  for (const expression of ['warm', 'curious', 'reflective']) assert.ok(css.includes(`[data-expression="${expression}"]`), expression);
});
test('layout includes narrow viewport and reduced motion support with accessible controls', () => {
  assert.match(css, /@media\s*\(max-width:\s*480px\)/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(css, /animation:\s*none\s*!important/);
  assert.match(css, /:focus-visible/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /aria-describedby="voice-hint"/);
  assert.match(html, /<label[^>]*for="message"/);
});
test('diagnostics stay collapsed and photo is initially absent', () => {
  assert.match(html, /<details class="technical-details">/);
  assert.match(html, /data-photo hidden/);
  assert.doesNotMatch(html, /<details[^>]*\bopen\b/);
});
test('the existing Stop control stays unique and precedes the rehearsal guide', () => {
  const controls = html.match(/<fieldset class="conversation-controls">([\s\S]*?)<\/fieldset>/)?.[1];
  assert.ok(controls, 'conversation controls keep an editable draft fieldset');

  const stops = [...html.matchAll(/<button\b[^>]*data-stop\b[^>]*>[\s\S]*?<\/button>/g)];
  assert.equal(stops.length, 1, 'the existing Stop button remains unique');
  assert.match(stops[0][0], /type="button"[\s\S]*停止全部/, 'global Stop is clearly labeled separately from reply interruption');
  const guideIndex = controls.indexOf('<section class="rehearsal-guide"');
  assert.ok(guideIndex >= 0, 'the offline rehearsal guide remains in the conversation controls');
  const stopIndex = controls.indexOf('data-stop');
  assert.ok(stopIndex >= 0, 'the unique Stop control remains inside the conversation fieldset');
  assert.ok(stopIndex < guideIndex, 'Stop precedes the long guide in source order');
  assert.match(read('apps/web/src/app/main.ts'), /element\('\[data-stop\]'\)\.addEventListener\('click'/,
    'the existing Stop handler selector is unchanged');
});
test('continuous listening exposes a distinct reply-only interruption control and cautious onset limits', () => {
  assert.match(html, /data-continuous-interrupt[^>]*hidden[^>]*>打断回应，继续听我说</);
  assert.match(html, /系统没有声学回声检测/);
  assert.match(html, /噪声或扬声器回声可能影响结果/);
  assert.match(html, /自动分句可能根据停顿判断/);
  assert.match(read('apps/web/src/app/main.ts'), /continuousInterrupt\.addEventListener\('click',\s*\(\)\s*=>\s*\{\s*submissionGeneration\+\+;[\s\S]*?controller\.interruptReply\(\)/);
});
test('long rehearsal help is progressively disclosed while fixed conversation controls remain', () => {
  const controls = html.match(/<fieldset class="conversation-controls">([\s\S]*?)<\/fieldset>/)?.[1];
  assert.ok(controls, 'conversation controls keep an editable draft fieldset');
  const helpIndex = controls.indexOf('<details class="rehearsal-instructions">');
  assert.ok(helpIndex >= 0, 'lengthy help uses native details disclosure');

  const help = controls.slice(helpIndex).match(/<details class="rehearsal-instructions">[\s\S]*?<\/details>/)?.[0];
  assert.ok(help, 'rehearsal details are closed cleanly');
  assert.match(help, /<summary>[^<]+<\/summary>/, 'native summary provides the disclosure control');
  assert.doesNotMatch(help.match(/^<details\b[^>]*>/)?.[0] ?? '', /\bopen(?:[\s=>])/,
    'long help is collapsed initially');
  assert.match(help, /<ol[\s>]/, 'the full step-by-step guidance remains available');
  assert.doesNotMatch(help, /data-command|data-rehearsal-input/, 'fixed commands and synthetic input stay outside the disclosure');

  const guide = controls.slice(controls.indexOf('<section class="rehearsal-guide"'), helpIndex);
  for (const hook of ['data-rehearsal-controls', 'data-command="你好"', 'data-command="讲讲旅途"',
    'data-command="照片里有什么"', 'data-command="暖灯"', 'data-ptt', 'data-rehearsal-input', 'data-voice-hint']) {
    assert.ok(controls.includes(hook), `existing conversation hook remains: ${hook}`);
  }
  assert.ok(guide.includes('data-rehearsal-input'), 'the offline synthetic-input control stays outside the disclosure');
  assert.match(css, /summary:focus-visible/, 'native disclosure summary keeps a visible keyboard focus state');
});
test('original visual assets are local with no remote font or image dependency', () => {
  assert.doesNotMatch(html + css, /(?:src|href)=["']https?:\/\//);
  assert.doesNotMatch(css, /url\(["']?https?:\/\//);
  for (const asset of ['cafe-night.svg', 'trip-memory.svg']) {
    assert.ok(existsSync(new URL(`../../apps/web/public/scene/${asset}`, import.meta.url)), asset);
  }
});
