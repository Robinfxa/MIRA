import { loadPublicConfig } from '../shared/config.js';
import { SceneEffectExecutor } from '../features/presentation/scene-executor.js';
import { MiraApiClient } from '../features/session/api-client.js';
import { SessionController } from '../features/session/controller.js';
import { recordingNotice, safeSessionError, watchDiagnosticsStatus } from '../features/diagnostics/status.js';

function element<T extends HTMLElement>(selector: string): T {
  const value = document.querySelector<T>(selector);
  if (!value) throw new Error(`Missing application element ${selector}`);
  return value;
}
const config = loadPublicConfig();
const status = element('[data-status]');
const diagnostic = element('[data-diagnostic]');
const error = element('[data-error]');
const ptt = element<HTMLButtonElement>('[data-ptt]');
const voiceHint = element('[data-voice-hint]');
const recordingBanner = element('[data-recording-notice]');
const rehearsalButton = element<HTMLButtonElement>('[data-rehearsal-input]');
const rehearsalHint = element('[data-rehearsal-hint]');
let rehearsalAvailable = false;
let rehearsalHeld: string | null = null;
const diagnosticsWatcher = watchDiagnosticsStatus(config, value => {
  const notice = recordingNotice(value);
  recordingBanner.hidden = !notice.visible;
  recordingBanner.textContent = notice.text;
  recordingBanner.dataset['recordingState'] = notice.state;
});
let microphoneAvailable = false;
let held: string | null = null;
let closed = false;
function defaultVoiceHint(): string {
  return microphoneAvailable ? '按住说话，松开后等待可靠转写。停止会立即释放麦克风。' : '麦克风识别未配置或浏览器不支持。可以继续用文字。';
}
const controller = new SessionController(
  new MiraApiClient(config), new SceneEffectExecutor(element('[data-stage]')), {
    connected() { if (!closed) element<HTMLFieldSetElement>('fieldset').disabled = false; },
    update(view) {
      status.textContent = view.phase;
      diagnostic.textContent = JSON.stringify({
        state: view.revision, activity: view.activity_seq, output: view.output_epoch,
        permit: view.permit_revision, grants: view.active_grants.length,
        presented: view.presented_effects.length, audioFacts: view.audio_progress.length, sealed: view.sealed,
      }, null, 2);
      if (view.last_error) error.textContent = safeSessionError(view.last_error, view.last_error_diagnostic_id);
    },
    error(message) { error.textContent = message; },
    localStop() { status.textContent = 'stopped · 本地已制止'; },
    capabilities(value) {
      if (closed) return;
      microphoneAvailable = value.microphone_enabled && typeof navigator.mediaDevices?.getUserMedia === 'function'
        && typeof globalThis.AudioContext === 'function' && typeof globalThis.AudioWorkletNode === 'function' && globalThis.isSecureContext;
      ptt.disabled = !microphoneAvailable;
      const modes = {mock: 'Mock · 固定场景', replay: 'Fixture · 生成夹具回放', rehearsal: 'OFFLINE · 离线排练', injected: '注入后端 · 尚未验收'};
      element('[data-mode-label]').textContent = modes[value.generation_mode];
      rehearsalAvailable = value.generation_mode === 'rehearsal' && value.qualification === 'offline_fixture';
      element('[data-rehearsal-banner]').hidden = !rehearsalAvailable;
      element('[data-rehearsal-controls]').hidden = !rehearsalAvailable;
      rehearsalButton.disabled = !rehearsalAvailable;
      element('[data-mode-description]').textContent = rehearsalAvailable
        ? 'OFFLINE 离线排练：固定口令、预先制作的英文合成音频与双语字幕。没有调用真实模型或 Google 服务；不识别自由对话，不采集麦克风。插画为原创本地矢量素材。字幕按整句语音 cue 呈现，不是逐字对齐，也不能证明用户听见。'
        : `${modes[value.generation_mode]}。${value.qualification === 'unavailable'
        ? '真实语音尚未配置，当前使用文字。' : '语音后端已注入；账户、扬声器、麦克风与真实打断仍需单独验收。'}角色和旅行插画是原创矢量素材，不代表实时生图。字幕显示不代表已经听见或逐字对齐。`;
      voiceHint.textContent = defaultVoiceHint();
    },
    rehearsalInput(state) {
      rehearsalButton.setAttribute('aria-pressed', String(state === 'listening'));
      if (state === 'stopped') rehearsalHeld = null;
      rehearsalHint.textContent = state === 'listening'
        ? '正在演练 listening 状态，没有录音或识别。松开只会发送固定口令「照片里有什么」。'
        : '合成输入演练：按住观察 listening；松开发送固定口令「照片里有什么」。不打开麦克风。';
    },
    microphone(state) {
      ptt.setAttribute('aria-pressed', String(state === 'recording' || state === 'starting'));
      voiceHint.textContent = state === 'starting' ? '正在打开麦克风；请在浏览器中自行决定是否授权。'
        : state === 'recording' ? '正在听。松开后结束录音并等待转写。'
        : state === 'finishing' ? '录音已停止，正在等待可靠的最终转写…' : defaultVoiceHint();
    },
  }, config,
);
function releaseGesture(cancel: boolean): void {
  if (held === null) return;
  held = null;
  if (cancel) void controller.stop();
  else void controller.finishMicrophone();
}
function startGesture(identity: string): void {
  if (closed || ptt.disabled || held !== null || rehearsalHeld !== null) return;
  held = identity;
  error.textContent = '';
  void controller.startMicrophone();
}
ptt.addEventListener('pointerdown', event => {
  if (event.button !== 0) return;
  event.preventDefault();
  startGesture(`pointer:${event.pointerId}`);
  try { ptt.setPointerCapture(event.pointerId); } catch { /* Window pointerup still releases capture. */ }
});
const pointerUp = (event: PointerEvent) => {
  if (held === `pointer:${event.pointerId}`) releaseGesture(false);
};
ptt.addEventListener('pointerup', pointerUp);
window.addEventListener('pointerup', pointerUp);
ptt.addEventListener('pointercancel', () => releaseGesture(true));
ptt.addEventListener('lostpointercapture', () => releaseGesture(true));
ptt.addEventListener('keydown', event => {
  if (event.key !== ' ' && event.key !== 'Enter') return;
  event.preventDefault();
  if (!event.repeat) startGesture(`key:${event.key}`);
});
ptt.addEventListener('keyup', event => {
  if (event.key !== ' ' && event.key !== 'Enter') return;
  event.preventDefault();
  if (held === `key:${event.key}`) releaseGesture(false);
});
// Assistive-technology activation can use a start/finish toggle without pointer events.
ptt.addEventListener('click', event => {
  if (event.detail !== 0) return;
  if (held === 'accessible') releaseGesture(false);
  else if (held === null) startGesture('accessible');
});
function releaseRehearsal(cancel: boolean): void {
  if (rehearsalHeld === null) return;
  rehearsalHeld = null;
  if (cancel) void controller.stop();
  else void controller.finishRehearsalInput();
}
function startRehearsal(identity: string): void {
  if (closed || !rehearsalAvailable || rehearsalButton.disabled || held !== null || rehearsalHeld !== null) return;
  error.textContent = '';
  void controller.startRehearsalInput();
  rehearsalHeld = identity;
}
rehearsalButton.addEventListener('pointerdown', event => {
  if (event.button !== 0) return;
  event.preventDefault(); startRehearsal(`pointer:${event.pointerId}`);
  try { rehearsalButton.setPointerCapture(event.pointerId); } catch { /* Window release is also observed. */ }
});
const rehearsalPointerUp = (event: PointerEvent) => {
  if (rehearsalHeld === `pointer:${event.pointerId}`) releaseRehearsal(false);
};
rehearsalButton.addEventListener('pointerup', rehearsalPointerUp);
window.addEventListener('pointerup', rehearsalPointerUp);
rehearsalButton.addEventListener('pointercancel', () => releaseRehearsal(true));
rehearsalButton.addEventListener('lostpointercapture', () => releaseRehearsal(true));
rehearsalButton.addEventListener('keydown', event => {
  if (event.key !== ' ' && event.key !== 'Enter') return;
  event.preventDefault(); if (!event.repeat) startRehearsal(`key:${event.key}`);
});
rehearsalButton.addEventListener('keyup', event => {
  if (event.key !== ' ' && event.key !== 'Enter') return;
  event.preventDefault(); if (rehearsalHeld === `key:${event.key}`) releaseRehearsal(false);
});
rehearsalButton.addEventListener('click', event => {
  if (event.detail !== 0) return;
  if (rehearsalHeld === 'accessible') releaseRehearsal(false);
  else if (rehearsalHeld === null) startRehearsal('accessible');
});
window.addEventListener('blur', () => releaseRehearsal(true));
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') releaseRehearsal(true); });
window.addEventListener('blur', () => releaseGesture(true));
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') releaseGesture(true); });

element<HTMLFormElement>('form').addEventListener('submit', event => {
  event.preventDefault();
  const input = element<HTMLInputElement>('[name=message]');
  if (!input.value.trim()) return;
  error.textContent = '';
  held = null; rehearsalHeld = null;
  void controller.input(input.value);
  input.value = '';
});
element('[data-stop]').addEventListener('click', () => { held = null; rehearsalHeld = null; void controller.stop(); });
for (const button of document.querySelectorAll<HTMLButtonElement>('[data-command]')) {
  button.addEventListener('click', () => {
    error.textContent = ''; held = null; rehearsalHeld = null;
    void controller.input(button.dataset.command ?? '');
  });
}
element('[data-close]').addEventListener('click', () => {
  closed = true; held = null; rehearsalHeld = null; ptt.disabled = true; rehearsalButton.disabled = true;
  diagnosticsWatcher.close();
  element<HTMLFieldSetElement>('fieldset').disabled = true;
  void controller.close().then(() => { status.textContent = 'closed · 刷新可新建'; });
});
window.addEventListener('pagehide', () => { closed = true; held = null; rehearsalHeld = null; diagnosticsWatcher.close(); void controller.close(); });
void controller.connect().catch(() => { error.textContent = '连接失败。请刷新后重试；未启动任何语音。'; });
