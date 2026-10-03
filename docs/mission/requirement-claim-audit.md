# Requirements and evidence-claim audit — 2026-10-03 12:56 UTC candidate

## Scope and conclusion

Read-only review of the frozen PDF-derived requirements, the 12:36 status overlay, README, AI_USAGE, DEMO-01 specification/verification, the archive-recovery report, and the immutable 12:56 release receipt. The original PDF/hash and 35 acceptance IDs remain authoritative; this audit does not change or waive them. No production source or tests were changed, and no tests, provider calls, browser/device checks, Git operations, or credential/secret scans were run for this audit.

The 12:56 receipt reports all 12 local release lanes passed (1,110 Python tests and 166 Node tests, per the release record). This is coherent offline software/package/loopback evidence, not product acceptance. DEMO-01 verification correctly limits its claim to a finite offline rehearsal using eight fixed synthetic English clips and a synthetic listening gesture that submits fixed text. The microphone capability remains false. The record explicitly says there was no provider call, browser/UI operation, actual speaker listening, mobile device, Chinese TTS/JEV quality test, or completed 3–5-minute recording.

Status meanings below: **partial** means relevant implementation or offline evidence exists but the stated acceptance outcome is not proven; **blocked** means a required real capability or prerequisite is unavailable; **not run** means no suitable evidence was found; **N/A** means the conditional branch was not selected. “Pass” is not inferred from code or automated tests.

## All 35 requirement IDs

| ID | Honest current status | Evidence boundary / remaining acceptance |
|---|---|---|
| PDF-01 | partial | Adult original character and authored scene exist; no continuous, recorded 3–5-minute interaction. |
| PDF-02 | partial | Scene/character UI exists in source and synthetic DOM evidence; current interactive browser/pixel review remains open. |
| PDF-03 | partial | Text and rehearsal controls exist; the rehearsal “listening” gesture stages a fixed text command and is not a working microphone input. |
| PDF-04 | not run | No current interactive desktop/mobile browser or real-phone acceptance. Static-render review is separate and does not substitute for device use. |
| PDF-05 | partial | Four-state/control behavior is represented and tested in software; human-observable rendered states are not accepted yet. |
| PDF-06 | partial | Text route and finite authored commands work in the controlled modes; free-form relevant multi-turn conversation is not established. |
| PDF-07 | blocked | No real microphone capture/recognition; the rehearsal gesture does not request permission or record. |
| PDF-08 | partial | Cue/audio linkage and fixed PCM delivery are software-tested; no evidence that a person heard actual playback or verified subtitle/audio timing on a device. |
| PDF-09 | partial | Finite scripted continuity is available; no real multi-round conversation or continuous 3–5-minute recording. |
| PDF-10 | blocked | Software interruption is tested, but no real speech input starts a new voice turn during actual audible character speech. |
| PDF-11 | partial | Local software cancellation is tested; actual audible stop timing is unobserved. |
| PDF-12 | partial | Stale generation/media/audio invalidation is tested with deterministic seams; no matching browser/device observation. |
| PDF-13 | partial | Queued software presentation/cancellation races are tested; physical/browser presentation behavior remains unobserved. |
| PDF-14 | partial | Synthetic listening state and fixed-text submission are tested; real listening-to-recognized-voice-turn recovery is absent. |
| PDF-15 | partial | Repeated cancellation/late-result software tests pass; actual browser/device stale-result behavior remains open. |
| PDF-16 | partial | The project uses explicit press-to-talk-style controls, but README does not explain why this choice fits mobile/scope; it must not imply true capture in rehearsal mode. |
| PDF-17 | partial | Structured effect/cue machinery is exercised by the authored rehearsal; current rendered user-visible effect acceptance remains open. |
| PDF-18 | partial | Three authored expressions exist in code; visible differentiation has not been checked in the current rendered UI. |
| PDF-19 | partial | Non-speech poses/actions exist in code; actual rendered differentiation has not been checked. |
| PDF-20 | partial | Rain/light environment changes are authored; current visual rendering is not accepted yet. |
| PDF-21 | partial | Authored commands/effects exercise input-linked behavior in software; a rendered relevant/irrelevant/delayed-input comparison remains open. |
| PDF-22 | partial | SVG/CSS character animation is the selected branch; source implementation is not evidence of perceived rendered motion. |
| PDF-23 | N/A | Video branch not selected. Do not manufacture video lifecycle “passes.” |
| PDF-24 | N/A | Runtime-generated media branch not selected. Do not manufacture generation lifecycle “passes.” |
| PDF-25 | blocked | No completed real model call. Codex backend authorization returned 401, so there was no Luna inference; Google ADC is pending; the first scored JEV case timed out, providing no quality result. |
| PDF-26 | partial | Provider-shaped timeout/401/403/429 and recovery behavior are software-tested; actual device permission/transport failure recovery has not been observed. |
| PDF-27 | partial | No-key mock/replay/rehearsal routes are documented and offline-verified with explicit labeling. Current browser usability remains unobserved; fixed rehearsal is not free-form dialogue. |
| PDF-28 | partial | Third-party/material notes exist. Archive-recovery contains a limited heuristic scan of the older published snapshot; this audit did not scan the current 12:56 tree, so no current-tree clean-scan claim is warranted. |
| PDF-D01 | partial | A published archive checkpoint was remotely verified/restored; it is not evidence that the expanded current Git tree, exact final release, and recording are one matching deliverable. |
| PDF-D02 | partial | README has a clear local-start route and archive startup worked with existing dependencies; exact current candidate review-environment startup is not independently demonstrated. |
| PDF-D03 | partial | A one-command startup is documented, but the clean dependency setup/time is untested. Archive recovery explicitly reused installed dependencies; do not claim a fresh setup under 15 minutes. |
| PDF-D04 | blocked | No 3–5-minute acceptance recording is reported or evidenced. The user-paced rehearsal guide and ~52.56 seconds of synthetic clips are not a recording. |
| PDF-D05 | partial | README covers modules, interaction, controls, services, sources and broad limitations. Missing explicit items: approximate actual effort/time spent, a two-week follow-on plan, and the reason for choosing press-to-talk. |
| PDF-D06 | documented | AI_USAGE identifies AI work, lists concrete AI defects and fixes, and says human independent product validation is not recorded. That is an honest disclosure, not evidence of human verification. |
| PDF-D07 | partial | Current limitations are disclosed, but README has no single current, actionable gaps/next-steps summary. The linked 12:36 overlay predates the completed 12:56 rehearsal. |

## Ten scenario statuses

| Scenario | Honest current status | What the evidence does and does not establish |
|---|---|---|
| A01 no-key startup/interface | partial | Mock/replay/rehearsal startup and loopback/package paths are offline-tested; interactive current browser, phone and pixel acceptance remain open. |
| A02 continuous dialogue | partial | Fixed command rehearsal is available; no relevant real-model dialogue or recorded continuous 3–5-minute session. |
| A03 real microphone | blocked | Microphone capability stays disabled; the staged phrase is fixed text, not captured audio/STT. |
| A04 speaking interruption | partial | Software playback/cancel races pass; no audible real speech interrupted into a new microphone-driven turn. |
| A05 late results / repeated interruptions | partial | Deterministic software regressions pass; corresponding current browser/device observation is still open. |
| A06 expressions/actions/environment/cause | partial | Authored effects and synthetic DOM behavior exist; current pixel-level rendered comparison remains pending. |
| A07 multimodal branch | partial | SVG/CSS animation exists in source; perceived motion has not been accepted in the current rendered app. |
| A08 failures and recovery | partial | Provider-shaped failures and software recovery are tested; actual permission/transport/device recovery and a recorded walkthrough are absent. |
| A09 real model and mode honesty | blocked | No live inference or JEV quality/calibration result; keep the provider blocker explicit and do not silently substitute fixtures. |
| A10 release materials | partial | Backup archive and offline checks exist; final matching expanded source/version, fresh setup evidence and required recording/gap report are still open. |

## Exact claim corrections and missing items

1. `README.md:4` says “文字和按住说话入口” in the unqualified feature summary. Suggested precision: “文字输入；离线排练的按住手势只提交固定合成文本，不采集麦克风。” The detailed clarification at lines 75–89 is good but comes later.
2. `README.md:9` starts “真实适配器已实现”. Keep “adapter code implemented” distinct from live capability: state plainly that there has been no Luna inference (Codex 401), Google ADC is pending, and the first scored JEV case timed out with no quality evidence. “Default disabled” alone does not tell a reader why live acceptance is absent.
3. `README.md:15` links the 11:04 integrated audit as “独立审查”, while `docs/mission/requirements-and-acceptance.md:266` points to the 12:36 overlay. Both predate the 12:56 candidate; keep them labeled historical and point delivery readers to a current dated status/gap record.
4. `README.md` needs three PDF-D05 additions: approximate actual time invested; a bounded two-week follow-on plan; and why explicit press-to-talk was chosen for this mobile-first scope. Do not present a plan as completed acceptance.
5. PDF-D07 needs current gap records that pair each unfinished capability with the concrete blocker and next action. At minimum: browser/device/real-audio observation; actual 3–5-minute recording; authorized model access/real inference; Google ADC and real microphone path; JEV timeout/no quality evidence; current-source/fresh-install/CI status. Preserve the 12:36 record as historical and add a new candidate-specific overlay.
6. Do not turn the 12:56 green receipt into a blanket “35/35 passed,” nor turn the verified archive into proof that the expanded Git tree or current release is published, CI-verified, secret-scanned, or matched to a recording.

## Remaining acceptance priorities

1. Keep the fixed rehearsal as an honest no-key/demo path; secure a user-authorized route for an actual model inference before claiming PDF-25/A09.
2. Complete actual browser/audio/microphone/device observation, including an audible interruption followed by a real new voice turn, and the relevant/irrelevant event comparison. Do not substitute software sample facts or static layout review.
3. Capture and review the required uninterrupted 3–5-minute walkthrough on the final version, including a failure/recovery and selected animation branch.
4. Update README/AI_USAGE/gap disclosure with the exact scope above; record any human validation only after a human actually performs it.
5. Establish a final source/version relationship and clean startup evidence. The archive-recovery report explicitly used preinstalled dependencies; do not overstate fresh install, expanded Git, CI, or publication status.

The locked requirements report remains unchanged. This note records evidence boundaries and the claim-level corrections needed for an honest final handoff.
