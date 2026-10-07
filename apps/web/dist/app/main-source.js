import { mountConversationArchive } from '../features/session/conversation-archive.js';
import { loadPublicConfig } from '../shared/config.js';
import { SceneEffectExecutor } from '../features/presentation/scene-executor.js';
import { MiraApiClient, MiraHttpError } from '../features/session/api-client.js';
import { SessionController } from '../features/session/controller.js';
import { ContinuousListeningController } from '../features/session/continuous-listening.js';
import { recordingNotice, safeSessionError, watchDiagnosticsStatus } from '../features/diagnostics/status.js';
import { ReviewedAudioPanel } from '../features/diagnostics/reviewed-audio.js';
import { mountTrustedDeviceAccess } from '../features/session/trusted-device-access.js';
import { mountOperatorPairing } from '../features/session/operator-pairing.js';
import { mountMemoryManagement } from '../features/session/memory-management.js';
let operatorGate = null;
let memoryManagement = null;
let conversationArchive = null;
function startSessionApp() {
    if (document.body?.dataset['conversationArchive'] === 'enabled') {
        conversationArchive = mountConversationArchive(document, { start: startConversationApp });
        return conversationArchive;
    }
    return startConversationApp();
}
function startConversationApp() {
    if (document.body?.dataset['operatorPairing'] === 'required'
        && document.body.dataset['memoryManagement'] === 'enabled') {
        memoryManagement = mountMemoryManagement(document);
    }
    function element(selector) {
        const value = document.querySelector(selector);
        if (!value)
            throw new Error(`Missing application element ${selector}`);
        return value;
    }
    const microphonePreview = element('[data-microphone-preview]');
    const microphoneTimingPanel = element('[data-microphone-timing-panel]');
    const microphoneTiming = element('[data-microphone-timing]');
    const responseMute = document.querySelector('[data-response-mute]');
    const responseVoiceStatus = document.querySelector('[data-response-voice-status]');
    const config = loadPublicConfig();
    const privateHttpText = document.body?.dataset['privateHttpText'] === 'true';
    const status = element('[data-status]');
    const diagnostic = element('[data-diagnostic]');
    const error = element('[data-error]');
    const stage = element('[data-stage]');
    const backgroundChoice = document.querySelector('[data-background-choice]');
    if (backgroundChoice) {
        const applyBackgroundChoice = () => {
            stage.dataset['backgroundVersion'] = backgroundChoice.value === 'painterly-v3' ? 'painterly-v3' : 'classic';
        };
        backgroundChoice.addEventListener('change', applyBackgroundChoice);
        applyBackgroundChoice();
    }
    const systemNoticeRegion = document.querySelector('[data-system-notice]');
    const systemNoticeBody = document.querySelector('[data-system-notice-body]');
    let systemNoticeFallback = null;
    const ptt = element('[data-ptt]');
    const continuousButton = element('[data-continuous-listening]');
    const continuousPanel = element('[data-continuous-panel]');
    const continuousStatus = element('[data-continuous-status]');
    const continuousPreview = element('[data-continuous-preview]');
    const continuousSend = element('[data-continuous-send]');
    const continuousInterrupt = element('[data-continuous-interrupt]');
    const continuousBargeMode = document.querySelector('[data-continuous-barge-mode]');
    // Only a choice made through this version's control may override the new default.
    // Browser form restoration can otherwise reapply the old first option after an upgrade.
    const bargePreferenceKey = 'mira.voice.barge-mode.v1';
    let selectedBargeMode = 'headphones';
    try {
        if (window.localStorage.getItem(bargePreferenceKey) === 'guarded')
            selectedBargeMode = 'guarded';
    }
    catch { /* Storage denial does not prevent voice input or the current explicit choice. */ }
    if (continuousBargeMode) {
        continuousBargeMode.value = selectedBargeMode;
        continuousBargeMode.addEventListener('change', () => {
            if (continuousBargeMode.disabled)
                return;
            selectedBargeMode = continuousBargeMode.value === 'guarded' ? 'guarded' : 'headphones';
            continuousBargeMode.value = selectedBargeMode;
            try {
                window.localStorage.setItem(bargePreferenceKey, selectedBargeMode);
            }
            catch { /* Keep in-page choice. */ }
        });
        window.addEventListener('pageshow', () => {
            continuousBargeMode.value = selectedBargeMode;
        });
    }
    const captureProcessing = document.querySelector('[data-capture-processing]');
    const continuousSentText = element('[data-continuous-sent-text]');
    const continuousRecordingLimit = element('[data-continuous-recording-limit]');
    const continuousReviewBlock = element('[data-continuous-review-block]');
    const messageInput = element('[name=message]');
    const sendMessage = element('[data-send-message]');
    const connectRetry = element('[data-connect-retry]');
    const connectionStatus = element('[data-connection-status]');
    const voiceHint = element('[data-voice-hint]');
    const recordingBanner = element('[data-recording-notice]');
    const conversationLog = document.querySelector('[data-conversation-log]');
    const conversationEmpty = document.querySelector('[data-conversation-empty]');
    const conversationHistoryNote = document.querySelector('[data-conversation-history-note]');
    const turnStatus = document.querySelector('[data-turn-status]');
    const conversationMessages = [];
    let latestSubtitleActivity = 0;
    let latestSubtitleOutputEpoch = 0;
    function showTurn(text, state) {
        if (!turnStatus)
            return;
        turnStatus.textContent = text;
        turnStatus.dataset['state'] = state;
    }
    function appendConversation(role, text, key, continuation) {
        if (!conversationLog || !text || conversationMessages.some(item => item.pieces.has(key)))
            return;
        const followLatest = conversationLog.scrollHeight - conversationLog.scrollTop - conversationLog.clientHeight < 72;
        const prior = continuation ? conversationMessages.find(item => item.key === continuation.key) : undefined;
        if (prior && prior.end === continuation?.start) {
            // Exact disjoint ranges only: no repeated prefix, inserted whitespace or speech timing inference.
            prior.body.textContent = (prior.body.textContent ?? '') + text;
            prior.pieces.add(key);
            prior.end = continuation.end;
            if (followLatest)
                conversationLog.scrollTop = conversationLog.scrollHeight;
            return;
        }
        const item = document.createElement('li');
        item.className = `conversation-message conversation-message--${role}`;
        const label = document.createElement('span');
        label.className = 'conversation-message-author';
        label.textContent = role === 'user' ? '你' : 'MIRA';
        const body = document.createElement('p');
        body.textContent = text;
        item.append(label, body);
        conversationLog.append(item);
        conversationMessages.push({ key: prior ? key : continuation?.key ?? key, pieces: new Set([key]),
            body, end: continuation?.end ?? null });
        if (conversationEmpty)
            conversationEmpty.hidden = true;
        if (conversationMessages.length > 80) {
            conversationMessages.shift();
            conversationLog.firstElementChild?.remove();
            if (conversationHistoryNote)
                conversationHistoryNote.textContent = document.body?.dataset['conversationArchive'] === 'enabled'
                    ? '当前页面显示最近 80 条消息；本机档案的实际保存状态请在记录面板核对。'
                    : '当前页面保留最近 80 条消息，较早消息已移出；刷新后清空。';
        }
        if (followLatest)
            conversationLog.scrollTop = conversationLog.scrollHeight;
    }
    function appendPresentedSubtitle(effect) {
        if (effect.kind !== 'subtitle' || effect.activity_seq < latestSubtitleActivity
            || effect.output_epoch < latestSubtitleOutputEpoch)
            return;
        latestSubtitleActivity = effect.activity_seq;
        latestSubtitleOutputEpoch = effect.output_epoch;
        // Optional forward-compatible projection; the protocol owner validates authority and chunk schema.
        // Unchunked cues retain their existing one-message semantics.
        const chunk = effect.caption_chunk;
        const valid = chunk && /^[0-9a-f-]{36}$/i.test(chunk.group_id)
            && /^[0-9a-f]{64}$/.test(chunk.source_sha256)
            && Number.isInteger(chunk.index) && chunk.index >= 0 && chunk.index <= 3
            && Number.isInteger(chunk.start) && chunk.start >= 0 && Number.isInteger(chunk.end)
            && chunk.end > chunk.start && Number.isInteger(chunk.total) && chunk.total <= 4096
            && chunk.end <= chunk.total && Array.from(effect.value).length === chunk.end - chunk.start;
        const continuation = valid ? { key: `reply:${effect.activity_seq}:${effect.output_epoch}:${chunk.group_id}:${chunk.source_sha256}`,
            start: chunk.start, end: chunk.end } : undefined;
        appendConversation('assistant', effect.value, `effect:${effect.id}`, continuation);
    }
    const rehearsalButton = element('[data-rehearsal-input]');
    const rehearsalHint = element('[data-rehearsal-hint]');
    let rehearsalAvailable = false;
    let rehearsalHeld = null;
    let gestureReviewFence = null;
    let rehearsalReviewFence = null;
    const diagnosticsWatcher = watchDiagnosticsStatus(config, value => {
        const notice = recordingNotice(value);
        recordingBanner.hidden = !notice.visible;
        recordingBanner.textContent = notice.text;
        recordingBanner.dataset['recordingState'] = notice.state;
    });
    let microphoneAvailable = false;
    let continuousAvailable = false;
    let reviewCanEnable = false;
    let continuous = null;
    let lastContinuousView = null;
    let held = null;
    let gestureInputRevision = 0;
    let rehearsalInputRevision = 0;
    let messageRevision = 0;
    let recoveredDraft = null;
    const recoveredNotice = element('[data-recovered-input-notice]');
    const recoveredLabel = element('[data-recovered-input-label]');
    function renderRecoveredDraft() {
        recoveredNotice.hidden = recoveredDraft === null;
        recoveredLabel.textContent = recoveredDraft === null ? '' : !recoveredDraft.target
            ? '这段语音的原请求来源无法确定。请核对文字，再选择“改为新话题”后发送。'
            : recoveredDraft.edited ? '已修改恢复文字；发送时仍作为被打断请求的补充。若另起话题，请先选择“改为新话题”。'
                : '已恢复待核对语音；发送时将补充被打断的原请求。若另起话题，请先选择“改为新话题”。';
    }
    element('[data-recovered-new-topic]').addEventListener('click', () => {
        recoveredDraft = null;
        renderRecoveredDraft();
        error.textContent = '已选择新话题；核对后点击发送。';
    });
    // A UI send may await microphone teardown before it reaches the controller.
    // Keep that continuation inside the same user intent, independently of draft edits.
    let submissionGeneration = 0;
    // A queued voice-enable command keeps its original gesture order while capture
    // teardown is pending. Other queued text still submits under the current mute.
    let outputMuteGeneration = 0;
    function explicitlyEnablesVoice(text) {
        const command = text.trim().toLowerCase().replace(/[。.!！ ]+$/u, '').replace(/^请/u, '');
        return ['取消静音', '可以开声音', '开启声音', '打开声音', '恢复语音', '可以说话了',
            '现在可以说话了', 'unmute', 'enable voice', 'turn on voice'].includes(command);
    }
    let messageCompositionActive = false;
    let closed = false;
    let connected = false;
    let connecting = false;
    function showConnection(state) {
        connected = state === 'ready';
        element('fieldset').disabled = false;
        messageInput.disabled = false;
        sendMessage.disabled = !connected;
        connectRetry.disabled = state === 'connecting' || connected || state === 'closed';
        connectRetry.hidden = connected;
        connectionStatus.dataset['connectionState'] = state;
        connectionStatus.textContent = {
            connecting: '正在连接本地服务。可以先写草稿，连接后才能发送。',
            ready: '已连接，可以发送。',
            failed: '连接未成功。草稿仍保留；处理下面的问题后点击重试连接。',
            closed: '会话已关闭。草稿仍保留在当前页面。',
        }[state];
        if (!connected)
            showTurn(state === 'connecting' ? '正在连接，可以先写草稿。' : state === 'closed' ? '本次会话已结束。' : '等待重新连接，草稿仍在。', state);
        for (const button of document.querySelectorAll('[data-command]'))
            button.disabled = !connected;
        if (!connected) {
            ptt.disabled = true;
            rehearsalButton.disabled = true;
            continuousButton.disabled = true;
            continuousSend.disabled = true;
            continuousInterrupt.disabled = true;
        }
    }
    let reviewPanel = null;
    const api = new MiraApiClient(config);
    messageInput.addEventListener('input', () => {
        messageRevision++;
        if (recoveredDraft) {
            if (messageInput.value === '')
                recoveredDraft = null;
            else
                recoveredDraft = { ...recoveredDraft, edited: true };
            renderRecoveredDraft();
        }
    });
    messageInput.addEventListener('compositionstart', () => { messageCompositionActive = true; });
    messageInput.addEventListener('compositionend', () => { messageCompositionActive = false; });
    messageInput.addEventListener('keydown', event => {
        if (event.key === 'Enter' && (messageCompositionActive || event.isComposing || event.keyCode === 229)) {
            event.preventDefault();
            return;
        }
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            element('form.composer').requestSubmit();
        }
    });
    function restoreNotSent(outcome, revision, expectedText) {
        if (outcome?.status !== 'not-sent' || typeof outcome.text !== 'string'
            || messageRevision !== revision || messageInput.value !== '')
            return false;
        if (expectedText !== undefined && outcome.text !== expectedText)
            return false;
        messageInput.value = outcome.text;
        return true;
    }
    function defaultVoiceHint() {
        if (!microphoneAvailable)
            return '麦克风识别未配置或浏览器不支持。可以继续用文字。';
        return continuousAvailable
            ? '点击开始自然对话，麦克风会持续聆听，包括安静时段。说完后自动发送；转写区发送后继续聆听，达到上限会停止。可随时打断回应继续说；文字框发送会先停止聆听。'
            : '按住说话是备用输入方式，松开后等待可靠转写。停止会立即释放麦克风。';
    }
    const sceneExecutor = new SceneEffectExecutor(stage, {
        chapter: {
            isOfferCurrent: effect => controller.isChapterOfferCurrent(effect),
            onChoice: ({ effect, choice }) => {
                if (!connected || closed || !controller.isChapterOfferCurrent(effect))
                    return;
                submissionGeneration++;
                held = null;
                rehearsalHeld = null;
                const gestureFence = gestureReviewFence;
                gestureReviewFence = null;
                gestureFence?.();
                const rehearsalFence = rehearsalReviewFence;
                rehearsalReviewFence = null;
                rehearsalFence?.();
                const reviewFence = reviewPanel?.invalidateForNewInput();
                // Continuous stop releases local capture immediately. The controller validates
                // and consumes this exact offer synchronously before its normal input awaits.
                void continuous?.stop('user_stop');
                showTurn('正在回应 MIRA…', 'pending');
                void controller.chooseChapterGift(effect, choice).finally(() => reviewFence?.());
            },
        },
        generatedImage: { fetchBytes: (effect, signal) => api.generatedImage(effect, signal) },
        characterRendererMode: document.body?.dataset['characterRenderer'] === 'code-native-review'
            ? 'code-native-review' : 'static-pixi',
    });
    const fixedPhotoRegion = document.querySelector('[data-fixed-photo-status]');
    const fixedPhotoMessage = document.querySelector('[data-fixed-photo-message]');
    const fixedPhotoDismiss = document.querySelector('[data-fixed-photo-dismiss]');
    const storyImageRegion = document.querySelector('[data-story-image-status]');
    const storyImageMessage = document.querySelector('[data-story-image-message]');
    const storyImageDismiss = document.querySelector('[data-story-image-dismiss]');
    const controller = new SessionController(api, sceneExecutor, {
        connected() {
            if (closed)
                return;
            showConnection('ready');
            reviewPanel?.start();
        },
        inputAccepted(text, requestId) { appendConversation('user', text, `input:${requestId}`); },
        visualPresented(effect) {
            appendPresentedSubtitle(effect);
        },
        fixedPhotoStatus(message, dismissible) {
            if (fixedPhotoRegion)
                fixedPhotoRegion.hidden = message === null;
            if (fixedPhotoMessage)
                fixedPhotoMessage.textContent = message ?? '';
            if (fixedPhotoDismiss)
                fixedPhotoDismiss.hidden = !dismissible;
        },
        storyImageStatus(message, dismissible) {
            if (storyImageRegion)
                storyImageRegion.hidden = message === null;
            if (storyImageMessage)
                storyImageMessage.textContent = message ?? '';
            if (storyImageDismiss)
                storyImageDismiss.hidden = !dismissible;
        },
        update(view, local) {
            if (conversationHistoryNote && (view.retired_user_inputs ?? 0) > 0) {
                conversationHistoryNote.textContent = `当前会话使用近期上下文，较早的 ${view.retired_user_inputs} 条输入已移出运行内存；这不是完整历史回忆。本页最多显示最近 80 条消息，档案保存状态请另行核对。`;
            }
            status.textContent = view.phase;
            const phases = { idle: '可以继续聊。', thinking: 'MIRA 正在想一想…', ready: '正在呈现已获准的内容。', stopped: '回应已停止，已显示的内容保留。', error: '这次回应遇到了问题，请查看提示。' };
            if (local?.expectedReplyInterruption) {
                status.textContent = continuous?.microphoneActive ? 'listening' : 'stopped';
                showTurn(continuous?.microphoneActive ? '已打断回应，正在继续听你说。' : '回应已停止，已显示的内容保留。', 'stopped');
            }
            else if (view.last_error === 'review_uncertain')
                showTurn('有一项内容暂未呈现，请查看系统提示。', 'held');
            else
                showTurn(phases[view.phase], view.phase);
            diagnostic.textContent = JSON.stringify({
                state: view.revision, activity: view.activity_seq, output: view.output_epoch,
                permit: view.permit_revision, grants: view.active_grants.length,
                presented: view.presented_effects.length, audioFacts: view.audio_progress.length, sealed: view.sealed,
            }, null, 2);
            if (local?.expectedReplyInterruption)
                error.textContent = '';
            else if (view.last_error === 'review_uncertain')
                error.textContent = systemNoticeFallback ?? '';
            else if (view.last_error)
                error.textContent = safeSessionError(view.last_error, view.last_error_diagnostic_id);
        },
        error(message) { error.textContent = message; if (message)
            showTurn('这次操作遇到了问题，请查看提示。', 'error'); },
        systemNotice(notice) {
            if (!systemNoticeRegion || !systemNoticeBody) {
                // Older or partial markup still needs a visible response on every poll.
                systemNoticeFallback = notice?.body ?? null;
                error.textContent = systemNoticeFallback ?? '';
                return;
            }
            if (notice)
                showTurn('有一项内容暂未呈现，请查看系统提示。', 'held');
            systemNoticeRegion.hidden = notice === null;
            systemNoticeBody.textContent = notice?.body ?? '';
        },
        localStop() { status.textContent = 'stopped · 本地已制止'; showTurn('已停止回应并释放麦克风；已显示内容保留。', 'stopped'); },
        outputPreference(muted, mode, pending) {
            if (responseMute) {
                responseMute.disabled = closed || pending || privateHttpText;
                responseMute.textContent = privateHttpText ? '局域网文字模式' : muted ? '开启回应声音' : '静音回应';
                responseMute.setAttribute('aria-pressed', String(muted));
            }
            if (responseVoiceStatus)
                responseVoiceStatus.textContent = privateHttpText
                    ? '局域网 HTTP 仅支持文字；本机或可信 HTTPS 可用语音。' : muted
                    ? '回应已静音，只显示文字。麦克风仍可继续聆听。'
                    : mode === 'text_only' ? '本轮只显示文字；开启声音从下一轮生效。' : '回应声音已开启（需服务可用）。';
        },
        capabilities(value) {
            if (closed)
                return;
            microphoneAvailable = value.microphone_enabled && typeof navigator.mediaDevices?.getUserMedia === 'function'
                && typeof globalThis.AudioContext === 'function' && typeof globalThis.AudioWorkletNode === 'function' && globalThis.isSecureContext;
            const continuousCapability = value.continuous_listening_enabled === true;
            continuousAvailable = microphoneAvailable && continuousCapability && value.generation_mode !== 'rehearsal';
            continuousButton.hidden = !continuousAvailable;
            continuousPanel.hidden = !continuousAvailable;
            ptt.disabled = !microphoneAvailable || Boolean(continuous?.active);
            const modes = { mock: 'Mock · 固定场景', replay: 'Fixture · 生成夹具回放', rehearsal: 'OFFLINE · 离线排练', injected: '注入后端 · 尚未验收' };
            element('[data-mode-label]').textContent = modes[value.generation_mode];
            rehearsalAvailable = value.generation_mode === 'rehearsal' && value.qualification === 'offline_fixture';
            reviewCanEnable = value.generation_mode === 'injected' && (value.microphone_enabled || value.speech_enabled);
            reviewPanel?.setCanEnable(reviewCanEnable);
            element('[data-rehearsal-banner]').hidden = !rehearsalAvailable;
            element('[data-rehearsal-controls]').hidden = !rehearsalAvailable;
            element('[data-code-mock-controls]').hidden = !(value.generation_mode === 'mock'
                && document.body?.dataset['characterRenderer'] === 'code-native-review');
            rehearsalButton.disabled = !rehearsalAvailable;
            element('[data-mode-description]').textContent = rehearsalAvailable
                ? 'OFFLINE 离线排练：固定口令、预先制作的英文合成音频与双语字幕。没有调用真实模型或 Google 服务；不识别自由对话，不采集麦克风。插画为原创本地矢量素材。字幕按整句语音 cue 呈现，不是逐字对齐，也不能证明用户听见。'
                : `${modes[value.generation_mode]}。${value.qualification === 'unavailable'
                    ? '真实语音尚未配置，当前使用文字。' : '语音后端已注入；账户、扬声器、麦克风与真实打断仍需单独验收。'}角色与旅行插画是本地原创素材，不代表实时生图。字幕显示不代表已经听见或逐字对齐。`;
            voiceHint.textContent = defaultVoiceHint();
            // Capability discovery occurs after the initial disabled listening view.
            // Recompute the same view; do not require a click to enable the first click.
            if (lastContinuousView !== null)
                renderContinuous(lastContinuousView);
            else
                continuousButton.disabled = !continuousAvailable || closed
                    || controller.microphoneBusy || reviewPanel?.recordingActive === true;
        },
        rehearsalInput(state) {
            rehearsalButton.setAttribute('aria-pressed', String(state === 'listening'));
            if (state === 'stopped')
                rehearsalHeld = null;
            rehearsalHint.textContent = state === 'listening'
                ? '正在演练 listening 状态，没有录音或识别。松开只会发送固定口令「照片里有什么」。'
                : '合成输入演练：按住观察 listening；松开发送固定口令「照片里有什么」。不打开麦克风。';
        },
        microphone(state) {
            ptt.setAttribute('aria-pressed', String(state === 'recording' || state === 'starting'));
            voiceHint.textContent = state === 'starting' ? '正在打开麦克风；请在浏览器中自行决定是否授权。'
                : state === 'recording' ? '正在听。识别内容会显示为未发送的用户输入预览；松开后才等待最终转写。'
                    : state === 'finishing' ? '录音已停止，正在等待可靠的最终转写…' : defaultVoiceHint();
        },
        microphonePreview(revision) {
            if (revision === null) {
                microphonePreview.textContent = '';
                microphonePreview.hidden = true;
                return;
            }
            const qualifier = revision.is_final ? '（片段已定稿，整轮仍未完成）' : '（仍在变化）';
            microphonePreview.textContent = `用户输入临时预览${qualifier}，未发送：${revision.text.slice(0, 2000)}`;
            microphonePreview.hidden = false;
        },
        microphoneTiming(value) {
            if (value === null) {
                microphoneTiming.textContent = '';
                microphoneTimingPanel.hidden = true;
                return;
            }
            // This surface contains only an ephemeral stream ID, numeric stage deltas and counts.
            microphoneTiming.textContent = JSON.stringify(value, null, 2);
            microphoneTimingPanel.hidden = false;
        },
        reviewAudition(state) { reviewPanel?.auditionState(state); },
    }, config, {
        onGlobalStop() { submissionGeneration++; void continuous?.stop('user_stop'); },
        externalMicrophoneActive: () => continuous?.microphoneActive === true,
        waitForReplyQuiet: signal => continuous?.waitForReplyQuiet(signal) ?? Promise.resolve(true),
        userInputPending: () => document.hidden || !!messageInput.value.trim() || continuous?.backgroundOutputBusy === true,
    });
    reviewPanel = new ReviewedAudioPanel(api, controller, {
        notice: element('[data-review-audio-notice]'),
        status: element('[data-review-audio-status]'),
        scope: element('[data-review-audio-scope]'),
        eligibilityNotice: element('[data-review-audio-eligibility]'),
        consent: element('[data-review-audio-consent]'),
        enable: element('[data-review-audio-enable]'),
        disable: element('[data-review-audio-disable]'),
        review: element('[data-review-audio-review]'),
        clip: element('[data-review-audio-clip]'),
        clipMetadata: element('[data-review-audio-clip-metadata]'),
        preview: element('[data-review-audio-preview]'),
        audition: element('[data-review-audio-audition]'),
        auditionStatus: element('[data-review-audio-audition-status]'),
        attestation: element('[data-review-audio-attestation]'),
        confirm: element('[data-review-audio-confirm]'),
        cancel: element('[data-review-audio-cancel]'),
        result: element('[data-review-audio-result]'),
    });
    reviewPanel.setCanEnable(false);
    function renderContinuous(view) {
        lastContinuousView = view;
        const active = view.state === 'starting' || view.state === 'listening' || view.state === 'stopping';
        continuousButton.setAttribute('aria-pressed', String(active));
        continuousButton.textContent = active ? '停止自然对话' : '点击开始自然对话';
        const startsExhausted = view.ready !== null
            && ((view.ready.max_streams_per_session !== null && view.ready.session_lease_starts_used >= view.ready.max_streams_per_session)
                || (view.ready.max_total_streams !== null && view.ready.total_lease_starts_used >= view.ready.max_total_streams));
        const previousPreviews = view.previous_previews ?? [];
        const previousPreviewsFull = previousPreviews.length >= (view.previous_preview_limit ?? 4);
        const heldPreviewsFull = (view.held_previews?.length ?? 0) >= (view.held_preview_limit ?? 12);
        continuousButton.disabled = closed || view.state === 'closed' || !continuousAvailable || view.state === 'stopping'
            || (!active && (controller.microphoneBusy || reviewPanel?.recordingActive === true || startsExhausted || view.service_budget_exhausted || view.pending_text_capacity || previousPreviewsFull || heldPreviewsFull));
        ptt.disabled = closed || view.state === 'closed' || !microphoneAvailable || active || controller.microphoneBusy;
        continuousPanel.hidden = !continuousAvailable;
        continuousInterrupt.hidden = !active;
        continuousInterrupt.disabled = closed || !active || view.state === 'stopping';
        continuousInterrupt.textContent = view.barge_in_suspended
            ? '恢复语音插话，继续听我说' : '打断回应，继续听我说';
        if (continuousBargeMode) {
            continuousBargeMode.disabled = closed || !continuousAvailable || active;
            continuousBargeMode.value = active ? view.barge_in_mode ?? selectedBargeMode : selectedBargeMode;
        }
        if (captureProcessing) {
            const processing = view.capture_processing;
            const flag = (value) => value === true ? '是' : value === false ? '否' : '未知';
            captureProcessing.textContent = processing
                ? `浏览器回声处理：已请求；支持：${flag(processing.echoCancellationSupported)}；报告开启：${flag(processing.echoCancellationReported)}。这不证明回声已消除。`
                : '浏览器尚未报告回声处理状态。';
            if (active && view.barge_in_mode === 'headphones' && !view.barge_in_available) {
                captureProcessing.textContent += ' 本次自动插话不可用，可点击打断按钮。';
            }
        }
        continuousRecordingLimit.hidden = !active;
        continuousReviewBlock.hidden = !active;
        reviewPanel?.setContinuousListeningBlocked(active);
        const stateText = {
            idle: '连续聆听尚未开始。',
            starting: '正在请求麦克风并建立连续聆听；点击停止会立即释放麦克风。',
            listening: view.natural_enabled ? '自然对话已开启。说完后会自动发送；需要时可手动发送，或打断回应继续说话。'
                : '正在聆听。当前使用手动发送备用模式；安静时段仍会持续采集。',
            stopping: '正在关闭本条聆听；麦克风已先行释放。',
            stopped: '连续聆听已停止。已收到的文字仍保留，可继续核对。',
            limit: '本条连续聆听已到达声明上限。不会自动续开；继续前请再次点击开始。',
            error: view.error ?? '连续聆听遇到问题；麦克风已释放。',
            closed: '会话已关闭；未发送文字仍保留在当前页面。',
        };
        const ready = view.ready;
        const finiteLimits = ready === null ? [] : [
            ready.max_seconds === null ? '' : `本次聆听上限 ${ready.max_seconds} 秒`,
            ready.max_utterances === null ? '' : `本次最多发送 ${ready.max_utterances} 条`,
            ready.max_streams_per_session === null ? '' : `会话启动 ${ready.session_lease_starts_used}/${ready.max_streams_per_session}`,
            ready.max_total_streams === null ? '' : `服务启动 ${ready.total_lease_starts_used}/${ready.max_total_streams}`,
        ].filter(Boolean);
        const readyText = finiteLimits.length ? `已配置：${finiteLimits.join('，')}。` : '';
        const endpointText = view.ready?.client_endpoint_supported
            ? `本地音量启发式：约 ${view.ready.client_silence_ms ?? 700} 毫秒安静后整理转写并自动发送，回复只在开始前等待安静。语音插话按本次设置运行；噪声或扬声器回声可能误触发，必要时可关闭语音插话。`
            : view.ready?.endpoint_mode === 'unavailable_manual'
                ? '自动语句端点不可用；仅显示转写，手动发送仍需服务端确认。' : '';
        const phases = { listening: '正在聆听', transcribing: '正在识别', ready: '准备发送',
            sending: '正在发送', sent: '已发送，继续聆听', manual_review: '需要核对，可手动发送' };
        const phaseText = view.state === 'listening' ? phases[view.conversation_phase] : '';
        const recognition = view.recognition_status;
        const recognitionStates = { opening: '正在衔接识别，麦克风继续聆听。', listening: '麦克风正在聆听。',
            draining: '正在整理刚才的话，麦克风继续聆听。', awaiting_commit: '这一段识别已就绪，麦克风继续聆听。',
            completed: '这一段识别已结束。', limit: '识别已达到本次声明上限。' };
        const finiteRecognition = ready?.max_recognition_streams;
        const remainingStt = recognition?.stt_requests_remaining ?? ready?.stt_requests_remaining;
        const recognitionText = [
            active && recognition ? recognitionStates[recognition.state] : '',
            active && recognition && typeof finiteRecognition === 'number' ? `本次识别 ${recognition.stream_index}/${finiteRecognition}。` : '',
            typeof remainingStt === 'number' ? `已配置的 STT 额度最近回报剩余 ${remainingStt} 次。` : '',
        ].filter(Boolean).join(' ');
        const bargePauseText = view.barge_in_suspended
            ? '短时间内连续触发，自动插话已暂停；可点击恢复语音插话。麦克风仍在聆听，原有重叠文字仍需核对。' : '';
        const retentionText = view.retired_sent_text > 0 ? `较早 ${view.retired_sent_text} 条已提交语音记录已移出本页；待核对文字仍保留。` : '';
        continuousStatus.textContent = [retentionText, phaseText, stateText[view.state], recognitionText, readyText, endpointText, bargePauseText, view.notice, view.error]
            .filter(Boolean).join(' ');
        const transcript = view.transcript?.lease_id === view.lease_id ? view.transcript : null;
        continuousPreview.hidden = transcript === null;
        continuousPreview.textContent = transcript === null ? '' :
            `${transcript.auto_ready ? '准备发送' : view.natural_enabled && !transcript.review_required ? '正在识别' : transcript.endpoint_pending ? '待核对' : transcript.is_final ? '稳定片段' : '临时转写'} · 修订 ${transcript.revision} · 识别文字：${transcript.text}${transcript.truncated ? '（仅显示前 2,000 字符，此内容不可直接发送）' : ''}${transcript.hint ? ` ${transcript.hint}` : ''}`;
        continuousSend.textContent = '手动发送当前稳定文字（备用）';
        continuousSend.disabled = closed || !continuousAvailable || view.state !== 'listening' || transcript?.can_send !== true;
        if (previousPreviewsFull && !active) {
            continuousStatus.textContent += ' 历史预览已满；先把一段放入空文字框并核对，释放空间后才能再次开始。';
        }
        continuousSentText.replaceChildren();
        continuousSentText.setAttribute('aria-label', '上次未发送预览、发送记录与同一句更正');
        for (const preview of view.held_previews ?? []) {
            const li = document.createElement('li'), label = document.createElement('span');
            label.textContent = `暂缓的语音预览（可能已另行手动发送，请对照发送记录核对）：${preview.text}`;
            const restore = document.createElement('button');
            restore.type = 'button';
            restore.textContent = '放入空文字框（核对后手动发送）';
            restore.addEventListener('click', () => {
                if (messageInput.value !== '') {
                    error.textContent = '文字输入框已有内容，未覆盖；请先核对后再决定。';
                    messageInput.focus();
                    return;
                }
                const restored = preview.utterance_id ? continuous?.restoreHeldInput(preview.lease_id, preview.utterance_id, preview.revision) : null;
                if (restored === null || restored === undefined)
                    return;
                recoveredDraft = { target: restored.continuationTarget, edited: false };
                renderRecoveredDraft();
                messageInput.value = restored.text;
                messageRevision++;
                messageInput.focus();
            });
            li.append(label, restore);
            continuousSentText.append(li);
        }
        for (const preview of previousPreviews) {
            const li = document.createElement('li');
            const label = document.createElement('span');
            const kind = preview.endpoint_pending ? '句末未对齐' : preview.is_final ? '稳定转写' : '临时转写';
            label.textContent = `上次聆听预览 · ${kind} · 修订 ${preview.revision} · 请核对（可能与下方已确认文字重叠，不会自动发送）：${preview.text}${preview.truncated ? '（仅显示前 2,000 字符）' : ''}`;
            const restore = document.createElement('button');
            restore.type = 'button';
            restore.textContent = '放入空文字框（仍需核对和手动发送）';
            restore.addEventListener('click', () => {
                if (messageInput.value !== '') {
                    error.textContent = '文字输入框已有内容，未覆盖；请先核对后再决定。';
                    messageInput.focus();
                    return;
                }
                const restored = continuous?.restorePreviousPreview(preview.lease_id);
                if (restored === null || restored === undefined) {
                    error.textContent = '这段预览已不在保留列表中，请核对页面当前文字。';
                    return;
                }
                messageInput.value = restored;
                messageRevision++;
                messageInput.focus();
            });
            li.append(label, restore);
            continuousSentText.append(li);
        }
        for (const item of view.sent_text) {
            const li = document.createElement('li');
            const label = document.createElement('span');
            const states = { sending: '正在提交', sent: '已提交', not_sent: '未送出', unknown: '结果不确定' };
            label.textContent = `${states[item.state]} · 已确定文字：${item.text}${item.notice ? ` · ${item.notice}` : ''}`;
            li.append(label);
            if (item.correction) {
                const correction = document.createElement('span');
                correction.textContent = ` · 同一句的后续更正（修订 ${item.correction.revision}，需核对，未自动重发）：${item.correction.text}`;
                li.append(correction);
                const restoreCorrection = document.createElement('button');
                restoreCorrection.type = 'button';
                restoreCorrection.textContent = '更正放入空文字框（核对后手动发送）';
                restoreCorrection.addEventListener('click', () => {
                    if (messageInput.value !== '') {
                        error.textContent = '文字输入框已有内容，未覆盖；请先核对后再决定。';
                        messageInput.focus();
                        return;
                    }
                    const restored = continuous?.restoreSentText(item.commit_id, true);
                    if (restored == null)
                        return;
                    messageInput.value = restored;
                    messageRevision++;
                    messageInput.focus();
                });
                li.append(restoreCorrection);
            }
            if (item.state === 'not_sent' || item.state === 'unknown') {
                const restore = document.createElement('button');
                restore.type = 'button';
                restore.textContent = item.state === 'unknown'
                    ? '已核对会话，放入空文字框' : '放入文字框（仍需手动发送）';
                restore.addEventListener('click', () => {
                    if (messageInput.value !== '') {
                        error.textContent = '文字输入框已有内容，未覆盖；请先核对后再决定。';
                        messageInput.focus();
                        return;
                    }
                    const restored = continuous?.restoreSentText(item.commit_id);
                    if (restored == null)
                        return;
                    messageInput.value = restored;
                    messageRevision++;
                    messageInput.focus();
                });
                li.append(restore);
            }
            continuousSentText.append(li);
        }
    }
    continuous = new ContinuousListeningController({
        bargeInMode: () => selectedBargeMode,
        mode: 'natural',
        openStream: (leaseId, signal, observers, mode) => api.continuousListening(leaseId, signal, observers, mode),
        submitInput: (text, listeningUtteranceId, continuationTarget) => {
            submissionGeneration++;
            return controller.input(text, undefined, listeningUtteranceId, continuationTarget);
        },
        canStart: () => continuousAvailable && microphoneAvailable && !controller.microphoneBusy
            && reviewPanel?.recordingActive !== true && !closed,
        interruptReply: () => controller.interruptReply(),
        prepareInputFromGesture: () => controller.prepareInputFromGesture(),
        isPlaybackBusy: () => controller.replyPcmBusy,
        captureReplyContinuation: () => controller.captureReplyContinuation(),
        isInterruptedReplyCurrent: target => controller.isInterruptedReplyCurrent(target),
        isReplyContinuationCurrent: target => controller.isReplyContinuationCurrent(target),
        onPhase: listening => controller.setContinuousListeningPhase(listening),
        onUpdate: renderContinuous,
    });
    continuousButton.addEventListener('click', () => {
        if (!continuous)
            return;
        error.textContent = '';
        if (continuous.active)
            void continuous.stop('user_stop');
        else
            continuous.start();
    });
    continuousSend.addEventListener('click', () => { submissionGeneration++; void continuous?.sendCurrent(); });
    continuousInterrupt.addEventListener('click', () => {
        submissionGeneration++;
        // This remains a reply-only manual interrupt even when automatic interruption is paused.
        if (controller.interruptReply() && lastContinuousView?.barge_in_suspended)
            continuous?.resumeAutomaticInterruption();
    });
    continuousBargeMode?.addEventListener('change', () => {
        // Changing mode never opens a microphone or changes the active lease in place.
        if (continuous?.active)
            void continuous.stop('user_stop');
    });
    function releaseGesture(cancel) {
        if (held === null)
            return;
        held = null;
        const settleFence = gestureReviewFence;
        gestureReviewFence = null;
        if (cancel) {
            void controller.stop().finally(() => settleFence?.());
        }
        else {
            const revision = gestureInputRevision;
            void controller.finishMicrophone().then(outcome => restoreNotSent(outcome, revision))
                .finally(() => settleFence?.());
        }
    }
    function startGesture(identity) {
        if (closed || ptt.disabled || held !== null || rehearsalHeld !== null)
            return;
        submissionGeneration++;
        gestureInputRevision = ++messageRevision;
        gestureReviewFence = reviewPanel?.invalidateForNewInput() ?? null;
        held = identity;
        error.textContent = '';
        void controller.startMicrophone();
    }
    ptt.addEventListener('pointerdown', event => {
        if (event.button !== 0)
            return;
        event.preventDefault();
        startGesture(`pointer:${event.pointerId}`);
        try {
            ptt.setPointerCapture(event.pointerId);
        }
        catch { /* Window pointerup still releases capture. */ }
    });
    const pointerUp = (event) => {
        if (held === `pointer:${event.pointerId}`)
            releaseGesture(false);
    };
    ptt.addEventListener('pointerup', pointerUp);
    window.addEventListener('pointerup', pointerUp);
    ptt.addEventListener('pointercancel', () => releaseGesture(true));
    ptt.addEventListener('lostpointercapture', () => releaseGesture(true));
    ptt.addEventListener('keydown', event => {
        if (event.key !== ' ' && event.key !== 'Enter')
            return;
        event.preventDefault();
        if (!event.repeat)
            startGesture(`key:${event.key}`);
    });
    ptt.addEventListener('keyup', event => {
        if (event.key !== ' ' && event.key !== 'Enter')
            return;
        event.preventDefault();
        if (held === `key:${event.key}`)
            releaseGesture(false);
    });
    // Assistive-technology activation can use a start/finish toggle without pointer events.
    ptt.addEventListener('click', event => {
        if (event.detail !== 0)
            return;
        if (held === 'accessible')
            releaseGesture(false);
        else if (held === null)
            startGesture('accessible');
    });
    function releaseRehearsal(cancel) {
        if (rehearsalHeld === null)
            return;
        rehearsalHeld = null;
        const settleFence = rehearsalReviewFence;
        rehearsalReviewFence = null;
        if (cancel) {
            void controller.stop().finally(() => settleFence?.());
        }
        else {
            const revision = rehearsalInputRevision;
            void controller.finishRehearsalInput().then(outcome => restoreNotSent(outcome, revision))
                .finally(() => settleFence?.());
        }
    }
    function startRehearsal(identity) {
        if (closed || !rehearsalAvailable || rehearsalButton.disabled || held !== null || rehearsalHeld !== null)
            return;
        submissionGeneration++;
        rehearsalInputRevision = ++messageRevision;
        rehearsalReviewFence = reviewPanel?.invalidateForNewInput() ?? null;
        error.textContent = '';
        void controller.startRehearsalInput();
        rehearsalHeld = identity;
    }
    rehearsalButton.addEventListener('pointerdown', event => {
        if (event.button !== 0)
            return;
        event.preventDefault();
        startRehearsal(`pointer:${event.pointerId}`);
        try {
            rehearsalButton.setPointerCapture(event.pointerId);
        }
        catch { /* Window release is also observed. */ }
    });
    const rehearsalPointerUp = (event) => {
        if (rehearsalHeld === `pointer:${event.pointerId}`)
            releaseRehearsal(false);
    };
    rehearsalButton.addEventListener('pointerup', rehearsalPointerUp);
    window.addEventListener('pointerup', rehearsalPointerUp);
    rehearsalButton.addEventListener('pointercancel', () => releaseRehearsal(true));
    rehearsalButton.addEventListener('lostpointercapture', () => releaseRehearsal(true));
    rehearsalButton.addEventListener('keydown', event => {
        if (event.key !== ' ' && event.key !== 'Enter')
            return;
        event.preventDefault();
        if (!event.repeat)
            startRehearsal(`key:${event.key}`);
    });
    rehearsalButton.addEventListener('keyup', event => {
        if (event.key !== ' ' && event.key !== 'Enter')
            return;
        event.preventDefault();
        if (rehearsalHeld === `key:${event.key}`)
            releaseRehearsal(false);
    });
    rehearsalButton.addEventListener('click', event => {
        if (event.detail !== 0)
            return;
        if (rehearsalHeld === 'accessible')
            releaseRehearsal(false);
        else if (rehearsalHeld === null)
            startRehearsal('accessible');
    });
    window.addEventListener('blur', () => releaseRehearsal(true));
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden')
        releaseRehearsal(true); });
    window.addEventListener('blur', () => { releaseGesture(true); void continuous?.stop('user_stop'); });
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') {
            releaseGesture(true);
            void continuous?.stop('user_stop');
        }
    });
    element('form.composer').addEventListener('submit', event => {
        event.preventDefault();
        if (!connected || closed)
            return;
        const text = messageInput.value;
        if (!text.trim())
            return;
        const recovery = recoveredDraft;
        if (recovery && !recovery.target) {
            renderRecoveredDraft();
            return;
        }
        if (!controller.prepareInputFromGesture())
            return;
        const gestureFence = gestureReviewFence;
        gestureReviewFence = null;
        gestureFence?.();
        const rehearsalFence = rehearsalReviewFence;
        rehearsalReviewFence = null;
        rehearsalFence?.();
        const reviewFence = reviewPanel?.invalidateForNewInput();
        error.textContent = '';
        held = null;
        rehearsalHeld = null;
        const revision = ++messageRevision;
        const submission = ++submissionGeneration;
        const muteGeneration = outputMuteGeneration;
        messageInput.value = '';
        recoveredDraft = null;
        renderRecoveredDraft();
        showTurn('正在提交你的消息…', 'pending');
        const restoreSubmission = (outcome) => {
            if (restoreNotSent(outcome, revision, text) && recovery) {
                recoveredDraft = recovery;
                renderRecoveredDraft();
            }
        };
        void (async () => {
            if (continuous?.active)
                await continuous.stop('user_stop');
            if (closed || !connected || submission !== submissionGeneration) {
                restoreSubmission({ status: 'not-sent', text });
                return;
            }
            if (explicitlyEnablesVoice(text) && muteGeneration !== outputMuteGeneration) {
                restoreSubmission({ status: 'not-sent', text });
                showTurn('已保持静音。较早的开启声音请求未发送；可核对草稿后重新发送。', 'held');
                return;
            }
            const outcome = await controller.input(text, undefined, undefined, recovery?.target ?? undefined);
            restoreSubmission(outcome);
        })().finally(() => reviewFence?.());
    });
    responseMute?.addEventListener('click', () => {
        const muted = !controller.outputMuted;
        if (muted)
            outputMuteGeneration++;
        void controller.setOutputMuted(muted);
    });
    document.querySelector('[data-photo-close]')?.addEventListener('click', () => {
        void controller.dismissPhoto();
    });
    document.querySelector('[data-fixed-photo-dismiss]')?.addEventListener('click', () => {
        void controller.dismissPhoto('fixed_photo');
    });
    document.querySelector('[data-story-image-dismiss]')?.addEventListener('click', () => {
        void controller.dismissStoryImage();
    });
    element('[data-stop]').addEventListener('click', () => {
        submissionGeneration++;
        held = null;
        rehearsalHeld = null;
        const gestureFence = gestureReviewFence;
        gestureReviewFence = null;
        gestureFence?.();
        const rehearsalFence = rehearsalReviewFence;
        rehearsalReviewFence = null;
        rehearsalFence?.();
        const reviewFence = reviewPanel?.invalidateForStop();
        const stopping = controller.stop();
        memoryManagement?.stop();
        conversationArchive?.stop();
        void stopping.finally(() => reviewFence?.());
    });
    for (const button of document.querySelectorAll('[data-command]')) {
        button.addEventListener('click', () => {
            if (!connected || closed)
                return;
            if (!controller.prepareInputFromGesture())
                return;
            error.textContent = '';
            held = null;
            rehearsalHeld = null;
            messageRevision++;
            const submission = ++submissionGeneration;
            const muteGeneration = outputMuteGeneration;
            const text = button.dataset.command ?? '';
            const revision = messageRevision;
            const gestureFence = gestureReviewFence;
            gestureReviewFence = null;
            gestureFence?.();
            const rehearsalFence = rehearsalReviewFence;
            rehearsalReviewFence = null;
            rehearsalFence?.();
            const reviewFence = reviewPanel?.invalidateForNewInput();
            void (async () => {
                if (continuous?.active)
                    await continuous.stop('user_stop');
                if (closed || !connected || submission !== submissionGeneration)
                    return;
                if (explicitlyEnablesVoice(text) && muteGeneration !== outputMuteGeneration) {
                    restoreNotSent({ status: 'not-sent', text }, revision, text);
                    showTurn('已保持静音。较早的开启声音请求未发送；可核对草稿后重新发送。', 'held');
                    return;
                }
                return controller.input(text);
            })().finally(() => reviewFence?.());
        });
    }
    const stopAndClose = async () => {
        if (closed)
            return;
        submissionGeneration++;
        conversationArchive?.close();
        conversationArchive = null;
        memoryManagement?.close();
        memoryManagement = null;
        const stopping = controller.stop();
        // Closing cancels dispatch, not a draft edit: known-undispatched text may still
        // return to the unchanged empty composer after microphone teardown settles.
        closed = true;
        held = null;
        rehearsalHeld = null;
        ptt.disabled = true;
        rehearsalButton.disabled = true;
        if (responseMute)
            responseMute.disabled = true;
        gestureReviewFence?.();
        gestureReviewFence = null;
        rehearsalReviewFence?.();
        rehearsalReviewFence = null;
        reviewPanel?.close();
        diagnosticsWatcher.close();
        showConnection('closed');
        await stopping;
        await continuous?.close();
        await controller.close();
        status.textContent = 'closed · 刷新可新建';
    };
    element('[data-close]').addEventListener('click', () => {
        if (operatorGate)
            void operatorGate.cancelAndRevoke();
        else
            void stopAndClose();
    });
    window.addEventListener('pagehide', () => {
        if (operatorGate)
            return;
        closed = true;
        held = null;
        rehearsalHeld = null;
        submissionGeneration++;
        gestureReviewFence?.();
        gestureReviewFence = null;
        rehearsalReviewFence?.();
        rehearsalReviewFence = null;
        reviewPanel?.close();
        diagnosticsWatcher.close();
        void continuous?.close();
        void controller.close();
    });
    function connectSession() {
        if (closed || connected || connecting)
            return;
        connecting = true;
        error.textContent = '';
        showConnection('connecting');
        void controller.connect().catch(problem => {
            if (closed)
                return;
            showConnection('failed');
            error.textContent = problem instanceof MiraHttpError
                ? problem.message : '连接失败。请确认开发服务已启动，再点重试连接；未启动任何语音。';
        }).finally(() => { connecting = false; });
    }
    connectRetry.addEventListener('click', connectSession);
    connectSession();
    return { stopAndClose };
}
if (document.body?.dataset['deviceAccess'] === 'trusted-private-network-no-pairing') {
    operatorGate = mountTrustedDeviceAccess(document, { onReady: startSessionApp });
}
else if (document.body?.dataset['operatorPairing'] === 'required') {
    operatorGate = mountOperatorPairing(document, { onPaired: startSessionApp });
}
else {
    startSessionApp();
}
