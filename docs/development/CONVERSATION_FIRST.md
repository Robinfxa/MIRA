# Direct-provider conversation and optional events

The direct `tools/live_provider.py` route now publishes each complete, schema-valid
subtitle cue before JEV input/output waits. There is no o1–o6 grading of ordinary
text and no whole-response seal review. The existing provider refusal, structured
output validation, current-context checks and presentation permit gate remain.
This does not guarantee textual truth or implement streaming JEV segmentation:
the currently implemented chunk fallback is the already bounded complete cue.
Natural-language instruction following and factual accuracy now rely on the
generation prompt and provider content policy for ordinary text. They are not
independently checked by the former o4 whole-response semantic review. Current
permission switches, Stop, schema and version checks remain hard runtime gates.

Only explicit pose, scene, story and affect proposals trigger the optional event
review. JEV checks current constraints, permissions, allowed controls and actual
presentation evidence; it does not execute changes. UNKNOWN, REJECT, malformed
answers, transport errors and request limits hold optional events while keeping
the text. A malformed generation JSON/schema is still a generation failure.

Speech uses the existing input permission observation and an admitted voice
backend. Restricted or uncertain speech leaves the independent text available.
Text and speech deliberately have different cue IDs: text is immediately readable,
speech gets its own new identity, and there is no duplicate subtitle or invented
audio receipt. This is not synchronized karaoke/word alignment. Client mute, Stop,
new input and permit revocation continue to block playback.

The Actor remains the only state writer. A same-cue subtitle receipt (or progress
on its separately permitted speech) can arrive during event review without a
paid retry. Different presentation changes or branch drift hold that event.
Only matching real presentation receipts update acknowledged outfit, expression,
scene and story history. The next generation and JEV context use these same
versioned facts. An invitation subtitle acknowledged before event approval is
reconciled by exact issued identity after approval, without reissuing it.

Legacy native/mock/replay routes retain their prior review policy. No new provider
calls, credentials, private recordings or persistent access were used to validate
this slice. Synthetic ASGI, Actor, JEV parser and receipt tests do not prove live
model quality, browser pixels, device voice or physical hearing.
