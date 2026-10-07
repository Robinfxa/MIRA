# Controlled provider evidence — 2026-10-04

These are fixed synthetic development checks, not a user conversation, physical audio test, or production-quality calibration. Each run used a fixed source and finite request budget. No credential, raw authentication header or personal conversation is included here. The default demo remains offline.

## Native text admission

One exact `gpt-6-luna` turn and four JEV HTTP 200 responses completed in **6.332 seconds**. The application reached `ready`, `sealed=true`, no last error, with subtitle and `look_at_rain` pose grants. The synthetic subtitle was “你好，我们一起听雨。” No presentation receipts or audio playback were submitted. The runtime had no environment/MCP/browser/computer/shell access. This proves the controlled backend generation/review path, not a visible browser conversation or quota ownership.

The versioned reported-confidence policy retains raw reported values and cross-field diagnostic warnings. Finite/range/key/maximum-choice/probability-sum checks, the original dual ≥0.6 thresholds, deterministic bans and other semantic checks remain active. This user-configured development policy has not been statistically calibrated for general Chinese conversation.

## Synthetic STT → generation → review

A prerecorded **4.66-second** English Flite input was converted deterministically to 16 kHz mono PCM and sent once to Speech-to-Text V2 `chirp_3`. The final 79-character transcript exactly matched the synthetic fixture. The 4.66 seconds is input duration, not recognition latency. Recorded monotonic times from probe start were dispatch 0.511 s and final transcript 5.846 s.

Native generation and four JEV HTTP 200 responses followed. Final review selected ALLOW for two checks but reported confidences of **0.58 and 0.55**, below the unchanged 0.6 threshold. The application correctly took the UNKNOWN fallback path; the probe ended after 13.751 s and reaped its owned model process. It made **no TTS request and no presentation/playback receipt**. This is successful partial integration plus expected uncertainty handling, not a normal fully approved natural voice exchange or a real microphone test.

## Fixed production TTS component

A separate, expressly bounded adapter check synthesized only “你好，这是一次语音连接测试。” through exact **`gemini-3.8-flash-tts` / Kore / global**, with no model generation, JEV, STT or Actor permit fabrication. It received HTTP 200, consumed all 52 PCM packets through the production parser, closed the provider iterator and saved a private WAV.

| Observation | Seconds from probe start |
|---|---:|
| HTTP dispatch | 0.464603 |
| Response headers | 1.695931 |
| First nonempty PCM yielded by production adapter | 1.738297 |
| Provider iterator complete | 2.964731 |
| WAV saved and completed | 2.966465 |

Dispatch to first PCM was **1.273694 seconds in this one run**. This is not first audible sound, browser enqueue/scheduling latency, an SLA, or a guarantee for later requests. Preflight/auth preparation is included in the start-relative times; the final time includes private file writing. No speaker playback occurred.

The complete result is 77,760 samples, 24 kHz mono signed 16-bit PCM, **3.24 seconds**, and a 155,564-byte standard WAV. PCM SHA-256: `0f79cec10571001f730d801ca13926c9923af7f805041455497eb2f3d0c5931e`; WAV SHA-256: `fdb45f96fd1299292d061167eda42be16f077efec2ccd443dc05199da6cd6e69`. The file is a fixed test utterance, not an admitted natural conversation reply.

## What remains

- Actual browser rendering, microphone/speaker behavior, mobile/Safari and a human-observed 3–5-minute recording.
- Continuous natural voice exchange reaching normal semantic approval and then audible presentation. Expected UNKNOWN fallback must remain usable rather than being silently forced to ALLOW.
- Representative semantic-quality calibration and repeatable latency measurements. The historical TTS run's 16.056-second saved-file total did not record first PCM, so it is not the same measurement as the latest 1.274-second first-PCM observation.

Use [current acceptance](CURRENT-ACCEPTANCE.md) and [the human recording plan](../development/DEMO-RECORDING.md). Never substitute these component checks for human perception.
